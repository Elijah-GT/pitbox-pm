"""The doomsday countdown in the top bar: one label and one moment.

There is exactly one for the whole team -- usually competition -- so it lives
under a single key in app_meta rather than a table of its own.

Reading it is for anyone signed in. Setting or clearing it is for admins: it is
the team's deadline, not a personal timer, and a countdown anyone could move
would stop meaning anything. Enforced twice, as for Learn: absent from
security.MEMBER_WRITABLE, and require_admin on each write.
"""
from __future__ import annotations

import json
from datetime import timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import schemas, security
from ..config import settings
from ..database import get_db
from ..models import AppMeta, Member

router = APIRouter(prefix="/api/countdown", tags=["countdown"])

KEY = "countdown"


def _read(db: Session) -> schemas.CountdownOut:
    look = {"doomsday": settings.doomsday}
    row = db.get(AppMeta, KEY)
    if row is None:
        return schemas.CountdownOut(**look)
    try:
        data = json.loads(row.value)
        return schemas.CountdownOut(label=data["label"], at=data["at"], **look)
    except (ValueError, KeyError, TypeError):
        # A value mangled by hand shows as "not set" rather than failing the
        # top bar on every page for everyone.
        return schemas.CountdownOut(**look)


@router.get("", response_model=schemas.CountdownOut)
def get_countdown(db: Session = Depends(get_db)):
    """Both fields null until an admin sets one."""
    return _read(db)


@router.put("", response_model=schemas.CountdownOut)
def set_countdown(
    payload: schemas.CountdownIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    # Stored in UTC. The moment is what matters; every viewer's browser shows
    # it counting down in its own clock.
    value = json.dumps({
        "label": payload.label,
        "at": payload.at.astimezone(timezone.utc).isoformat(),
    })
    row = db.get(AppMeta, KEY)
    if row is None:
        db.add(AppMeta(key=KEY, value=value))
    else:
        row.value = value
    db.commit()
    return _read(db)


@router.delete("", status_code=204)
def clear_countdown(
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    row = db.get(AppMeta, KEY)
    if row is not None:
        db.delete(row)
        db.commit()
