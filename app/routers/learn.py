"""Learn: the team's own reference library, modelled on frcdesign.org.

A SECTION is a card on the Learn page -- "Suspension", "Welding" -- with a
picture, a summary, and a chip for each of its pages. A PAGE is a writeup in
Markdown followed by "CAD references": cards linking to models in Onshape.

Not scoped to a project. See models.LearnSection for why.

WHO MAY DO WHAT is NOT the usual line. Elsewhere members edit and leads add
and delete; here everyone reads and only leads change anything. These pages
are the team's guidance -- how we weld, how we name parts -- and guidance
that any signed-in student can rewrite is not guidance. So every write below
requires an admin: adding, deleting, editing, reordering, and pictures.

Every save records who made it, so "last edited by" is always on the page,
and saves carry the version they started from so two leads editing at once
cannot silently overwrite each other.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .. import schemas, security, storage
from ..database import get_db
from ..models import LearnImage, LearnPage, LearnSection, Member

router = APIRouter(prefix="/api/learn", tags=["learn"])

# Pictures only, keyed by storage.extension_of() -- which keeps the dot.
# Mapped explicitly rather than through mimetypes.guess_type, which reads the
# Windows registry and has been known to answer image/x-png or image/pjpeg:
# fine for a download, wrong for an allowlist.
#
# SVG is deliberately absent: it is a document that can carry script, and
# these are served inline on this origin.
IMAGE_TYPES = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
}


def image_url(image_id: int) -> str:
    return f"/api/learn/images/{image_id}"


def _section(db: Session, section_id: int) -> LearnSection:
    row = db.get(LearnSection, section_id)
    if row is None:
        raise HTTPException(404, "Section not found")
    return row


def _page(db: Session, page_id: int) -> LearnPage:
    row = db.get(LearnPage, page_id)
    if row is None:
        raise HTTPException(404, "Page not found")
    return row


def _section_out(row: LearnSection) -> schemas.LearnSectionOut:
    return schemas.LearnSectionOut(
        id=row.id,
        title=row.title,
        summary=row.summary,
        group=row.group,
        icon=row.icon,
        position=row.position,
        image_url=image_url(row.image_id) if row.image_id else None,
        pages=[schemas.LearnPageSummary.model_validate(p) for p in row.pages],
    )


def _page_out(row: LearnPage) -> schemas.LearnPageOut:
    out = schemas.LearnPageOut.model_validate(row)
    out.updated_by_name = row.updated_by.name if row.updated_by else None
    return out


def _free(db: Session, hashes: set[str]) -> None:
    """Delete blobs nothing points at any more. Call AFTER commit.

    After, not before: if the commit failed, freeing first would leave rows
    pointing at bytes that are gone. Freeing after means the worst case is an
    orphan, which scripts/gc_blobs.py reclaims.
    """
    for sha in hashes:
        storage.delete_blob_if_orphaned(sha, still_referenced=storage.still_referenced(db, sha))


def _swap(rows: list, row, direction: str) -> None:
    """Move `row` one step within `rows`, then renumber 0..n so the positions
    stay dense -- which also repairs any duplicates left behind by hand edits."""
    i = rows.index(row)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(rows):
        rows[i], rows[j] = rows[j], rows[i]
    for n, each in enumerate(rows):
        each.position = n


def _next_position(db: Session, column, *where) -> int:
    top = db.scalar(select(func.max(column)).where(*where))
    return 0 if top is None else top + 1


# --- the index ---------------------------------------------------------------

@router.get("", response_model=schemas.LearnLibraryOut)
def library(db: Session = Depends(get_db)):
    """Every section with its page titles: the whole Learn page in one call."""
    rows = db.scalars(
        select(LearnSection)
        .options(selectinload(LearnSection.pages))
        .order_by(LearnSection.position, LearnSection.id)
    )
    return schemas.LearnLibraryOut(sections=[_section_out(r) for r in rows])


# --- sections ----------------------------------------------------------------

@router.post("/sections", response_model=schemas.LearnSectionOut, status_code=201)
def create_section(
    payload: schemas.LearnSectionIn,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    row = LearnSection(
        **payload.model_dump(),
        position=_next_position(db, LearnSection.position, LearnSection.group == payload.group),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _section_out(row)


@router.patch("/sections/{section_id}", response_model=schemas.LearnSectionOut)
def update_section(
    section_id: int,
    payload: schemas.LearnSectionUpdate,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    row = _section(db, section_id)
    fields = payload.model_dump(exclude_unset=True)
    if "title" in fields and fields["title"] is None:
        raise HTTPException(422, "A section needs a title.")
    for key in ("group", "icon"):
        if key in fields and fields[key] is None:
            fields.pop(key)

    moving_group = "group" in fields and fields["group"] != row.group
    for field, value in fields.items():
        setattr(row, field, value)
    if moving_group:
        # Lands at the end of its new heading rather than colliding with
        # whatever already holds its old position there.
        row.position = _next_position(
            db, LearnSection.position,
            LearnSection.group == row.group, LearnSection.id != row.id,
        )
    db.commit()
    db.refresh(row)
    return _section_out(row)


@router.post("/sections/{section_id}/move", response_model=schemas.LearnLibraryOut)
def move_section(
    section_id: int,
    payload: schemas.LearnMove,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Reorder within its heading. Admin-only, unlike reordering tree nodes:
    the order of the guidance is part of the guidance."""
    row = _section(db, section_id)
    siblings = list(db.scalars(
        select(LearnSection)
        .where(LearnSection.group == row.group)
        .order_by(LearnSection.position, LearnSection.id)
    ))
    _swap(siblings, row, payload.direction)
    db.commit()
    return library(db)


