# Pit Box

Part tracking and project management for the MESA ARC Racing Baja SAE team.

Break the car down into a tree — **Vehicle → Subsystem → Assembly → Part** — as
deep as you need. Attach datasheets, CAD, PCB files and firmware to the exact part
they belong to. Tag anything, including whole branches. Then filter the tree down
to just what you care about.

## Run it

**React + Vite UI, with hot reload** — starts the API and the frontend together:

```powershell
.\dev.ps1
```

On macOS / Linux use `./dev.sh`.

Then open **http://localhost:5173**. (Use `localhost`, not `127.0.0.1` — Vite
binds to the IPv6 loopback.)

| Page | What it is |
|---|---|
| `/` | Landing page — what Baja SAE is, and what this tool does |
| `/app` | The tracker |
| `/login`, `/signup` | Forms only; there is no auth backend yet |

**Backend only**, serving the no-build UI (or the built React app if you have
run `npm run build`):

```powershell
.\run.ps1
```

...and **http://127.0.0.1:8000**. On macOS / Linux use `./run.sh`.

First run creates a virtual environment and installs dependencies (~30 seconds).
There are two frontends and both work — see [docs/FRONTEND.md](docs/FRONTEND.md)
for why, and for the note about how Node is installed here.

Doing it by hand:
```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt   # .venv/bin/python on mac/linux
.venv/Scripts/python -m uvicorn app.main:app --reload
```

The first launch seeds a demo car (the 2026 season, ~60 nodes) so there is
something to click. Delete `pitbox.db` to start over.

Interactive API docs: **http://127.0.0.1:8000/docs**

## Access

Pit Box does not manage passwords. It runs behind **Cloudflare Access**, which
gates the URL by email domain: anyone with a school address gets in, everyone
else does not. A new member opens the link, Cloudflare emails them a code, and
they appear in the roster automatically — no account to create, nothing to hand
over at the end of the year but the Cloudflare login.

Setup is in **[docs/CLOUDFLARE.md](docs/CLOUDFLARE.md)**.

`PITBOX_AUTH_MODE` picks how this works:

| Mode | Meaning |
|---|---|
| `cloudflare` *(default)* | Cloudflare Access decides. The app must be reachable only through its tunnel. |
| `password` | Built-in login, for running without Cloudflare. See `scripts/create_user.py`. |
| `none` | No auth at all. Local development only — `dev.ps1` sets this. |

The default fails closed: reached directly, the app returns 403 rather than
serving your BOM to whoever found the port.

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

**Export.** `Export CSV` gives you a flat, indented BOM for the cost report.

## Where things are

| Path | What |
|---|---|
| `app/models.py` | The schema. Start here. |
| `app/tree.py` | All hierarchy mechanics — paths, moves, cloning, tag resolution |
| `app/routers/` | The API |
| `app/security.py` | Password hashing, sessions, the guard on every route |
| `frontend/src/lib/filter.ts` | The filtering algorithm (React app) |
| `static/js/filter.js` | The same algorithm, no-build version |
| `docs/SCHEMA.md` | Why the tree is stored the way it is |
| `docs/ARCHITECTURE.md` | Stack rationale and the design decisions behind it |
| `docs/FRONTEND.md` | The two frontends, and how to run the Vite one |
| `docs/CLOUDFLARE.md` | Tunnel + Access setup, and the security model |
| `tests/test_api.py` | 26 tests over the parts that are easy to break |

## Tests

```bash
.venv/Scripts/python -m pip install -r requirements.txt
.venv/Scripts/python -m pytest tests -q
```

## Customizing it for your team

- **Subsystem template** — `BAJA_TEMPLATE` in `app/seed.py`, a plain nested list
- **Default tags** — `DEFAULT_TAGS` in the same file
- **Statuses** — `STATUSES` in `app/models.py` and the matching `Status` literal in
  `app/schemas.py`
- **Extra part fields** — use the `extra` JSON column before adding a real column
- **Colors** — the CSS variables at the top of `static/app.css` and
  `frontend/src/styles.css`

