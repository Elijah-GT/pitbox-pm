"""Team roster — the assignee list, the login accounts, and who is an admin.

Reading the roster is open to any signed-in member (the assignee dropdown needs
it). Changing it is admin-only: creating accounts, setting passwords,
deactivating people and granting admin are exactly the actions that would let
someone give themselves more access than the Cloudflare policy intended.

The admin flag is what separates "can see the car" from "can change the car"
once the Access policy is a whole email domain rather than a list of names.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas, security
from ..database import get_db
from ..models import Member, Session as SessionRow

router = APIRouter(prefix="/api/members", tags=["members"])

# Promotions and demotions are logged: "who made X an admin" is the first
# question anyone asks when permissions surprise them.
log = logging.getLogger(__name__)


@router.get("", response_model=list[schemas.MemberOut])
def list_members(include_inactive: bool = False, db: Session = Depends(get_db)):
    stmt = select(Member).order_by(Member.name)
    if not include_inactive:
        stmt = stmt.where(Member.is_active.is_(True))
    return list(db.scalars(stmt))


@router.post("", response_model=schemas.MemberOut, status_code=201)
def create_member(
    payload: schemas.MemberIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Add someone to the roster. They cannot sign in until an admin sets a
    password for them (PUT /api/members/{id}/password)."""
    if payload.email:
        clash = db.scalar(select(Member).where(func.lower(Member.email) == payload.email.lower()))
        if clash:
            raise HTTPException(409, "A member with that email already exists.")
    # A name typed into the roster form came from a person, so it does not need
    # the "who are you really?" prompt that an email-derived name triggers.
    member = Member(**payload.model_dump(), name_confirmed=True)
    db.add(member)
    db.commit()
    db.refresh(member)
    return member


@router.patch("/{member_id}", response_model=schemas.MemberOut)
def update_member(
    member_id: int,
    payload: schemas.MemberIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(404, "Member not found")
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(member, field, value)
    db.commit()
    db.refresh(member)
    return member


@router.put("/{member_id}/password", status_code=204)
def set_member_password(
    member_id: int,
    payload: schemas.PasswordSet,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Set or reset someone's password — how a new member gets their first one.

    Every existing session for that member is dropped, so a password reset also
    signs out whoever might already be using the account.
    """
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(404, "Member not found")
    if not member.email:
        raise HTTPException(400, "Give this member an email address first — it is their username.")

    member.password_hash = security.hash_password(payload.password)
    for row in db.scalars(select(SessionRow).where(SessionRow.member_id == member_id)):
        db.delete(row)
    db.commit()


@router.delete("/{member_id}", status_code=204)
def deactivate_member(
    member_id: int,
    db: Session = Depends(get_db),
    admin: Member = Depends(security.require_admin),
):
    """Graduating seniors get deactivated, not deleted — their name should stay
    on the parts they designed. Their sessions end immediately."""
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(404, "Member not found")
    if member.id == admin.id:
        raise HTTPException(400, "You cannot deactivate your own account.")

    # Refuse to remove the last admin, or nobody can manage the roster again.
    if member.is_admin:
        remaining = db.scalar(
            select(func.count()).select_from(Member).where(
                Member.is_admin.is_(True), Member.is_active.is_(True), Member.id != member_id
            )
        ) or 0
        if remaining == 0:
            raise HTTPException(400, "That is the last admin. Promote someone else first.")

    member.is_active = False
    # Admin does not survive deactivation. Under Cloudflare Access a
    # deactivated member is reactivated automatically the next time they sign
    # in -- the Access policy is the authority on who may be here -- so leaving
    # the flag set would silently hand write access back to someone a lead
    # deliberately removed. Getting it back should take a deliberate promotion.
    member.is_admin = False
    for row in db.scalars(select(SessionRow).where(SessionRow.member_id == member_id)):
        db.delete(row)
    db.commit()


@router.patch("/{member_id}/admin", response_model=schemas.MemberOut)
def set_member_admin(
    member_id: int,
    payload: schemas.AdminUpdate,
    db: Session = Depends(get_db),
    admin: Member = Depends(security.require_admin),
):
    """Promote or demote a teammate. This is the whole "Manage Admins" screen.

    Its own endpoint on purpose. Folding it into PATCH /api/members/{id} would
    mean the roster form and the privilege switch share a payload, and the day
    somebody adds is_admin to MemberIn for convenience, every member gains the
    ability to promote themselves. Here it is one field with one guard.

    Two refusals, both about not locking the team out:

      * The last active admin cannot be demoted. Otherwise a lead tidying up
        before graduation leaves an instance nobody can ever write to again --
        recoverable only by someone with shell access to the server, which is
        exactly the dependency this screen exists to remove.
      * A deactivated member cannot be promoted, because they cannot sign in.
        Making them "the admin" would look like it worked and fix nothing.

    Demoting YOURSELF is allowed as long as another admin remains. A lead
    handing over at the end of the year should be able to step down without
    asking their successor to do it for them.
    """
    member = db.get(Member, member_id)
    if member is None:
        raise HTTPException(404, "Member not found")

    if payload.is_admin == member.is_admin:
        return member  # already there; nothing to do and nothing to guard

    if payload.is_admin:
        if not member.is_active:
            raise HTTPException(
                400,
                "That member is deactivated and cannot sign in. "
                "Reactivate them first, then make them an admin.",
            )
    elif member.is_active and security.count_admins(db) <= 1:
        # `member.is_active and` matters. count_admins() only counts admins who
        # can actually sign in, so a deactivated member holding the flag is not
        # in that number -- and without this clause, demoting them would be
        # refused for "being the last admin" while the real last admin is
        # somebody else entirely. That left the flag stuck on the account
        # forever, which is precisely the row you most want to be able to clear.
        raise HTTPException(
            400,
            "That is the last admin. Promote someone else first, or nobody "
            "will be able to change anything.",
        )

    member.is_admin = payload.is_admin
    db.commit()
    db.refresh(member)
    log.info(
        "%s %s %s", admin.email, "promoted" if payload.is_admin else "demoted", member.email
    )
    return member
