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


def still_referenced(db, sha256: str) -> bool:
    """Whether ANY row still points at these bytes.

    Blobs are content-addressed, so the same drawing uploaded as a node
    attachment and set as a manufacturing part's drawing is ONE file on disk.
    Counting only the table you happen to be deleting from would unlink bytes
    the other one still needs. Both delete paths go through here so the two
    cannot drift apart.
    """
    # Local import: storage must not pull in the ORM at module load, or
    # models -> storage -> models becomes a cycle the day models needs a helper.
    from sqlalchemy import func, select

    from .models import Attachment, MfgPart

    attached = db.scalar(
        select(func.count()).select_from(Attachment).where(Attachment.sha256 == sha256)
    ) or 0
    if attached:
        return True
    drawn = db.scalar(
        select(func.count()).select_from(MfgPart).where(MfgPart.drawing_sha256 == sha256)
    ) or 0
    return drawn > 0


def delete_blob_if_orphaned(sha256: str, still_referenced: bool) -> bool:
    """Remove a blob only when no attachment row points at it any more.

    Callers must pass the result of a COUNT over attachments -- deleting one
    attachment must never delete bytes another node still relies on.
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
