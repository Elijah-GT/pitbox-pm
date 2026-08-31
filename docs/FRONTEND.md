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

## Pages

The React app is multi-page, routed client-side by react-router in `Root.tsx`:

| Route | Page | Notes |
|---|---|---|
| `/` | `pages/Landing.tsx` | Public page explaining Baja SAE and the tool |
| `/app` | `App.tsx` | The tracker — everything that existed before |
| `/login`, `/signup` | `pages/Login.tsx`, `pages/Signup.tsx` | Forms only; **no auth backend exists yet** |
| `*` | `pages/NotFound.tsx` | |

Two things make this work, and both are easy to break:

**The server must serve `index.html` for unknown paths.** `spa_fallback` in
`app/main.py` does it. Without it `/login` 404s on a hard refresh or a pasted
link — and *dev does not show the bug*, because Vite serves the shell itself.
The fallback deliberately excludes `/api/`, `/assets/`, `/static/` and the docs
paths so an unknown API route still returns a JSON 404 rather than an HTML page
that a `fetch` would happily treat as a 200. `tests/test_api.py` pins that.

**The fixed-viewport sizing belongs to `/app`, not to `body`.** The tracker
never scrolls the page; its panes scroll internally. That used to be
`body { height: 100vh; overflow: hidden }`, which makes an ordinary scrolling
page impossible. It now lives on `.app-shell`, which wraps only the `/app`
route.

## Running it

```powershell
.\dev.ps1      # Windows
./dev.sh       # macOS / Linux
```

That starts FastAPI on **:8000** and Vite on **:5173**, then you open
<http://localhost:5173>. Vite proxies `/api` to FastAPI, so every fetch call
stays relative and there is no CORS configuration anywhere.

Note the URL is `localhost`, not `127.0.0.1` — Vite binds to the IPv6 loopback
by default and `127.0.0.1:5173` will refuse the connection. Use `--host` if you
want it reachable from another machine on the shop network.

## Node is installed portably

The Node MSI requires administrator rights, which weren't available here, so on
Windows Node lives unpacked under:

```
%LOCALAPPDATA%\nodejs\node-v24.19.0-win-x64\
```

`dev.ps1` finds it and puts it on PATH **for that session only** — your system
PATH is untouched. Two consequences:

- Running `npm` in a plain terminal will say "command not found". Either use
  `dev.ps1`, or add that folder to your PATH permanently.
- To remove Node entirely, delete that one folder.

To install it properly system-wide later (from an admin terminal):

```powershell
winget install OpenJS.NodeJS.LTS
```

`dev.sh` looks in three places, in order, and stops at the first hit:

1. `node` already on PATH — a Homebrew or apt install, nothing else needed.
2. **nvm**, sourced from `$NVM_DIR/nvm.sh` (default `~/.nvm`). A script doesn't
   inherit nvm the way an interactive shell does, so it has to load it itself.
3. A portable tarball unpacked under `~/.local/nodejs`, e.g.
   `~/.local/nodejs/node-v24.19.0-darwin-arm64/`. Highest-sorting one wins.
   Override the folder with `NODE_ROOT=/some/path ./dev.sh`.

Same deal as Windows: PATH is changed for that one run only.

## Building for production

```bash
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

**Left — hierarchy.** Drawn SVG edges: a riser per ancestor column, and a
rounded elbow (last child) or a tee (everything else) for the node's own edge.
`TreeEdges` renders one small SVG per row rather than one canvas behind the
list, so the geometry is entirely row-local and expanding a branch cannot knock
the lines out of register.

The shape comes from `TreeRow.ancestorHasNext` / `isLast`, computed over the
*rendered* rows, not the raw tree: if a filter hides the last three children of
a branch, the last surviving child still has to get the elbow or the lines
dangle into nothing.

The one piece of cross-element geometry: a row's edge layer is
`(depth + 1) * INDENT` wide and `.tree-edges` carries `margin-right: -8px` to
cancel the row's flex gap. That makes the layer's right edge meet the twisty
exactly, which is what puts a child's riser directly under its parent's twisty.
Add padding to `.tree-edges` and every riser in the tree shifts off its parent.

The chain from the root to the selected node is stroked in the accent colour, so
a part six levels down can be traced back to its subsystem.

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
- **Each member row draws its own leader to the gutter.** `.row-leader` is a
  flex spacer that fills whatever space is left between the row's content and
  the lanes, and turns into a dashed rule in the lane's colour when the row is
  connected. Rows are full width, so without it a lane dot can sit hundreds of
  pixels from the part it belongs to with nothing joining them. It is also what
  pushes the tag dots right — an unconnected row lays out exactly as before.

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
