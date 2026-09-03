# Database Schema

## Storing the hierarchy

This is the decision the whole system turns on, so here is the reasoning rather
than just the answer.

### The four options

| Approach | Read a subtree | Insert a child | Move a branch | Ancestors | Verdict |
|---|---|---|---|---|---|
| **Adjacency list** (`parent_id`) | recursive CTE | 1 INSERT | 1 UPDATE | recursive CTE | Simple, but every read walks |
| **Materialized path** (`/1/7/23/`) | 1 indexed `LIKE` | 1 INSERT + path | rewrite subtree paths | free — parse the string | Fast reads, cheap writes |
| **Nested sets** (`lft`/`rgt`) | 1 range scan | **renumbers half the table** | brutal | range query | Wrong for a BOM |
| **Closure table** | 1 join | depth+1 INSERTs | delete+reinsert pairs | 1 join | Correct, but 3–4× the rows |

### What we chose: adjacency list **+** materialized path

Both, together. They are not competing — one is truth, the other is an index.

```python
class Node:
    parent_id: int | None   # SOURCE OF TRUTH. Real FK, ON DELETE CASCADE.
    path:      str          # DERIVED CACHE. '/1/7/23/' — always ends in own id.
    depth:     int          # DERIVED CACHE. Saves counting slashes.
    position:  int          # sibling order, for drag-and-drop
```

**`parent_id` is the truth.** It is a real foreign key, so the database itself
refuses to orphan a part, and `ON DELETE CASCADE` means deleting a subsystem
reliably takes its subtree with it. Adding a child — requirement #2, the thing
this app does most — is one INSERT.

**`path` is a cache** that buys three things adjacency-list-alone makes painful:

```sql
-- Everything under node 7, one indexed prefix scan, no recursion:
SELECT * FROM nodes WHERE project_id = 1 AND path LIKE '/1/7/%';
```
```python
# Ancestors with no query at all — they are already in the string:
node.path            # '/1/7/23/'
node.ancestor_ids    # [1, 7]
```
```python
# And cascading tags resolve by prefix match instead of by walking:
descendant.path.startswith(tagged_branch.path)
```

**The trailing slash is load-bearing.** Paths are stored `/1/7/23/`, with slashes
on both ends. Without the trailing one, `LIKE '/1/7%'` would happily match
`/1/70/`, silently pulling a stranger's subtree into your filter. With it,
`'/1/70/'` fails the pattern `'/1/7/%'` at the `0`. There is a test for exactly
this (`test_subtree_prefix_does_not_match_sibling_with_shared_digits`).

**Why not nested sets:** inserting one node renumbers roughly half the table. A
BOM changes many times a day during build season. Nested sets optimize for a
read-heavy, write-never tree; this is the opposite.

**Why not a closure table:** it is genuinely correct and would work. It costs one
row per ancestor-descendant pair (a 2,000-node, 6-deep tree becomes ~10,000 rows),
plus a second table to keep in sync. For a system a student inherits with no
handover, the string you can read in a database browser wins.

**The cost we accepted:** the cache can drift if someone writes `path` by hand.
Mitigations: every structural change goes through `app/tree.py`, moves are tested,
and `get_project_nodes()` falls back to returning an orphaned row rather than
silently hiding a part.

## Tables

```
projects ──< nodes >── members
                │
                ├──< node_tags >── tags
                └──< attachments
```

### `projects` — one tree
`id, name, slug, season, description, is_archived, created_at, updated_at`

One row per tree: "Baja 2026 Car", "Baja 2027 Car", a test rig, the trailer.

### `nodes` — the tree itself

| Column | Notes |
|---|---|
| `project_id` | FK, CASCADE |
| `parent_id` | FK to `nodes.id`, CASCADE. NULL = root |
| `path`, `depth`, `position` | derived cache, see above |
| `name`, `node_type` | `vehicle` / `subsystem` / `assembly` / `part` |
| `part_number`, `status`, `assignee_id`, `description` | requirement #5 |
| `quantity`, `sourcing`, `material`, `mass_g`, `cost_cents`, `vendor`, `lead_time_days` | BOM fields |
| `extra` | JSON escape hatch — torque spec, heat treat, inspection date, whatever this year's team needs without a migration |

Indexes: `(project_id, path)` is the workhorse — every subtree query is a prefix
scan on it. Plus `parent_id`, `(project_id, status)`, `part_number`.

`cost_cents` is an integer. Never store money in a float.

### `tags` + `node_tags` — the many-to-many, with a twist

```python
class NodeTag:
    node_id: int
    tag_id:  int
    cascade: bool   # <-- the whole design is in this one column
    UniqueConstraint(node_id, tag_id)
```