@router.delete("/sections/{section_id}", status_code=204)
def delete_section(
    section_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Delete a section, its pages and every picture uploaded to it."""
    row = _section(db, section_id)
    hashes = set(db.scalars(select(LearnImage.sha256).where(LearnImage.section_id == row.id)))
    # Pages and images go with it through ON DELETE CASCADE.
    db.delete(row)
    db.commit()
    _free(db, hashes)


@router.put("/sections/{section_id}/image", response_model=schemas.LearnSectionOut)
def set_section_image(
    section_id: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_admin),
):
    """Put a render on the card. Replaces any previous one."""
    row = _section(db, section_id)
    image = _store_image(db, file, member, section_id=row.id, page_id=None)
    freed = _drop_card_image(db, row)
    row.image_id = image.id
    db.commit()
    _free(db, freed)
    db.refresh(row)
    return _section_out(row)


@router.delete("/sections/{section_id}/image", response_model=schemas.LearnSectionOut)
def clear_section_image(
    section_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Back to the line-art icon."""
    row = _section(db, section_id)
    freed = _drop_card_image(db, row)
    db.commit()
    _free(db, freed)
    db.refresh(row)
    return _section_out(row)


def _drop_card_image(db: Session, row: LearnSection) -> set[str]:
    """Forget the section's current card picture. Returns the bytes to free
    once the caller has committed."""
    old = db.get(LearnImage, row.image_id) if row.image_id else None
    row.image_id = None
    if old is None:
        return set()
    db.delete(old)
    return {old.sha256}


# --- pages -------------------------------------------------------------------

@router.post("/pages", response_model=schemas.LearnPageOut, status_code=201)
def create_page(
    payload: schemas.LearnPageIn,
    db: Session = Depends(get_db),
    admin: Member = Depends(security.require_admin),
):
    section = _section(db, payload.section_id)
    row = LearnPage(
        section_id=section.id,
        title=payload.title,
        body="",
        references=[],
        position=_next_position(db, LearnPage.position, LearnPage.section_id == section.id),
        updated_by_id=admin.id,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return _page_out(row)


@router.get("/pages/{page_id}", response_model=schemas.LearnPageOut)
def get_page(page_id: int, db: Session = Depends(get_db)):
    return _page_out(_page(db, page_id))


@router.patch("/pages/{page_id}", response_model=schemas.LearnPageOut)
def update_page(
    page_id: int,
    payload: schemas.LearnPageUpdate,
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_admin),
):
    row = _page(db, page_id)

    if payload.base_version is not None and payload.base_version != row.version:
        who = row.updated_by.name if row.updated_by else "Someone else"
        raise HTTPException(
            409,
            f"{who} saved this page while you were editing it, so your changes "
            "were NOT saved. Copy them somewhere safe, reload the page, and add "
            "them back in.",
        )

    fields = payload.model_dump(exclude_unset=True, exclude={"base_version", "references"})
    if "title" in fields and fields["title"] is None:
        raise HTTPException(422, "A page needs a title.")
    if "body" in fields and fields["body"] is None:
        fields["body"] = ""

    if payload.references is not None:
        wanted = {r.image_id for r in payload.references if r.image_id is not None}
        if wanted:
            found = set(db.scalars(
                select(LearnImage.id).where(
                    LearnImage.id.in_(wanted), LearnImage.section_id == row.section_id
                )
            ))
            if wanted - found:
                raise HTTPException(400, "A reference image does not belong to this section.")
        row.references = [r.model_dump() for r in payload.references]

    for field, value in fields.items():
        setattr(row, field, value)
    row.version += 1
    row.updated_by_id = member.id
    # Set explicitly: a save that only changes references touches no column
    # SQLAlchemy's onupdate watches for in the same way.
    row.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    return _page_out(row)


@router.post("/pages/{page_id}/move", response_model=schemas.LearnLibraryOut)
def move_page(
    page_id: int,
    payload: schemas.LearnMove,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Reorder within its section -- which, for the CAD guide, is reading order."""
    row = _page(db, page_id)
    siblings = list(db.scalars(
        select(LearnPage)
        .where(LearnPage.section_id == row.section_id)
        .order_by(LearnPage.position, LearnPage.id)
    ))
    _swap(siblings, row, payload.direction)
    db.commit()
    # The sections' already-loaded page lists predate the swap.
    db.expire_all()
    return library(db)


@router.delete("/pages/{page_id}", status_code=204)
def delete_page(
    page_id: int,
    db: Session = Depends(get_db),
    _admin: Member = Depends(security.require_admin),
):
    """Delete a page and the pictures uploaded while writing it."""
    row = _page(db, page_id)
    hashes = set(db.scalars(select(LearnImage.sha256).where(LearnImage.page_id == row.id)))
    db.delete(row)
    db.commit()
    _free(db, hashes)


# --- pictures ----------------------------------------------------------------

def _store_image(
    db: Session, file: UploadFile, member: Member, *, section_id: int, page_id: int | None,
) -> LearnImage:
    """Validate, store and record one picture. Flushed, not committed."""
    safe_name = storage.sanitize_filename(file.filename or "image.png")
    content_type = IMAGE_TYPES.get(storage.extension_of(safe_name))
    # Checked BEFORE the bytes are written, so a refused upload leaves nothing
    # behind on disk.
    if content_type is None:
        raise HTTPException(415, "Pictures only: PNG, JPEG, GIF or WebP.")

    try:
        blob = storage.save_stream(file.file, declared_name=safe_name)
    except storage.UploadTooLarge:
        raise HTTPException(413, "File exceeds the configured upload limit.") from None
    except storage.BlockedFileType as exc:
        raise HTTPException(415, f"File type '{exc}' is not allowed.") from None

    image = LearnImage(
        section_id=section_id,
        page_id=page_id,
        sha256=blob.sha256,
        filename=safe_name,
        content_type=content_type,
        size_bytes=blob.size_bytes,
        uploaded_by_id=member.id,
    )
    db.add(image)
    db.flush()
    return image


@router.post("/images", response_model=schemas.LearnImageOut, status_code=201)
def upload_image(
    file: UploadFile = File(...),
    section_id: int = Form(...),
    page_id: int | None = Form(default=None),
    db: Session = Depends(get_db),
    member: Member = Depends(security.require_admin),
):
    """A picture for a writeup or a CAD reference. Returns the URL to use.

    Admin-only, because putting a photo into a page is part of editing it.
    """
    section = _section(db, section_id)
    if page_id is not None and _page(db, page_id).section_id != section.id:
        raise HTTPException(400, "That page is not in that section.")

    image = _store_image(db, file, member, section_id=section.id, page_id=page_id)
    db.commit()
    return schemas.LearnImageOut(id=image.id, url=image_url(image.id), filename=image.filename)


@router.get("/images/{image_id}")
def serve_image(image_id: int, db: Session = Depends(get_db)):
    image = db.get(LearnImage, image_id)
    if image is None:
        raise HTTPException(404, "Image not found")
    path = storage.blob_path(image.sha256)
    if not path.exists():
        raise HTTPException(
            410, "The stored image is missing from disk. Check storage/ or your backups."
        )
    return FileResponse(
        path,
        media_type=image.content_type,
        headers={
            # A new upload is a new id, so a given URL never changes content:
            # cache it for good. Private, because it sits behind a login.
            "Cache-Control": "private, max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )
