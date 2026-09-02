"""Remove the seeded demo roster (Alex Rivera, Priya Nair, ...) from a database.

The demo members exist so a fresh clone has a populated assignee dropdown and
something to look at. Once a real team is using the app they are just five fake
people cluttering every tree, and there is no roster screen to remove them from.

    python scripts/remove_demo_members.py            # show what would go
    python scripts/remove_demo_members.py --apply    # actually delete

Only deletes a member when the name matches the seed roster AND the record has
no email address, because a real member always arrives from Cloudflare Access
with one. A real teammate who happens to be called Alex Rivera is never touched.

Nodes assigned to a deleted member become unassigned -- assignee_id is
ON DELETE SET NULL, so nothing else is disturbed. Stop the app first: SQLite
allows one writer, and you do not want a half-applied change.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Member, Node  # noqa: E402
from app.seed import DEMO_MEMBER_NAMES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true",
                    help="perform the deletion (without this it is a dry run)")
    args = ap.parse_args()

    with SessionLocal() as db:
        doomed = list(db.scalars(
            select(Member).where(
                Member.name.in_(DEMO_MEMBER_NAMES),
                Member.email.is_(None),
            )
        ))

        if not doomed:
            print("No seeded demo members found. Nothing to do.")
            return 0

        print(f"{'name':<20} {'subteam':<14} assigned nodes")
        total_assignments = 0
        for m in doomed:
            n = db.scalar(
                select(func.count()).select_from(Node).where(Node.assignee_id == m.id)
            ) or 0
            total_assignments += n
            print(f"{m.name:<20} {(m.subteam or '-'):<14} {n}")

        if not args.apply:
            print(f"\nDry run. {len(doomed)} member(s) would be deleted and "
                  f"{total_assignments} node assignment(s) cleared.")
            print("Re-run with --apply to do it.")
            return 0

        for m in doomed:
            db.delete(m)
        db.commit()

        remaining = db.scalar(select(func.count()).select_from(Member)) or 0
        print(f"\nDeleted {len(doomed)} demo member(s). "
              f"{total_assignments} node(s) are now unassigned. "
              f"{remaining} member(s) remain.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
