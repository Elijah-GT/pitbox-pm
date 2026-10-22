"""Delete stored files that no attachment row points at any more.

Deleting a project removes its attachment rows but deliberately leaves the bytes
on disk, because content-addressed blobs are shared: another project (or last
year's car) may still reference the exact same file. This script is the separate,
auditable cleanup pass.

    python scripts/gc_blobs.py            # report only, changes nothing
    python scripts/gc_blobs.py --delete   # actually remove the orphans
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import storage  # noqa: E402
from app.config import settings  # noqa: E402
from app.database import SessionLocal  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--delete", action="store_true", help="actually delete orphans")
    args = parser.parse_args()

    with SessionLocal() as db:
        # Every table that can point at a blob, from the one list the delete
        # path uses too. This script used to keep its own copy of that list,
        # and a copy is exactly what goes stale: it once counted attachments
        # alone, which would have reported every shop drawing as an orphan.
        referenced = storage.referenced_hashes(db)

    blobs_root = settings.storage_dir / "blobs"
    if not blobs_root.exists():
        print(f"No blob store at {blobs_root}. Nothing to do.")
        return 0

    orphans: list[Path] = []
    total = 0
    for path in blobs_root.rglob("*"):
        if not path.is_file() or path.suffix == ".part":
            continue
        total += 1
        if path.name not in referenced:
            orphans.append(path)

    freed = sum(p.stat().st_size for p in orphans)
    print(f"{total} blobs on disk, {len(referenced)} referenced, {len(orphans)} orphaned.")
    print(f"Reclaimable: {freed / 1024 / 1024:.1f} MB")

    if not args.delete:
        for path in orphans[:20]:
            print(f"  would delete {path.name}  ({path.stat().st_size / 1024:.0f} KB)")
        if len(orphans) > 20:
            print(f"  ... and {len(orphans) - 20} more")
        print("\nRe-run with --delete to remove them.")
        return 0

    for path in orphans:
        try:
            path.chmod(0o666)
        except OSError:
            pass
        path.unlink(missing_ok=True)
    print(f"Deleted {len(orphans)} orphaned blobs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
