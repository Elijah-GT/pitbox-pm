"""File upload / download endpoints.

Datasheets, STEP files, KiCad projects, firmware binaries -- all attached to a
specific node so the information lives next to the part it describes instead of
in a Drive folder nobody can navigate.
"""
from __future__ import annotations

import mimetypes
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import schemas, storage
from ..database import get_db
from ..models import Attachment, Node

router = APIRouter(prefix="/api/attachments", tags=["attachments"])

# Only these are ever rendered in the browser. Everything else downloads, so a
# helpfully-uploaded .html or .svg cannot run script on our origin.
INLINE_SAFE = {"image/png", "image/jpeg", "image/gif", "image/webp"}


@router.get("", response_model=list[schemas.AttachmentOut])
def list_attachments(
    node_id: int = Query(...),
    include_old_versions: bool = False,
    db: Session = Depends(get_db),
):
    stmt = select(Attachment).where(Attachment.node_id == node_id)
    if not include_old_versions:
        stmt = stmt.where(Attachment.is_current.is_(True))
    return list(db.scalars(stmt.order_by(Attachment.filename, Attachment.version.desc())))


@router.post("", response_model=schemas.AttachmentOut, status_code=201)
def upload(
    node_id: int = Form(...),
    file: UploadFile = File(...),
    kind: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    uploaded_by_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
):
    """Attach a file to a node.

    Re-uploading the same filename to the same node creates version N+1 and
    demotes the previous one rather than overwriting it -- when someone drops a
    revised bracket STEP in at 2 a.m., last week's is still there.
    """
    node = db.get(Node, node_id)
    if node is None:
        raise HTTPException(404, f"Node {node_id} not found")

    safe_name = storage.sanitize_filename(file.filename or "upload")

    try:
        blob = storage.save_stream(file.file, declared_name=safe_name)
    except storage.UploadTooLarge:
        raise HTTPException(413, "File exceeds the configured upload limit.") from None
    except storage.BlockedFileType as exc:
        raise HTTPException(415, f"File type '{exc}' is not allowed.") from None

    previous_max = db.scalar(
        select(func.max(Attachment.version)).where(
            Attachment.node_id == node_id, Attachment.filename == safe_name
        )
    )
    if previous_max:
        db.execute(
            Attachment.__table__.update()
            .where(Attachment.node_id == node_id, Attachment.filename == safe_name)
            .values(is_current=False)
        )

    # Never trust the browser's Content-Type; re-derive it from the name we chose.
    guessed_type, _ = mimetypes.guess_type(safe_name)

    row = Attachment(
        node_id=node_id,
        filename=safe_name,
        content_type=guessed_type or "application/octet-stream",
        size_bytes=blob.size_bytes,
        sha256=blob.sha256,
        kind=kind or storage.guess_kind(safe_name),
        version=(previous_max or 0) + 1,
        is_current=True,
        notes=notes,
        uploaded_by_id=uploaded_by_id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.get("/{attachment_id}/download")
def download(attachment_id: int, inline: bool = False, db: Session = Depends(get_db)):
    row = db.get(Attachment, attachment_id)
    if row is None:
        raise HTTPException(404, "Attachment not found")

    path = storage.blob_path(row.sha256)
    if not path.exists():
        raise HTTPException(
            410, "The stored file is missing from disk. Check your storage/ directory or backups."
        )

    disposition = "inline" if (inline and row.content_type in INLINE_SAFE) else "attachment"
    # RFC 5987 encoding so names with spaces or non-ASCII survive the round trip.
    encoded = quote(row.filename)
    return FileResponse(
        path,
        media_type=row.content_type if disposition == "inline" else "application/octet-stream",
        headers={
            "Content-Disposition": f"{disposition}; filename*=UTF-8''{encoded}",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.delete("/{attachment_id}", status_code=204)
def delete_attachment(attachment_id: int, db: Session = Depends(get_db)):
    """Remove an attachment row, and the blob too if nothing else references it."""
    row = db.get(Attachment, attachment_id)
    if row is None:
        raise HTTPException(404, "Attachment not found")

    node_id, filename, sha = row.node_id, row.filename, row.sha256
    db.delete(row)
    db.flush()

    # Content-addressed storage means other nodes (or last year's car, or a
    # manufacturing part's drawing) may point at these same bytes. Only unlink
    # when the last reference anywhere is gone -- storage.still_referenced()
    # counts every table that can hold a blob, which is why this is not a plain
    # COUNT over attachments.
    storage.delete_blob_if_orphaned(sha, still_referenced=storage.still_referenced(db, sha))

    # Promote the newest surviving version so the node is never left with none marked current.
    survivor = db.scalar(
        select(Attachment)
        .where(Attachment.node_id == node_id, Attachment.filename == filename)
        .order_by(Attachment.version.desc())
        .limit(1)
    )
    if survivor is not None and not survivor.is_current:
        survivor.is_current = True

    db.commit()
