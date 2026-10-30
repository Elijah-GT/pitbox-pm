"""Content-addressed blob storage.

Files are stored on disk at storage/blobs/<aa>/<bb>/<sha256>, where aa/bb are the
first four hex characters of the hash. Two consequences worth knowing:

  * Deduplication is free. The same 40 MB STEP file attached to six nodes, or
    carried over from last year's car, occupies 40 MB once.
  * Blobs are immutable. "Editing" a file means uploading a new one, which is
    exactly the versioning behaviour you want for CAD and firmware.

Swapping this for S3 / Cloudflare R2 later means reimplementing three functions
(save_stream, open_blob, blob_path) -- nothing above this layer changes.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .config import settings

CHUNK = 1024 * 1024  # 1 MiB


@dataclass(frozen=True)
class StoredBlob:
    sha256: str
    size_bytes: int
    deduplicated: bool


def blob_path(sha256: str) -> Path:
    return settings.storage_dir / "blobs" / sha256[:2] / sha256[2:4] / sha256


_SAFE_NAME = re.compile(r"[^A-Za-z0-9._ -]")


def sanitize_filename(raw: str) -> str:
    """Reduce a browser-supplied filename to something safe to store and echo back.

    Strips any directory component (defeats '../../etc/passwd' and the Windows
    'C:\\evil.txt' variant), removes control and shell-significant characters,
    and refuses names that are all dots.
    """
    name = raw.replace("\\", "/").split("/")[-1]
    name = name.replace("\x00", "").strip()
    name = _SAFE_NAME.sub("_", name)
    name = name.lstrip(".") or "upload"
    if len(name) > 200:
        stem, dot, ext = name.rpartition(".")
        name = (stem[:190] + dot + ext[:9]) if dot else name[:200]
    return name


def extension_of(filename: str) -> str:
    return os.path.splitext(filename)[1].lower()


class UploadTooLarge(Exception):
    pass


class BlockedFileType(Exception):
    pass


def save_stream(fileobj, *, declared_name: str) -> StoredBlob:
    """Stream an upload to disk, hashing as we go.

    We never call .read() on the whole upload -- a 200 MB assembly would sit in
    RAM. We also enforce the size cap while streaming rather than trusting the
    Content-Length header, and only move the file into place once it is complete,
    so a cancelled upload cannot leave a truncated blob behind.
    """
    ext = extension_of(declared_name)
    if ext in settings.blocked_extensions:
        raise BlockedFileType(ext)

    hasher = hashlib.sha256()
    size = 0
    blobs_root = settings.storage_dir / "blobs"
    blobs_root.mkdir(parents=True, exist_ok=True)

    fd, tmp_name = tempfile.mkstemp(dir=blobs_root, suffix=".part")
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as out:
            while True:
                chunk = fileobj.read(CHUNK)
                if not chunk:
                    break
                size += len(chunk)
                if size > settings.max_upload_bytes:
                    raise UploadTooLarge(size)
                hasher.update(chunk)
                out.write(chunk)

        digest = hasher.hexdigest()
        final = blob_path(digest)
        if final.exists():
            tmp.unlink(missing_ok=True)
            return StoredBlob(sha256=digest, size_bytes=size, deduplicated=True)

        final.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(tmp), str(final))
        try:
            final.chmod(0o444)  # blobs are immutable; make that explicit
        except OSError:
            pass  # Windows / odd filesystems: not fatal
        return StoredBlob(sha256=digest, size_bytes=size, deduplicated=False)
    finally:
        tmp.unlink(missing_ok=True)


def blob_reference_columns():
    """Every column that holds the address of a blob. THE list.

    Blobs are content-addressed and shared: the same PDF attached to a node,
    set as a shop drawing and pasted into a Learn page is ONE file on disk. So
    anything that frees bytes has to ask every table that can point at them,
    not only the one it happens to be deleting from.

    This used to be written out twice -- in still_referenced() and again in
    scripts/gc_blobs.py -- and the second copy is where it went wrong: the
    collector only knew about attachments, so it would have reported every
    shop drawing as an orphan. Both now read this, and a test fails if a model
    grows a *sha256 column that is not listed here.
    """
    # Local import: storage must not pull in the ORM at module load, or
    # models -> storage -> models becomes a cycle the day models needs a helper.
    from .models import Attachment, LearnImage, MfgPart, Resource

    return (
        Attachment.sha256,
        MfgPart.drawing_sha256,
        LearnImage.sha256,
        Resource.file_sha256,
    )


def still_referenced(db, sha256: str) -> bool:
    """Whether ANY row, in any table, still points at these bytes."""
    from sqlalchemy import func, select

    for column in blob_reference_columns():
        found = db.scalar(
            select(func.count()).select_from(column.class_).where(column == sha256)
        )
        if found:
            return True
    return False


def referenced_hashes(db) -> set[str]:
    """Every blob address the database still uses -- what the collector keeps."""
    from sqlalchemy import select

    referenced: set[str] = set()
    for column in blob_reference_columns():
        referenced |= {h for h in db.scalars(select(column)) if h}
    return referenced


def delete_blob_if_orphaned(sha256: str, still_referenced: bool) -> bool:
    """Remove a blob only when nothing points at it any more.

    Callers must pass the result of still_referenced() -- deleting one row must
    never delete bytes that another row, in any table, still relies on.
    """
    if still_referenced:
        return False
    path = blob_path(sha256)
    if path.exists():
        try:
            path.chmod(0o666)
        except OSError:
            pass
        path.unlink(missing_ok=True)
        return True
    return False


def guess_kind(filename: str) -> str:
    """Best-effort bucket for the UI's file-type icons. Users can override it."""
    ext = extension_of(filename)
    mapping = {
        ".step": "cad", ".stp": "cad", ".iges": "cad", ".igs": "cad", ".sldprt": "cad",
        ".sldasm": "cad", ".ipt": "cad", ".iam": "cad", ".f3d": "cad", ".catpart": "cad",
        ".x_t": "cad", ".stl": "cad", ".3mf": "cad", ".dxf": "drawing", ".dwg": "drawing",
        ".idw": "drawing", ".slddrw": "drawing",
        ".sch": "pcb", ".brd": "pcb", ".kicad_pcb": "pcb", ".kicad_sch": "pcb",
        ".gbr": "pcb", ".grb": "pcb",
        ".hex": "firmware", ".bin": "firmware", ".uf2": "firmware", ".elf": "firmware",
        ".ino": "firmware", ".c": "firmware", ".h": "firmware", ".cpp": "firmware",
        ".pdf": "datasheet",
        ".png": "photo", ".jpg": "photo", ".jpeg": "photo", ".gif": "photo", ".webp": "photo",
        ".xlsx": "analysis", ".csv": "analysis", ".m": "analysis", ".ipynb": "analysis",
    }
    return mapping.get(ext, "other")
