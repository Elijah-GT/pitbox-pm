"""The cut list: parts the shop has to make, and the drawing for each.

Flat on purpose. The assembly tree answers "what is the car made of"; this
answers "what do we have to cut this week". They are different lists -- three
tube lengths for one A-arm, plus jigs and fixtures that are not part of the car
at all -- so this is a list, not another tree.

`name` is meant to match the part's name in Onshape exactly. That string is the
whole integration: nothing to keep in sync, and the same words find the part in
either system.

Who may do what follows the line used everywhere else (app/security.py):
adding and deleting a part is planning, so it is for leads. Editing one --
including uploading its drawing and marking it done -- is any member, because
the person at the bandsaw is the one who knows.
"""
from __future__ import annotations

import mimetypes
from datetime import datetime, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import schemas, security, storage
from ..database import get_db
from ..models import Member, MfgPart, Project

router = APIRouter(prefix="/api/mfg-parts", tags=["manufacturing"])

# Rendered in the browser rather than downloaded. Images are inert. PDF is here
# because an Onshape drawing is almost always a PDF, and a cut list whose
# drawings you cannot look at is just a spreadsheet. A PDF can carry
# JavaScript, and it is NOT sandboxed -- a sandbox stops Chrome's viewer from
# rendering it at all; serve_drawing explains the trade-off and the real fix.
# Anything else, from a .dxf to a helpfully-renamed .html, downloads.
INLINE_TYPES = {
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/webp",
    "application/pdf",
}


def _get(db: Session, part_id: int) -> MfgPart:
    row = db.get(MfgPart, part_id)
    if row is None:
        raise HTTPException(404, "Part not found")
    return row


def _check_assignee(db: Session, assignee_id: int | None) -> None:
    if assignee_id is not None and db.get(Member, assignee_id) is None:
        raise HTTPException(400, "No such member.")


def _release_drawing(db: Session, row: MfgPart) -> None:
    """Forget the current drawing, and free its bytes if nothing else wants them.

    Called before replacing a drawing as well as when clearing one, so a part
    that has been through five revisions does not leave five dead blobs behind.
    """
    old = row.drawing_sha256
    row.drawing_sha256 = None
    row.drawing_filename = None
    row.drawing_content_type = None
    row.drawing_size_bytes = None
    row.drawing_uploaded_at = None
    if not old:
        return
    # Flush first: still_referenced() must not count the row we just cleared.
    db.flush()
    storage.delete_blob_if_orphaned(old, still_referenced=storage.still_referenced(db, old))


@router.get("", response_model=list[schemas.MfgPartOut])
def list_parts(project_id: int = Query(...), db: Session = Depends(get_db)):
    """One project's cut list.

    Ordered by subsystem then name so it reads the way the shop works --
    everything for the rollcage together. Parts with no subsystem sort last
    rather than first: they are the odds and ends, not the headline.
    """
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    rows = list(db.scalars(select(MfgPart).where(MfgPart.project_id == project_id)))
    rows.sort(key=lambda r: (r.subsystem is None, (r.subsystem or "").lower(), r.name.lower()))
    return rows


