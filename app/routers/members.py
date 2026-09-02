"""Team roster — the assignee list, and the login accounts.

Reading the roster is open to any signed-in member (the assignee dropdown needs
it). Changing it is admin-only: creating accounts, setting passwords and
deactivating people are exactly the actions that would let someone grant
themselves access.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas, security
from ..database import get_db
from ..models import Member, Session as SessionRow

router = APIRouter(prefix="/api/members", tags=["members"])


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
    for row in db.scalars(select(SessionRow).where(SessionRow.member_id == member_id)):
        db.delete(row)
    db.commit()
