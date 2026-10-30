"""Resources: research the team finds -- design reports, papers, videos, datasheets.

Not Learn. Learn is the team's guidance, written and kept by leads; this is the
research behind it, and finding it is everyone's job.

WHO MAY DO WHAT
---------------
  * anyone signed in can ADD a resource -- the same reasoning as asking for a
    part to be bought: the list is only useful if adding to it is easy;
  * whoever added one can edit it, attach or replace its file, or remove it,
    and an admin can do the same to any of them;
  * nobody else can: a member cannot rewrite or delete what a teammate found.

The route-level allowlist (security.MEMBER_WRITABLE) lets members reach these
routes at all; which rows they may touch is decided here, from the row.
"""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import schemas, security, storage
from ..database import get_db
from ..models import Member, Resource
# Same rule as shop drawings for what displays in the browser rather than
# downloading -- see mfg.serve_drawing for why PDFs are not sandboxed.
from .mfg import INLINE_TYPES

router = APIRouter(prefix="/api/resources", tags=["resources"])

NOT_YOURS = (
    "You can change or remove resources you added yourself. Ask a team lead "
    "about anyone else's."
)


def _get(db: Session, resource_id: int) -> Resource:
    row = db.get(Resource, resource_id)
    if row is None:
        raise HTTPException(404, "Resource not found")
    return row


def _check_can_change(row: Resource, member: Member) -> None:
    if member.is_admin:
        return
    if row.added_by_id is not None and row.added_by_id == member.id:
        return
    raise HTTPException(403, NOT_YOURS)


def _free(db: Session, sha: str | None) -> None:
    """Free a blob nothing points at any more. Call AFTER commit, so a failed
    commit leaves at worst an orphan for gc_blobs.py, never a row pointing at
    deleted bytes."""
    if sha:
        storage.delete_blob_if_orphaned(sha, still_referenced=storage.still_referenced(db, sha))


def _out(row: Resource) -> schemas.ResourceOut:
    """Serialize while the session is still open: added_by_name reads a
    relationship, and lazy-loading it after the request's session has closed
    would fail."""
    return schemas.ResourceOut.model_validate(row)


def _clear_file(row: Resource) -> str | None:
    """Forget the row's file. Returns its address for the caller to free."""
    old = row.file_sha256
    row.file_sha256 = None
    row.file_name = None
    row.file_content_type = None
    row.file_size_bytes = None
    row.file_uploaded_at = None
    return old


@router.get("", response_model=list[schemas.ResourceOut])
def list_resources(db: Session = Depends(get_db)):
    """Everything, newest first -- the UI filters and searches in the browser."""
    return [_out(r) for r in db.scalars(
        select(Resource)
        .options(selectinload(Resource.added_by))
        .order_by(Resource.created_at.desc(), Resource.id.desc())
    )]


@router.post("", response_model=schemas.ResourceOut, status_code=201)
def create_resource(
    payload: schemas.ResourceIn,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    # Who found it comes from the signed-in identity, never the request body:
    # it is what decides who may edit it later.
    row = Resource(**payload.model_dump(), added_by_id=member.id)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.patch("/{resource_id}", response_model=schemas.ResourceOut)
def update_resource(
    resource_id: int,
    payload: schemas.ResourceUpdate,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    row = _get(db, resource_id)
    _check_can_change(row, member)

    fields = payload.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"] is None:
        raise HTTPException(422, "A resource needs a title.")
    if "kind" in fields and fields["kind"] is None:
        fields.pop("kind")
    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return _out(row)


@router.delete("/{resource_id}", status_code=204)
def delete_resource(
    resource_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    row = _get(db, resource_id)
    _check_can_change(row, member)
    sha = row.file_sha256
    db.delete(row)
    db.commit()
    _free(db, sha)


# --- the file ----------------------------------------------------------------

@router.put("/{resource_id}/file", response_model=schemas.ResourceOut)
def upload_file(
    resource_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    """Attach a file -- the PDF of a paper, a design report. Replaces any
    previous one: a resource is one thing, not a folder."""
    row = _get(db, resource_id)
    _check_can_change(row, member)
    safe_name = storage.sanitize_filename(file.filename or "resource")

    try:
        blob = storage.save_stream(file.file, declared_name=safe_name)
    except storage.UploadTooLarge:
        raise HTTPException(413, "File exceeds the configured upload limit.") from None
    except storage.BlockedFileType as exc:
        raise HTTPException(415, f"File type '{exc}' is not allowed.") from None

    old = _clear_file(row)
    # Never trust the browser's Content-Type; derive it from the name we chose.
    guessed, _ = mimetypes.guess_type(safe_name)
    row.file_sha256 = blob.sha256
    row.file_name = safe_name
    row.file_content_type = guessed or "application/octet-stream"
    row.file_size_bytes = blob.size_bytes
    row.file_uploaded_at = datetime.now(timezone.utc)
    db.commit()
    if old != blob.sha256:
        _free(db, old)
    db.refresh(row)
    return _out(row)


@router.get("/{resource_id}/file")
def serve_file(resource_id: int, download: bool = False, db: Session = Depends(get_db)):
    row = _get(db, resource_id)
    if not row.file_sha256:
        raise HTTPException(404, "This resource has no file.")
    path = storage.blob_path(row.file_sha256)
    if not path.exists():
        raise HTTPException(410, "The stored file is missing from disk. Check storage/ or your backups.")

    content_type = row.file_content_type or "application/octet-stream"
    inline = not download and content_type in INLINE_TYPES
    return FileResponse(
        path,
        media_type=content_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"{'inline' if inline else 'attachment'}; "
                f"filename*=UTF-8''{quote(row.file_name or 'resource')}"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{resource_id}/file", response_model=schemas.ResourceOut)
def clear_file(
    resource_id: int,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_member),
):
    row = _get(db, resource_id)
    _check_can_change(row, member)
    old = _clear_file(row)
    db.commit()
    _free(db, old)
    db.refresh(row)
    return _out(row)
