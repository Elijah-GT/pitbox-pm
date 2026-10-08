"""The project timeline: dated goals, and whether they have been met.

Separate from the part tree on purpose. A milestone is not a component of the
car -- it has no quantity, cost or vendor, and it does not belong in a BOM --
but it does have the one thing no node has: a date.

Who may do what follows the same line as everywhere else (see
app/security.py). Creating and deleting a goal is planning, so it is for team
leads. Editing one -- including ticking it off -- is any member, because the
person who finished the work is the one who knows it is finished, and making
them find a lead to tick a box is how a timeline stops being updated.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas, security
from ..database import get_db
from ..models import Member, Milestone, Node, Project

router = APIRouter(prefix="/api/milestones", tags=["milestones"])


def _get(db: Session, milestone_id: int) -> Milestone:
    row = db.get(Milestone, milestone_id)
    if row is None:
        raise HTTPException(404, "Milestone not found")
    return row


def _check_links(db: Session, project_id: int, owner_id: int | None, node_id: int | None) -> None:
    """Reject links that point nowhere, or into a different tree.

    The node check matters: without it you could attach a goal on the 2027 car
    to a part on the 2026 one, and the timeline would offer a jump that lands
    the reader in another project with no explanation.
    """
    if owner_id is not None and db.get(Member, owner_id) is None:
        raise HTTPException(400, "No such member.")
    if node_id is not None:
        node = db.get(Node, node_id)
        if node is None:
            raise HTTPException(400, "No such part.")
        if node.project_id != project_id:
            raise HTTPException(400, "That part belongs to a different tree.")


@router.get("", response_model=list[schemas.MilestoneOut])
def list_milestones(project_id: int, db: Session = Depends(get_db)):
    """Every goal on one project's timeline, earliest first.

    Scoped by project rather than returned whole: the timeline is always drawn
    for the tree you are looking at, and an unscoped list would mix seasons.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    return list(
        db.scalars(
            select(Milestone)
            .where(Milestone.project_id == project_id)
            # id as the tiebreak so two goals on the same day keep a stable
            # order -- otherwise they swap places between reloads and the
            # timeline looks like it is rearranging itself.
            .order_by(Milestone.due_date, Milestone.id)
        )
    )


@router.post("", response_model=schemas.MilestoneOut, status_code=201)
def create_milestone(
    payload: schemas.MilestoneIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, "Project not found")
    _check_links(db, payload.project_id, payload.owner_id, payload.node_id)

    row = Milestone(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{milestone_id}", response_model=schemas.MilestoneOut)
def update_milestone(
    milestone_id: int,
    payload: schemas.MilestoneUpdate,
    db: Session = Depends(get_db),
    _member: Member = Depends(security.require_member),
):
    row = _get(db, milestone_id)
    fields = payload.model_dump(exclude_unset=True)

    _check_links(
        db,
        row.project_id,
        fields.get("owner_id", row.owner_id),
        fields.get("node_id", row.node_id),
    )

    if "done" in fields and fields["done"] != row.done:
        # Stamped here rather than by the caller, so the record of when a goal
        # was actually met cannot be backdated from the client.
        row.done_at = datetime.now(timezone.utc) if fields["done"] else None

    for field, value in fields.items():
        setattr(row, field, value)

    db.commit()
    db.refresh(row)
    return row


@router.delete("/{milestone_id}", status_code=204)
def delete_milestone(
    milestone_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    db.delete(_get(db, milestone_id))
    db.commit()
