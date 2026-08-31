# Frontend

There are **two** frontends in this repo, both talking to the same API. That is
deliberate, not leftover mess.

| | `frontend/` (React + Vite) | `static/` (no build) |
|---|---|---|
| Stack | React 19, TypeScript, Vite 8 | Vanilla ES modules |
| Needs Node | yes | no |
| Served at | `/` once built | `/static/` always |
| Use it when | you want components, types, HMR | Node is unavailable or you want to edit-and-refresh |

The API is unchanged by either. `app/` never knew which UI was talking to it.

## Running it

```powershell
.\dev.ps1
```

That starts FastAPI on **:8000** and Vite on **:5173**, then you open
<http://localhost:5173>. Vite proxies `/api` to FastAPI, so every fetch call
stays relative and there is no CORS configuration anywhere.

Note the URL is `localhost`, not `127.0.0.1` — Vite binds to the IPv6 loopback
by default and `127.0.0.1:5173` will refuse the connection. Use `--host` if you
want it reachable from another machine on the shop network.

## Installing Node

Node 20 or newer. On Windows:

```powershell
winget install OpenJS.NodeJS.LTS
```

That needs administrator rights. **If you cannot elevate** — locked-down lab and
shop machines often cannot — download the official Windows `.zip` from
<https://nodejs.org/en/download>, unpack it somewhere you can write, and add that
folder to your PATH. No installer, no admin, and uninstalling is deleting the
folder.

`dev.ps1` supports exactly that: it looks for an unpacked Node under
`%LOCALAPPDATA%\nodejs\` and puts it on PATH **for that session only**, leaving
your system PATH untouched. The trade-off is that `npm` on its own in a plain
terminal will then say "command not found" — use `dev.ps1`, or add the folder to
your PATH permanently.

If you never intend to touch the React app you do not need Node at all. The
`static/` UI has no build step; see the table above.

## Building for production

```powershell
cd frontend
npm run build
```

Output lands in `frontend/dist/`. FastAPI serves it at `/` automatically the
next time it starts — no config, no separate web server. `npm run build` runs
`tsc -b` first, so a type error fails the build rather than shipping.

Deploying is then exactly what it was before: one process, one port.

## Layout

```
frontend/src/
  api/types.ts       Mirrors app/schemas.py. Update both together.
  api/client.ts      Typed fetch wrapper; throws ApiError with the API's message
  lib/tree.ts        Builds the parent/child indexes from the flat node list
  lib/filter.ts      The filtering algorithm — the interesting file
  lib/format.ts      Status labels/colours, money and byte formatting
  hooks/useToast.ts
  components/
    TopBar.tsx       Project picker, new / clone / export
    FilterBar.tsx    Tag chips, search, isolate vs highlight
    TreeView.tsx     The tree, drag-and-drop, row states
    DetailPanel.tsx  Metadata form, tags, files
    ContextMenu.tsx
  App.tsx            State and data flow
```

## Two kinds of line, two sides of the row

The tree draws **two different relationships at once**, and keeping them
visually separate is the point of the layout.

**Left — hierarchy.** Monospaced guide glyphs (`├──`, `└──`, `│`), exactly like
the DOS `tree` command. Computed in `guidePrefix()` over the *rendered* rows,
not the raw tree: if a filter hides the last three children of a branch, the
last surviving child still has to get the `└──` corner or the lines dangle into
nothing.

**Right — connections.** A gutter of coloured lanes linking every item that
shares a data value, *anywhere in the list*. Two parts both tagged Electrical
are joined even though one lives under Drivetrain and the other under
Ergonomics. That link crosses the hierarchy, so it cannot be shown by
indentation — hence its own column.

Pick the field and the values in the **Breakdown** header: choose `Connect by`
(Tag, Status, Assignee, Material, Vendor, Make/Buy, Type), then search its
values by name. Each value you add becomes one lane: a spine joining its
members, a dot per member, and a faint leader back to each row.

Details that matter if you touch this:

- **Only values on two or more nodes are offered.** A value on a single node
  cannot connect anything, so the search hides it.
- **Tags are the one multi-valued field.** A node with three tags appears on
  three lanes, which is correct — it really does belong to all three.
- **Members hidden in collapsed branches are auto-revealed**, the same way
  filtering reveals its matches. A connection you cannot see is useless.
- **An active filter still wins.** In Isolate mode a connected-but-unmatched
  node stays hidden and the spine simply skips it, rather than drawing a line
  to a row that is not there.
- **The gutter is positioned by row index, not by measuring the DOM.** That is
  why `ROW_H` is exported from `TreeView.tsx` and pushed into CSS as `--row-h`
  from the component — if you set the row height in the stylesheet instead, the
  two silently drift and every dot lands half a row off.

This view exists only in the React app. The no-build `static/` UI still has the
tree and the tag filter, but no guide glyphs and no connection gutter.

## Things worth knowing before you edit

**The whole tree is one fetch.** `GET /api/projects/{id}/tree` returns every
node flat. `buildIndex()` turns it into parent/child maps once, and filtering
runs over that in memory. This is why typing in the search box is instant. Do
not add per-node requests.

**Filter state is derived, never stored.** `computeVisibility()` is a pure
function of `(index, filter)` called inside `useMemo`. Auto-expanding to reveal
matches is also derived (`effectiveExpanded`) rather than written back into
state — writing it back would fight the user every time they collapsed a branch.

**Fields save on blur, not behind a Save button.** In a shop, people edit one
field and walk away. The inputs are uncontrolled (`defaultValue`) and the whole
detail panel is keyed by node id, so switching parts resets the form.

**Money is integer cents everywhere except the one cost input**, which converts
on the way in and out. Don't introduce floats.

**Node names are user input.** React escapes by default — keep it that way, and
do not reach for `dangerouslySetInnerHTML`.