@router.post("", response_model=schemas.MfgPartOut, status_code=201)
def create_part(
    payload: schemas.MfgPartIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    if db.get(Project, payload.project_id) is None:
        raise HTTPException(404, "Project not found")
    _check_assignee(db, payload.assignee_id)

    row = MfgPart(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.patch("/{part_id}", response_model=schemas.MfgPartOut)
def update_part(
    part_id: int,
    payload: schemas.MfgPartUpdate,
    db: Session = Depends(get_db),
    _member: Member = Depends(security.require_member),
):
    row = _get(db, part_id)
    fields = payload.model_dump(exclude_unset=True)
    _check_assignee(db, fields.get("assignee_id", row.assignee_id))

    for field, value in fields.items():
        setattr(row, field, value)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{part_id}", status_code=204)
def delete_part(
    part_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    row = _get(db, part_id)
    # Free the drawing's bytes on the way out, or deleting parts would slowly
    # fill the volume with files nothing points at.
    _release_drawing(db, row)
    db.delete(row)
    db.commit()


# --- the drawing -------------------------------------------------------------

@router.put("/{part_id}/drawing", response_model=schemas.MfgPartOut)
def upload_drawing(
    part_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _member: Member = Depends(security.require_member),
):
    """Attach or replace this part's drawing.

    PUT rather than POST because there is exactly one: uploading a revision
    replaces the old one. The bytes go to the same deduplicated store as node
    attachments, so a drawing that is also attached to a tree node is stored
    once rather than twice.
    """
    row = _get(db, part_id)
    safe_name = storage.sanitize_filename(file.filename or "drawing")

    try:
        blob = storage.save_stream(file.file, declared_name=safe_name)
    except storage.UploadTooLarge:
        raise HTTPException(413, "File exceeds the configured upload limit.") from None
    except storage.BlockedFileType as exc:
        raise HTTPException(415, f"File type '{exc}' is not allowed.") from None

    _release_drawing(db, row)

    # Never trust the browser's Content-Type; re-derive it from the name we chose.
    guessed, _ = mimetypes.guess_type(safe_name)
    row.drawing_sha256 = blob.sha256
    row.drawing_filename = safe_name
    row.drawing_content_type = guessed or "application/octet-stream"
    row.drawing_size_bytes = blob.size_bytes
    row.drawing_uploaded_at = datetime.now(timezone.utc)

    db.commit()
    db.refresh(row)
    return row


@router.get("/{part_id}/drawing")
def serve_drawing(part_id: int, download: bool = False, db: Session = Depends(get_db)):
    """Show the drawing, or hand it over as a file.

    One URL for both, because the browser decides what to do from the
    Content-Disposition: the <img>/<iframe> in the UI uses this URL bare, and
    the Download button adds ?download=1.
    """
    row = _get(db, part_id)
    if not row.drawing_sha256:
        raise HTTPException(404, "This part has no drawing yet.")

    path = storage.blob_path(row.drawing_sha256)
    if not path.exists():
        raise HTTPException(
            410, "The stored drawing is missing from disk. Check storage/ or your backups."
        )

    content_type = row.drawing_content_type or "application/octet-stream"
    inline = not download and content_type in INLINE_TYPES
    encoded = quote(row.drawing_filename or "drawing")

    return FileResponse(
        path,
        media_type=content_type if inline else "application/octet-stream",
        headers={
            "Content-Disposition": (
                f"{'inline' if inline else 'attachment'}; filename*=UTF-8''{encoded}"
            ),
            # nosniff matters most here: it stops the browser second-guessing
            # the type we declared, which is what turns a mislabelled upload
            # into a script running on this origin.
            "X-Content-Type-Options": "nosniff",
            # NO `Content-Security-Policy: sandbox`, and no sandbox attribute
            # on the iframe that embeds this. Both were tried and both break
            # the feature: Chrome's PDF viewer is itself JavaScript, so a
            # sandboxed PDF response is either refused outright ("This page has
            # been blocked by Chrome") or silently downloaded instead of shown.
            # `sandbox allow-scripts` does not help either -- still downloaded.
            # You can sandbox a PDF or display it, not both.
            #
            # What protects us instead:
            #   * the inline allowlist above is short and closed -- .html and
            #     .svg download rather than render, so the obvious script
            #     vectors never execute here at all;
            #   * uploads require a signed Cloudflare Access token, so this is
            #     not a public drop box;
            #   * storage.BLOCKED_EXTENSIONS refuses executables on the way in.
            #
            # The residual risk is a teammate uploading a PDF with script in
            # it, which would then run on this origin. If that ever matters,
            # the real fix is serving uploads from a SEPARATE hostname so they
            # are cross-origin by construction (the googleusercontent.com
            # pattern), not a sandbox header that stops the drawings working.
        },
    )


@router.delete("/{part_id}/drawing", response_model=schemas.MfgPartOut)
def clear_drawing(
    part_id: int,
    db: Session = Depends(get_db),
    _member: Member = Depends(security.require_member),
):
    """Remove the drawing but keep the part.

    Member-level like uploading, not admin-level like deleting the part:
    replacing a drawing already discards the previous one, so making removal
    the stricter of the two would be a rule with no teeth.
    """
    row = _get(db, part_id)
    _release_drawing(db, row)
    db.commit()
    db.refresh(row)
    return row