Tagging one part is the obvious case. **Tagging a whole branch** — requirement #4
— is where the design choice lives.

The naive approach is to copy the tag onto every descendant. That breaks
immediately: add a part to the branch next week and it silently misses the tag,
and un-tagging becomes a subtree-wide DELETE.

Instead, `cascade=True` stores **one row** on the branch root, meaning "this tag
applies here and to everything beneath." A node's *effective* tags are then:

> its own tags ∪ every `cascade=True` tag on any of its ancestors

which is cheap, because each node's ancestors are already sitting in its `path`.
`tree.effective_tags()` resolves an entire project in two queries.

What this gives you:
- Tag "Electrical & Data" once → every connector under it is Electrical.
- A part added tomorrow inherits it automatically.
- Un-tagging the branch is one DELETE.
- Filtering for `electrical` finds all of them, without anyone tagging by hand.

In the UI, inherited tags render as dashed pills (and square dots in the tree) with
a jump-to-source button, because the fix for a wrong inherited tag is at the
ancestor, not here. The API returns 409 with the source node id if you try to
remove an inherited tag directly.

Tags are **global, not per-project**, so "Pending Machining" means the same thing
on the 2027 car as it did on the 2026 one, and tag filters survive a clone.

### `attachments` — files on nodes

| Column | Notes |
|---|---|
| `node_id` | FK, CASCADE |
| `filename` | **sanitized** — directory components stripped |
| `sha256` | content address; the bytes live at `storage/blobs/<aa>/<bb>/<sha256>` |
| `size_bytes`, `content_type` | type is re-derived from the name, never trusted from the browser |
| `kind` | `datasheet` / `cad` / `drawing` / `pcb` / `firmware` / `analysis` / `photo` / `other`, guessed from extension |
| `version`, `is_current` | re-uploading the same filename to the same node makes v2 and demotes v1 |
| `uploaded_by_id`, `uploaded_at`, `notes` | provenance |

**Content addressing** means the same 40 MB STEP file attached to six corners —
or carried over from last year's car by a project clone — occupies 40 MB once.
It also makes blobs immutable, which is exactly the versioning behavior you want
for CAD and firmware.

Because blobs are shared, deleting an attachment only unlinks the bytes when the
last reference to that hash is gone. Deleting a whole project leaves the blobs;
`scripts/gc_blobs.py` reclaims them as a separate, auditable pass.

Upload safety, in `app/storage.py`:
- streamed in 1 MiB chunks — a 200 MB assembly never sits in RAM
- size cap enforced **while streaming**, not from the `Content-Length` header
- written to a temp file and moved into place only when complete, so a cancelled
  upload cannot leave a truncated blob
- filenames stripped of directory components (`../../etc/passwd` → `etc_passwd`)
- executable extensions rejected
- downloads always `Content-Disposition: attachment` + `nosniff`, except a small
  image allowlist — so a helpfully-uploaded `.html` or `.svg` cannot run script
  on this origin

### `members` — the roster
`id, name, email, subteam, role, is_active`

Deliberately not an auth system; it is the list you pick an assignee from.
Graduating seniors get deactivated, not deleted, so their name stays on the parts
they designed.

## Query cookbook

```sql
-- Whole subtree of node 7 (project 1)
SELECT * FROM nodes WHERE project_id=1 AND path LIKE '/1/7/%' ORDER BY depth, position;

-- Direct children only
SELECT * FROM nodes WHERE parent_id=7 ORDER BY position;

-- Everything still on the drawing board, deepest first
SELECT * FROM nodes WHERE project_id=1 AND status IN ('concept','design') ORDER BY depth DESC;

-- Directly tagged (inherited tags are resolved in app code, see tree.effective_tags)
SELECT n.* FROM nodes n
  JOIN node_tags nt ON nt.node_id = n.id
  JOIN tags t       ON t.id = nt.tag_id
 WHERE n.project_id = 1 AND t.slug = 'pending-machining';

-- Which branches broadcast a tag to their whole subtree
SELECT n.name, t.name FROM node_tags nt
  JOIN nodes n ON n.id = nt.node_id
  JOIN tags  t ON t.id = nt.tag_id
 WHERE nt.cascade = 1;

-- Subtree cost roll-up
SELECT SUM(cost_cents * quantity) FROM nodes
 WHERE project_id=1 AND path LIKE '/1/7/%';
```

## Porting to Postgres

Everything above is standard SQL and works unchanged. Two optional upgrades:

- Swap `path VARCHAR` for the **`ltree`** extension to get `@>` ancestor operators
  and GiST indexing. Worth it above ~100k nodes; unnecessary below that.
- Add a `GIN` index on `extra` if you start querying inside that JSON.
