"""Make someone an admin from the command line.

This exists for exactly two situations, and nothing else:

  * Bootstrapping an instance that already has members but no admin -- the case
    you land in when the admin flag is introduced to a database people are
    already using.
  * Recovery. Someone demoted the wrong person, or the last admin left without
    handing over.

Day-to-day, admins are made in the app: Team > Make admin. That is the whole
point of storing this in the database rather than in an env var -- next year's
lead should never need a terminal, and this script should never be part of a
routine.

    python scripts/grant_admin.py                      # list who is who
    python scripts/grant_admin.py you@school.edu       # promote
    python scripts/grant_admin.py you@school.edu --revoke

On Fly.io, run it inside the machine so it edits the volume's database:

    fly ssh console -C "python scripts/grant_admin.py you@school.edu"

The email must already exist as a member -- it is created on that person's
first sign-in through Cloudflare Access, so have them open the site once first.
Matching is case-insensitive.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import func, select  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.models import Member  # noqa: E402


def show_roster(db) -> None:
    members = list(db.scalars(select(Member).order_by(Member.name)))
    if not members:
        print("No members yet. Have someone sign in first — the account is "
              "created on their first visit.")
        return
    print(f"{'name':<22} {'email':<34} {'admin':<7} active")
    for m in members:
        print(f"{m.name:<22} {(m.email or '-'):<34} "
              f"{'yes' if m.is_admin else 'no':<7} {'yes' if m.is_active else 'no'}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("email", nargs="?", help="who to promote (omit to just list the roster)")
    ap.add_argument("--revoke", action="store_true", help="take admin away instead of granting it")
    args = ap.parse_args()

    with SessionLocal() as db:
        if not args.email:
            show_roster(db)
            return 0

        email = args.email.strip().lower()
        member = db.scalar(select(Member).where(func.lower(Member.email) == email))
        if member is None:
            print(f"No member with email {email!r}.\n")
            show_roster(db)
            return 1

        if args.revoke:
            # Same rule the API enforces: an instance with no admins can only be
            # rescued from a shell, which is the dependency this is meant to end.
            others = db.scalar(
                select(func.count()).select_from(Member).where(
                    Member.is_admin.is_(True),
                    Member.is_active.is_(True),
                    Member.id != member.id,
                )
            ) or 0
            if member.is_admin and others == 0:
                print("Refusing: that is the last admin. Promote someone else first.")
                return 1
            member.is_admin = False
        else:
            member.is_admin = True
            if not member.is_active:
                # A promoted account that cannot sign in helps nobody, and the
                # person running this clearly wants them administering the app.
                member.is_active = True
                print(f"(reactivated {member.email} — a deactivated admin cannot sign in)")

        db.commit()
        verb = "no longer an admin" if args.revoke else "now an admin"
        print(f"{member.name} <{member.email}> is {verb}.")

        total = db.scalar(
            select(func.count()).select_from(Member).where(
                Member.is_admin.is_(True), Member.is_active.is_(True)
            )
        ) or 0
        print(f"{total} active admin(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
