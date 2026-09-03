# Pit Box

Part tracking and project management for a Baja SAE team.

Break the car down into a tree — **Vehicle → Subsystem → Assembly → Part** — as
deep as you need. Attach datasheets, CAD, PCB files and firmware to the exact part
they belong to. Tag anything, including whole branches. Then filter the tree down
to just what you care about.

Built for the way a student team actually works: a third of the roster leaves
every year, nobody inherits a handover document, and whoever picks it up next
should not have to maintain accounts or run scripts to keep it alive.

---

## Try it in two minutes

You need **Python 3.11+**. Node is optional — see [Frontends](#frontends).

```bash
git clone https://github.com/Elijah-GT/pitbox-pm.git
```

```bash
cd pitbox-pm
```

Windows:

```powershell
.\run.ps1
```

macOS / Linux:

```bash
./run.sh
```

Then open **http://127.0.0.1:8000**.

The first run creates a virtual environment and installs dependencies (~30
seconds), then seeds a demo car with about 60 nodes so there is something to
click. Delete `pitbox.db` to start over with an empty tree.

The interactive Swagger docs are switched off — see `docs_url` in
`app/main.py` if you want them while developing. They are off because
FastAPI mounts them on the app rather than a router, so the auth guard did
not cover them.

Both run scripts set `PITBOX_AUTH_MODE=none`, because there is no point putting a
login in front of a laptop. Deployments leave it unset and get the secure
default — see [Access](#access).

<details>
<summary>Doing it by hand instead</summary>

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # .venv/bin/python on mac/linux
.venv/Scripts/python -m uvicorn app.main:app --reload
```

Set `PITBOX_AUTH_MODE=none` in the environment first (`$env:PITBOX_AUTH_MODE="none"`
in PowerShell, `export PITBOX_AUTH_MODE=none` in bash), or the app will refuse to
start without Cloudflare Access configured. The run scripts do this for you.
</details>

---

## What it does

**Trees.** Create a tree from scratch, from the standard Baja subsystem template,
or by cloning a previous year's car — statuses reset, structure and tags intact.
Add a child anywhere with `+`. Drag rows to re-parent. Right-click to duplicate a
whole assembly (build one upright properly, then duplicate it for the other three
corners).

**Files.** Drag them onto a part. Uploading the same filename twice makes v2 and
keeps v1. Identical files are stored once no matter how many parts reference them.

**Tags.** Apply to one part, or tick **"apply to whole branch"** to tag a subsystem
and everything under it — including parts added next month. Inherited tags show as
dashed pills with a jump-to-source button.

**Filters.** Click tag chips, search text, filter by status or assignee. Two views:
- **Isolate** — prune the tree to matches plus the ancestors needed to reach them
- **Highlight** — keep the whole tree, dim everything that does not match

**Connections.** A gutter down the right-hand side links every part sharing a
value you pick — tag, vendor, material, assignee — even across different
subsystems. Relationships that indentation cannot show.

**Export.** `Export CSV` gives you a flat, indented BOM for the cost report.

---

## Deploying it for your team

Two supported routes. Both put **Cloudflare Access** in front, so there are no
passwords to manage and no accounts to create — a new member with a school email
signs in and appears in the roster automatically.

| | Guide | Needs |
|---|---|---|
| A machine you can leave on | [docs/CLOUDFLARE.md](docs/CLOUDFLARE.md) | a PC that stays powered, a domain |
| No machine to leave on | [docs/FLY.md](docs/FLY.md) | a Fly.io account, a domain |

Both need a domain on Cloudflare (~$10/yr at cost from Cloudflare Registrar) and
a free Cloudflare Zero Trust plan, which covers 50 users. Budget about an hour,
most of it clicking in a dashboard.

### Access

Identity is proved by **verifying the JWT Cloudflare signs**, not by trusting the
`Cf-Access-Authenticated-User-Email` header. A forged header gets a 403 no matter
where the request came from — which is what makes it safe to run somewhere with a
public URL rather than only behind a tunnel.

`PITBOX_AUTH_MODE` picks how this works:

| Mode | Meaning |
|---|---|
| `cloudflare` *(default)* | Cloudflare Access decides. Needs `PITBOX_ACCESS_TEAM_DOMAIN` and `PITBOX_ACCESS_AUD`; refuses to start without them. |
| `password` | Built-in login (scrypt + revocable sessions), for running without Cloudflare. See `scripts/create_user.py`. |
| `none` | No auth at all. Local development only — the run scripts set this. |

The default fails closed twice over: it will not start without the means to
verify a signature, and once running it returns 403 to anything not carrying one.

### Who can change things

Signing in and being allowed to change things are two different questions,
because the Access policy that suits a team is usually "anyone with a school
email address". That is the right rule for reading and a bad one for deleting —
it would let any student at the university wipe a subsystem.

There are three tiers:

| | Who | What |
|---|---|---|
| **Read** | anyone signed in | see every tree, every part, every file |
| **Edit** | any member | change a part that exists: status, assignee, cost, vendor, material, description; apply and remove tags; re-parent and reorder; upload files |
| **Add / delete** | admins only | create and delete nodes, duplicate branches, delete files, everything project-wide (new tree, clone, rename, delete), the shared tag vocabulary, and the roster |

The line is **edit versus add/delete**. Someone working on their own subsystem
has to be able to mark a part ordered and set its cost without waiting on a
lead — that is the daily job. What they cannot do is change the shape of the
tree, because those are the actions that lose work.

Enforcement is one dependency on the router (`app/main.py`), not a check per
endpoint, so a route added later is admin-only from the moment it exists. The
member-writable routes are an explicit allowlist in `security.MEMBER_WRITABLE`;
anything absent from it needs an admin. `validate_member_writable()` runs at
import and refuses to start the app if an entry there stops matching a real
route, so renaming an endpoint fails loudly instead of quietly promoting an
everyday action to admin-only.

Two more things anyone may do, both about their own account rather than the
team's data: `PATCH /api/auth/me` (set your own display name) and
`POST /api/auth/password`.

Admins are stored in the database and managed **in the app** — the **Team**
button in the top bar, visible to admins only. Nobody needs a terminal, a
hosting login, or a redeploy to hand over to next year's leads. The API refuses
to demote or deactivate the last remaining admin, so there is no way to lock
everyone out by accident.

The first person to sign in on an empty database becomes the admin. That is the
only automatic promotion; on a database that already has members, nobody is
promoted by signing in. If you end up with a database that has members but no
admin — which is what happens when you add this to an instance people are
already using — fix it once from a shell:

```bash
python scripts/grant_admin.py you@school.edu
```

On Fly.io: `fly ssh console -C "python scripts/grant_admin.py you@school.edu"`.
Run it with no email to list who is currently who.

### Backups

`pitbox.db` runs in WAL mode, so **copying that file alone can silently lose most
of your data** — recent writes live in `pitbox.db-wal` until SQLite checkpoints.
Use the script, which uses SQLite's online backup API and prints row counts:

```bash
python scripts/backup.py --keep 20
```

---

## Frontends

There are two, both talking to the same API, and both work:

| | `frontend/` (React 19 + TS + Vite) | `static/` (no build) |
|---|---|---|
| Served at | `/` once built | `/static/` always |
| Needs Node | yes | no |
| Guide lines + connection gutter | yes | no |

`static/` exists so the app still runs on a machine with Python and nothing else.
For hot reload while developing the React app:

```powershell
.\dev.ps1
```

That starts the API on **:8000** and Vite on **:5173** — open
**http://localhost:5173** (`localhost`, not `127.0.0.1`; Vite binds the IPv6
loopback). Details in [docs/FRONTEND.md](docs/FRONTEND.md).

---

## Where things are

| Path | What |
|---|---|
| `app/models.py` | The schema. Start here. |
| `app/tree.py` | All hierarchy mechanics — paths, moves, cloning, tag resolution |
| `app/routers/` | The API |
| `app/security.py` | Password hashing, sessions, the guard on every route |
| `app/access_jwt.py` | Verifies Cloudflare Access tokens — signature, audience, issuer |
| `frontend/src/lib/filter.ts` | The filtering algorithm (React app) |
| `static/js/filter.js` | The same algorithm, no-build version |
| `docs/SCHEMA.md` | Why the tree is stored the way it is |
| `docs/ARCHITECTURE.md` | Stack rationale and the design decisions behind it |
| `docs/FRONTEND.md` | The two frontends, and how to run the Vite one |
| `docs/CLOUDFLARE.md` | Tunnel + Access setup, and the security model |
| `docs/FLY.md` | Deploying to Fly.io: Dockerfile, volume, no public port |
| `tests/test_api.py` | 67 tests over the parts that are easy to break |

**The one rule:** nothing outside `app/tree.py` may write `Node.path`,
`Node.depth` or `Node.position`. Route every structural change through those
functions and the denormalized path cache stays consistent.

## Tests

```bash
.venv/Scripts/python -m pip install -r requirements-dev.txt
```

```bash
.venv/Scripts/python -m pytest tests -q
```

---

## Making it yours

- **Team name** — `PITBOX_TEAM_NAME`, in `.env` or your host's environment
- **Subsystem template** — `BAJA_TEMPLATE` in `app/seed.py`, a plain nested list
- **Default tags** — `DEFAULT_TAGS` in the same file
- **Statuses** — `STATUSES` in `app/models.py` and the matching `Status` literal in
  `app/schemas.py`
- **Extra part fields** — use the `extra` JSON column before adding a real column
- **Colors** — the CSS variables at the top of `static/app.css` and
  `frontend/src/styles.css`

Copy `.env.example` to `.env` to change any setting; every one has a working
default, and the app runs with no `.env` at all.

Nothing in the schema is Baja-specific beyond the seed template — it is a tree of
parts with tags, files and statuses, so it adapts to Formula SAE, a rocketry
team, or any other project that decomposes into assemblies.
