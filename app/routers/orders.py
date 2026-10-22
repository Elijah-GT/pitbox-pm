"""Purchase requests: parts somebody needs bought, and where each order has got to.

WHO MAY DO WHAT
---------------
This is the one place the usual line -- members edit, leads add and delete --
bends, because the whole point of the list is that anyone can ask:

  * anyone signed in can SUBMIT a request;
  * the requester can change or cancel their own request while it is still
    waiting -- once a lead has acted on it, it is locked to them;
  * approving, denying, ordering and shipping are for leads, because those are
    decisions about the team's money;
  * ANY member can mark something on order as received. Whoever opened the
    box knows it arrived, and making them find a lead first is how an order
    list goes stale -- the same reasoning as ticking off a timeline goal;
  * deleting a request is for leads. A requester withdraws by cancelling, so
    the record of what was asked for survives.

The route-level guard (security.MEMBER_WRITABLE) can only say "members may
PATCH this route". Which rows and which statuses is decided here, from the row
itself, because it depends on who asked and where the order has got to.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas, security
from ..database import get_db
from ..models import Member, Project, PurchaseRequest

router = APIRouter(prefix="/api/purchase-requests", tags=["orders"])

# What a requester may change on their own request while it waits.
REQUESTER_FIELDS = frozenset({
    "item", "vendor", "url", "part_number", "quantity",
    "unit_cost_cents", "notes", "subsystem", "needed_by",
})

# Bought and on its way. From either of these, any member may mark it received.
IN_TRANSIT = frozenset({"ordered", "shipped"})

# Columns that cannot be NULL. An explicit null in a PATCH means "clear it",
# which for these would be a 500 from the database instead of a useful 422.
_REQUIRED = ("item", "quantity")

LEAD_ONLY_STATUS = (
    "Approving, denying and placing orders is for team leads. You can cancel "
    "your own request while it is still waiting, and mark anything on order as "
    "received."
)


def _get(db: Session, request_id: int) -> PurchaseRequest:
    row = db.get(PurchaseRequest, request_id)
    if row is None:
        raise HTTPException(404, "Request not found")
    return row


def _event(status: str, member: Member) -> dict:
    return {
        "status": status,
        "at": datetime.now(timezone.utc).isoformat(),
        "by": member.id,
        # Copied, not just referenced: the history should still say who
        # approved it after that person has left the roster.
        "by_name": member.name,
    }


def _set_status(row: PurchaseRequest, status: str, member: Member) -> None:
    if status == row.status:
        return
    row.status = status
    # Reassigned rather than appended to: SQLAlchemy does not notice changes
    # made inside a JSON list, so .append() would be silently lost on commit.
    row.history = [*(row.history or []), _event(status, member)]


def _check_member_edit(row: PurchaseRequest, fields: dict, member: Member) -> None:
    """The rules for someone who is not a lead. Raises 403 with the reason."""
    own = row.requested_by_id == member.id
    details = set(fields) - {"status"}

    if details:
        if not details <= REQUESTER_FIELDS:
            raise HTTPException(
                403, "Order and tracking numbers are filled in by whoever places "
                "the order, which is a team lead.",
            )
        if not own:
            raise HTTPException(403, "You can only change requests you made yourself.")
        if row.status != "requested":
            raise HTTPException(
                403, "A team lead has already acted on this request, so it is "
                "locked. Ask a lead if something about it needs to change.",
            )

    status = fields.get("status")
    if status is None or status == row.status:
        return
    if status == "cancelled" and own and row.status == "requested":
        return
    if status == "received" and row.status in IN_TRANSIT:
        return
    raise HTTPException(403, LEAD_ONLY_STATUS)


@router.get("", response_model=list[schemas.PurchaseRequestOut])
def list_requests(project_id: int = Query(...), db: Session = Depends(get_db)):
    """One project's requests, newest first. The UI groups them by status."""
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    return list(db.scalars(
        select(PurchaseRequest)
        .where(PurchaseRequest.project_id == project_id)
        .order_by(PurchaseRequest.created_at.desc(), PurchaseRequest.id.desc())
    ))


@router.post("", response_model=schemas.PurchaseRequestOut, status_code=201)
def create_request(
    payload: schemas.PurchaseRequestIn,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, "Project not found")

    fields = payload.model_dump()
    status = fields.pop("status") or "requested"
    if not member.is_admin and (
        status != "requested" or fields.get("order_number") or fields.get("tracking_number")
    ):
        raise HTTPException(
            403, "A new request starts as Requested. A team lead moves it on from there.",
        )

    row = PurchaseRequest(
        **fields,
        status=status,
        # From the signed-in identity, never from the request body.
        requested_by_id=member.id,
        history=[_event(status, member)],
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{request_id}", response_model=schemas.PurchaseRequestOut)
def update_request(
    request_id: int,
    payload: schemas.PurchaseRequestUpdate,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    row = _get(db, request_id)
    fields = payload.model_dump(exclude_unset=True)

    for key in _REQUIRED:
        if key in fields and fields[key] is None:
            raise HTTPException(422, f"{key} cannot be empty.")
    if not member.is_admin:
        _check_member_edit(row, fields, member)

    status = fields.pop("status", None)
    for field, value in fields.items():
        setattr(row, field, value)
    if status is not None:
        _set_status(row, status, member)

    db.commit()
    db.refresh(row)
    return row


@router.delete("/{request_id}", status_code=204)
def delete_request(
    request_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    row = _get(db, request_id)
    db.delete(row)
    db.commit()
