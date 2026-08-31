"""End-to-end tests against a throwaway database.

These cover the parts that are genuinely easy to get wrong: keeping the
materialized path consistent through moves, resolving cascading tags, deep
copying a tree, and file versioning. Run with:  .venv/Scripts/python -m pytest
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

# Point the app at a temp database + storage dir BEFORE importing it, since
# config.Settings is read at import time.
_TMP = Path(tempfile.mkdtemp(prefix="pitbox-test-"))
os.environ["PITBOX_DATABASE_URL"] = f"sqlite:///{(_TMP / 'test.db').as_posix()}"
os.environ["PITBOX_STORAGE_DIR"] = str(_TMP / "storage")
# The bulk of the suite drives the built-in login, so pin that mode. The
# Cloudflare and open modes get their own tests below, which flip it back.
os.environ["PITBOX_AUTH_MODE"] = "password"

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


ADMIN_EMAIL = "test-admin@example.edu"
ADMIN_PASSWORD = "test-password-123"


@pytest.fixture(scope="module")
def client():
    """A signed-in admin. Every route below /api except auth and health now
    requires a session, so the fixture logs in and TestClient keeps the cookie."""
    with TestClient(app) as c:
        from app.database import SessionLocal
        from app.models import Member
        from app.security import hash_password

        with SessionLocal() as db:
            if db.query(Member).filter(Member.email == ADMIN_EMAIL).first() is None:
                db.add(Member(
                    name="Test Admin", email=ADMIN_EMAIL,
                    password_hash=hash_password(ADMIN_PASSWORD), is_admin=True,
                ))
                db.commit()

        r = c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        assert r.status_code == 200, r.text
        yield c


@pytest.fixture()
def anon():
    """A client with no session, for checking that things are actually locked."""
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def project(client):
    r = client.post("/api/projects", json={"name": "Test Car", "season": "2027", "template": "blank"})
    assert r.status_code == 201, r.text
    return r.json()


def _tree(client, project_id):
    r = client.get(f"/api/projects/{project_id}/tree")
    assert r.status_code == 200, r.text
    return r.json()


def _add(client, project_id, parent_id, name, **kw):
    r = client.post(
        "/api/nodes",
        json={"project_id": project_id, "parent_id": parent_id, "name": name, **kw},
    )
    assert r.status_code == 201, r.text
    return r.json()


# --- structure ---------------------------------------------------------------

def test_health(client):
    assert client.get("/api/health").json()["status"] == "ok"


def test_new_project_from_template_is_populated(client):
    r = client.post("/api/projects", json={"name": "Template Car", "template": "baja_standard"})
    assert r.status_code == 201
    data = _tree(client, r.json()["id"])
    names = {n["name"] for n in data["nodes"]}
    assert "Front Suspension" in names
    assert "Wiring Harness" in names
    root = [n for n in data["nodes"] if n["parent_id"] is None][0]
    assert root["path"] == f"/{root['id']}/"
    assert root["depth"] == 0


def test_path_and_depth_are_maintained_on_insert(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    sub = _add(client, project["id"], root["id"], "Drivetrain", node_type="subsystem")
    part = _add(client, project["id"], sub["id"], "Gearbox", node_type="part")

    assert sub["path"] == f"{root['path']}{sub['id']}/"
    assert part["path"] == f"{root['path']}{sub['id']}/{part['id']}/"
    assert part["depth"] == 2
    assert part["ancestor_ids"] == [root["id"], sub["id"]]


def test_move_rewrites_descendant_paths(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    a = _add(client, project["id"], root["id"], "Branch A")
    b = _add(client, project["id"], root["id"], "Branch B")
    child = _add(client, project["id"], a["id"], "Child")
    grandchild = _add(client, project["id"], child["id"], "Grandchild")

    r = client.post(f"/api/nodes/{child['id']}/move", json={"new_parent_id": b["id"]})
    assert r.status_code == 200, r.text

    nodes = {n["id"]: n for n in _tree(client, project["id"])["nodes"]}
    moved, moved_gc = nodes[child["id"]], nodes[grandchild["id"]]

    assert moved["parent_id"] == b["id"]
    assert moved["path"] == f"{b['path']}{child['id']}/"
    assert moved["depth"] == 2
    # The whole subtree must follow, not just the node that was dragged.
    assert moved_gc["path"] == f"{moved['path']}{grandchild['id']}/"
    assert moved_gc["depth"] == 3


def test_cannot_move_node_into_its_own_descendant(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    parent = _add(client, project["id"], root["id"], "Parent")
    child = _add(client, project["id"], parent["id"], "Child")

    r = client.post(f"/api/nodes/{parent['id']}/move", json={"new_parent_id": child["id"]})
    assert r.status_code == 400
    assert "descendant" in r.json()["detail"].lower()

    r = client.post(f"/api/nodes/{parent['id']}/move", json={"new_parent_id": parent["id"]})
    assert r.status_code == 400


def test_subtree_prefix_does_not_match_sibling_with_shared_digits(client, project):
    """'/1/7/%' must not match '/1/70/'. The trailing slash is what saves us."""
    root = _tree(client, project["id"])["nodes"][0]
    nodes = [_add(client, project["id"], root["id"], f"N{i}") for i in range(12)]
    target = nodes[0]
    r = client.get(f"/api/nodes/{target['id']}")
    assert r.json()["descendant_count"] == 0


def test_delete_removes_whole_subtree(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Doomed")
    _add(client, project["id"], branch["id"], "Doomed Child")
    kid2 = _add(client, project["id"], branch["id"], "Doomed Child 2")
    _add(client, project["id"], kid2["id"], "Doomed Grandchild")

    r = client.delete(f"/api/nodes/{branch['id']}")
    assert r.status_code == 200
    assert r.json()["deleted_count"] == 4
    assert client.get(f"/api/nodes/{kid2['id']}").status_code == 404


# --- tags --------------------------------------------------------------------

def test_cascading_tag_applies_to_descendants(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Electrical Branch")
    child = _add(client, project["id"], branch["id"], "Harness")
    grandchild = _add(client, project["id"], child["id"], "Connector")

    tag = client.post("/api/tags", json={"name": "TestElectrical", "color": "#3b82f6"}).json()
    r = client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": True})
    assert r.status_code == 201

    tags_by_node = _tree(client, project["id"])["tags_by_node"]
    gc_tags = tags_by_node[str(grandchild["id"])]
    entry = [t for t in gc_tags if t["tag_id"] == tag["id"]][0]
    assert entry["inherited"] is True
    assert entry["source_node_id"] == branch["id"]

    # The node it was applied to owns it directly, not by inheritance.
    own = [t for t in tags_by_node[str(branch["id"])] if t["tag_id"] == tag["id"]][0]
    assert own["inherited"] is False


def test_node_added_later_inherits_existing_branch_tag(client, project):
    """The reason cascade is resolved at read time instead of copied on write."""
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Late Branch")
    tag = client.post("/api/tags", json={"name": "LateTag"}).json()
    client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": True})

    latecomer = _add(client, project["id"], branch["id"], "Added Afterwards")
    detail = client.get(f"/api/nodes/{latecomer['id']}").json()
    assert any(t["tag_id"] == tag["id"] and t["inherited"] for t in detail["tags"])


def test_non_cascading_tag_stays_put(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Solo Branch")
    child = _add(client, project["id"], branch["id"], "Solo Child")
    tag = client.post("/api/tags", json={"name": "SoloTag"}).json()
    client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": False})

    detail = client.get(f"/api/nodes/{child['id']}").json()
    assert not any(t["tag_id"] == tag["id"] for t in detail["tags"])


def test_removing_inherited_tag_points_at_the_source(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Src Branch")
    child = _add(client, project["id"], branch["id"], "Src Child")
    tag = client.post("/api/tags", json={"name": "SrcTag"}).json()
    client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": True})

    r = client.delete(f"/api/nodes/{child['id']}/tags/{tag['id']}")
    assert r.status_code == 409
    assert str(branch["id"]) in r.json()["detail"]


def test_reassigning_a_tag_toggles_cascade_idempotently(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Toggle Branch")
    child = _add(client, project["id"], branch["id"], "Toggle Child")
    tag = client.post("/api/tags", json={"name": "ToggleTag"}).json()

    client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": False})
    r = client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": True})
    assert r.status_code == 201

    detail = client.get(f"/api/nodes/{child['id']}").json()
    assert any(t["tag_id"] == tag["id"] for t in detail["tags"])


# --- filtering ---------------------------------------------------------------

def test_filter_returns_ancestors_so_the_tree_can_render(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    lvl1 = _add(client, project["id"], root["id"], "Level 1")
    lvl2 = _add(client, project["id"], lvl1["id"], "Level 2")
    target = _add(client, project["id"], lvl2["id"], "Deep Target", status="needs_rework")

    r = client.get(f"/api/projects/{project['id']}/filter", params={"status": ["needs_rework"]})
    assert r.status_code == 200
    data = r.json()

    assert target["id"] in data["matched_ids"]
    # Only the deep node matched, but every ancestor must be visible or the row
    # has nothing to hang off in the UI.
    for ancestor in (root["id"], lvl1["id"], lvl2["id"]):
        assert ancestor in data["visible_ids"]
        assert ancestor not in data["matched_ids"]


def test_filter_tag_mode_all_vs_any(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    both = _add(client, project["id"], root["id"], "Has Both")
    one = _add(client, project["id"], root["id"], "Has One")

    t1 = client.post("/api/tags", json={"name": "FilterA"}).json()
    t2 = client.post("/api/tags", json={"name": "FilterB"}).json()
    client.post(f"/api/nodes/{both['id']}/tags", json={"tag_id": t1["id"]})
    client.post(f"/api/nodes/{both['id']}/tags", json={"tag_id": t2["id"]})
    client.post(f"/api/nodes/{one['id']}/tags", json={"tag_id": t1["id"]})

    params = {"tags": ["filtera", "filterb"]}
    any_ids = client.get(
        f"/api/projects/{project['id']}/filter", params={**params, "tag_mode": "any"}
    ).json()["matched_ids"]
    all_ids = client.get(
        f"/api/projects/{project['id']}/filter", params={**params, "tag_mode": "all"}
    ).json()["matched_ids"]

    assert {both["id"], one["id"]}.issubset(set(any_ids))
    assert both["id"] in all_ids and one["id"] not in all_ids


def test_filter_by_text_searches_part_number(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(client, project["id"], root["id"], "Mystery Bracket", part_number="ZZZ-9910")
    r = client.get(f"/api/projects/{project['id']}/filter", params={"q": "zzz-99"})
    assert node["id"] in r.json()["matched_ids"]


# --- cloning -----------------------------------------------------------------

def test_clone_project_deep_copies_tree_and_tags(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    branch = _add(client, project["id"], root["id"], "Cloneable", status="installed")
    _add(client, project["id"], branch["id"], "Cloneable Child", status="installed")
    tag = client.post("/api/tags", json={"name": "CloneTag"}).json()
    client.post(f"/api/nodes/{branch['id']}/tags", json={"tag_id": tag["id"], "cascade": True})

    r = client.post(
        "/api/projects/clone",
        json={"name": "Next Year Car", "source_project_id": project["id"], "reset_status": "concept"},
    )
    assert r.status_code == 201, r.text
    clone = r.json()

    original = _tree(client, project["id"])
    copied = _tree(client, clone["id"])
    assert len(copied["nodes"]) == len(original["nodes"])
    assert {n["name"] for n in copied["nodes"]} >= {"Cloneable", "Cloneable Child"}

    # Statuses reset, so nothing arrives pre-marked as built.
    assert all(n["status"] == "concept" for n in copied["nodes"])
    # Fresh ids and fresh paths -- no leakage from the source project.
    assert not (
        {n["id"] for n in copied["nodes"]} & {n["id"] for n in original["nodes"]}
    )
    copied_branch = [n for n in copied["nodes"] if n["name"] == "Cloneable"][0]
    child = [n for n in copied["nodes"] if n["name"] == "Cloneable Child"][0]
    assert child["path"].startswith(copied_branch["path"])
    # And the cascading tag came along.
    assert any(
        t["tag_id"] == tag["id"]
        for t in copied["tags_by_node"].get(str(child["id"]), [])
    )


def test_duplicate_node_copies_subtree_in_place(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    corner = _add(client, project["id"], root["id"], "Upright Assembly")
    _add(client, project["id"], corner["id"], "Bearing")
    _add(client, project["id"], corner["id"], "Spacer")

    r = client.post(f"/api/nodes/{corner['id']}/duplicate", json={"name": "Upright Assembly RH"})
    assert r.status_code == 201, r.text
    dupe = r.json()
    assert dupe["name"] == "Upright Assembly RH"
    assert dupe["descendant_count"] == 2
    assert dupe["parent_id"] == root["id"]


# --- files -------------------------------------------------------------------

def test_upload_download_and_versioning(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(client, project["id"], root["id"], "Bracket")

    r = client.post(
        "/api/attachments",
        data={"node_id": node["id"], "notes": "first revision"},
        files={"file": ("bracket.step", b"ISO-10303-21; v1", "application/octet-stream")},
    )
    assert r.status_code == 201, r.text
    v1 = r.json()
    assert v1["version"] == 1 and v1["is_current"] is True
    assert v1["kind"] == "cad"  # inferred from the .step extension

    r = client.post(
        "/api/attachments",
        data={"node_id": node["id"]},
        files={"file": ("bracket.step", b"ISO-10303-21; v2 revised", "application/octet-stream")},
    )
    v2 = r.json()
    assert v2["version"] == 2

    current = client.get("/api/attachments", params={"node_id": node["id"]}).json()
    assert [a["id"] for a in current] == [v2["id"]]  # v1 demoted, not deleted

    all_versions = client.get(
        "/api/attachments", params={"node_id": node["id"], "include_old_versions": True}
    ).json()
    assert len(all_versions) == 2

    dl = client.get(f"/api/attachments/{v1['id']}/download")
    assert dl.status_code == 200
    assert dl.content == b"ISO-10303-21; v1"
    assert "attachment" in dl.headers["content-disposition"]


def test_identical_files_are_stored_once(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    a = _add(client, project["id"], root["id"], "Part A")
    b = _add(client, project["id"], root["id"], "Part B")
    payload = b"same bytes for both parts"

    r1 = client.post(
        "/api/attachments", data={"node_id": a["id"]},
        files={"file": ("shared.pdf", payload, "application/pdf")},
    ).json()
    r2 = client.post(
        "/api/attachments", data={"node_id": b["id"]},
        files={"file": ("shared.pdf", payload, "application/pdf")},
    ).json()

    assert r1["sha256"] == r2["sha256"]
    from app import storage
    assert storage.blob_path(r1["sha256"]).exists()

    # Deleting one must NOT pull the bytes out from under the other.
    assert client.delete(f"/api/attachments/{r1['id']}").status_code == 204
    assert storage.blob_path(r2["sha256"]).exists()
    assert client.get(f"/api/attachments/{r2['id']}/download").content == payload


def test_directory_traversal_filename_is_neutralized(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(client, project["id"], root["id"], "Sketchy")
    r = client.post(
        "/api/attachments", data={"node_id": node["id"]},
        files={"file": ("../../../../etc/passwd", b"nope", "text/plain")},
    )
    assert r.status_code == 201
    assert "/" not in r.json()["filename"] and "\\" not in r.json()["filename"]
    assert not r.json()["filename"].startswith(".")


def test_blocked_extension_is_refused(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(client, project["id"], root["id"], "No Executables")
    r = client.post(
        "/api/attachments", data={"node_id": node["id"]},
        files={"file": ("virus.exe", b"MZ", "application/octet-stream")},
    )
    assert r.status_code == 415


def test_deleting_node_deletes_its_attachment_rows(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(client, project["id"], root["id"], "Ephemeral")
    att = client.post(
        "/api/attachments", data={"node_id": node["id"]},
        files={"file": ("doomed.txt", b"bye", "text/plain")},
    ).json()

    client.delete(f"/api/nodes/{node['id']}")
    assert client.get(f"/api/attachments/{att['id']}/download").status_code == 404


# --- metadata & export -------------------------------------------------------

def test_patch_updates_only_supplied_fields(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    node = _add(
        client, project["id"], root["id"], "Metadata Part",
        part_number="ABC-1", material="6061", vendor="McMaster",
    )
    r = client.patch(f"/api/nodes/{node['id']}", json={"status": "ordered"})
    assert r.status_code == 200
    updated = r.json()
    assert updated["status"] == "ordered"
    assert updated["material"] == "6061"     # untouched
    assert updated["part_number"] == "ABC-1"


def test_invalid_status_is_rejected(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    r = client.post(
        "/api/nodes",
        json={"project_id": project["id"], "parent_id": root["id"], "name": "Bad", "status": "wat"},
    )
    assert r.status_code == 422


def test_rollup_sums_cost_over_subtree(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    asm = _add(client, project["id"], root["id"], "Cost Assembly")
    _add(client, project["id"], asm["id"], "Cheap", cost_cents=100, quantity=2)
    _add(client, project["id"], asm["id"], "Pricey", cost_cents=5000, quantity=1)

    detail = client.get(f"/api/nodes/{asm['id']}").json()
    assert detail["rollup_cost_cents"] == 100 * 2 + 5000


def test_csv_export_has_a_row_per_node(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    _add(client, project["id"], root["id"], "Exported Part", part_number="EXP-1")
    r = client.get(f"/api/projects/{project['id']}/export.csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "EXP-1" in r.text
    body_rows = [ln for ln in r.text.strip().splitlines()[1:] if ln.strip()]
    assert len(body_rows) == len(_tree(client, project["id"])["nodes"])


# --- SPA routing -------------------------------------------------------------
# The catch-all that serves index.html for client-side routes is declared last,
# but a mistake there is silent and nasty: it can swallow the API, turning a
# typo'd fetch into a 200 page instead of a 404. These pin the boundary.


def test_unknown_api_path_is_a_json_404_not_the_html_shell(client):
    r = client.get("/api/definitely-not-a-route")
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_api_routes_still_win_over_the_catch_all(client):
    assert client.get("/api/projects").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_client_side_routes_are_served_by_the_server(client):
    # /login exists only in the React router. A hard refresh has to reach the
    # shell, or every page but / breaks in production.
    for path in ("/", "/app", "/login", "/signup"):
        r = client.get(path)
        assert r.status_code == 200, path
# --- authentication ----------------------------------------------------------

def test_every_api_route_requires_a_session(anon, project):
    """The guard is applied at router include time, so a new endpoint is
    protected by default. This checks the actual surface, not one sample."""
    protected = [
        ("get", "/api/projects"),
        ("get", f"/api/projects/{project['id']}/tree"),
        ("get", f"/api/projects/{project['id']}/export.csv"),
        ("post", "/api/projects"),
        ("post", "/api/projects/clone"),
        ("get", "/api/nodes/1"),
        ("post", "/api/nodes"),
        ("patch", "/api/nodes/1"),
        ("delete", "/api/nodes/1"),
        ("get", "/api/tags"),
        ("post", "/api/tags"),
        ("get", "/api/members"),
        ("post", "/api/members"),
        ("get", "/api/attachments?node_id=1"),
    ]
    for method, url in protected:
        if method in {"post", "patch", "put"}:
            res = getattr(anon, method)(url, json={})
        else:
            res = getattr(anon, method)(url)
        assert res.status_code == 401, f"{method.upper()} {url} returned {res.status_code}, not 401"


def test_health_stays_public(anon):
    # Uptime checks and `fly status` must work without credentials.
    assert anon.get("/api/health").status_code == 200


def test_root_redirects_to_login_when_signed_out(anon):
    res = anon.get("/", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/login"


def test_login_page_renders(anon):
    res = anon.get("/login")
    assert res.status_code == 200
    assert "Sign in" in res.text


def test_login_rejects_wrong_password(anon):
    res = anon.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": "not-it"})
    assert res.status_code == 401
    # Same message whichever half is wrong, so the form cannot enumerate accounts.
    assert res.json()["detail"] == "Wrong email or password."


def test_login_rejects_unknown_email_identically(anon):
    res = anon.post("/api/auth/login", json={"email": "nobody@example.edu", "password": "x"})
    assert res.status_code == 401
    assert res.json()["detail"] == "Wrong email or password."


def test_login_sets_a_httponly_cookie(anon):
    res = anon.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert res.status_code == 200
    cookie = res.headers["set-cookie"].lower()
    assert "pitbox_session=" in cookie
    assert "httponly" in cookie          # XSS cannot read it
    assert "samesite=lax" in cookie      # cross-site writes are blocked
    assert anon.get("/api/auth/me").json()["email"] == ADMIN_EMAIL


def test_me_never_leaks_the_hash(client):
    body = client.get("/api/auth/me").json()
    assert "password_hash" not in body
    assert body["has_password"] is True
    assert body["is_admin"] is True


def test_logout_invalidates_the_session_server_side(anon):
    anon.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    assert anon.get("/api/projects").status_code == 200
    assert anon.post("/api/auth/logout").status_code == 204
    assert anon.get("/api/projects").status_code == 401


def test_stolen_cookie_is_useless_after_logout(anon):
    """Sessions are server-side, so a copied cookie dies with the session
    rather than staying valid until it expires."""
    anon.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
    stolen = anon.cookies["pitbox_session"]
    anon.post("/api/auth/logout")

    with TestClient(app) as thief:
        thief.cookies.set("pitbox_session", stolen)
        assert thief.get("/api/projects").status_code == 401


def test_password_hashing_is_salted_and_verifiable():
    from app.security import hash_password, verify_password
    a, b = hash_password("same-password"), hash_password("same-password")
    assert a != b                       # distinct salts
    assert a.startswith("scrypt$")      # parameters travel with the hash
    assert verify_password("same-password", a)
    assert not verify_password("same-password", b.replace("scrypt", "bogus"))
    assert not verify_password("wrong", a)
    assert not verify_password("anything", None)   # no password set = cannot log in


def test_deactivated_member_loses_access_immediately(client, anon):
    made = client.post("/api/members", json={
        "name": "Temp Member", "email": "temp@example.edu", "is_active": True,
    }).json()
    assert client.put(f"/api/members/{made['id']}/password",
                      json={"password": "temp-password-1"}).status_code == 204

    anon.post("/api/auth/login", json={"email": "temp@example.edu", "password": "temp-password-1"})
    assert anon.get("/api/projects").status_code == 200

    client.delete(f"/api/members/{made['id']}")          # deactivate
    assert anon.get("/api/projects").status_code == 401  # next request, not next login


def test_non_admin_cannot_manage_the_roster(client, anon):
    made = client.post("/api/members", json={
        "name": "Plain Member", "email": "plain@example.edu", "is_active": True,
    }).json()
    client.put(f"/api/members/{made['id']}/password", json={"password": "plain-password-1"})
    anon.post("/api/auth/login", json={"email": "plain@example.edu", "password": "plain-password-1"})

    assert anon.get("/api/members").status_code == 200          # reading is fine
    assert anon.post("/api/members", json={"name": "Sneaky"}).status_code == 403
    assert anon.put(f"/api/members/{made['id']}/password",
                    json={"password": "hijacked-123"}).status_code == 403
    assert anon.delete(f"/api/members/{made['id']}").status_code == 403


def test_changing_password_requires_the_current_one(client):
    res = client.post("/api/auth/password",
                      json={"current_password": "wrong", "new_password": "brand-new-pass"})
    assert res.status_code == 401


def test_cannot_deactivate_the_last_admin(client):
    me = client.get("/api/auth/me").json()
    res = client.delete(f"/api/members/{me['id']}")
    assert res.status_code == 400


# --- auth modes ---------------------------------------------------------------
# The default deployment is Cloudflare Access: no accounts, no passwords, the
# identity arrives in a header that only the tunnel can set.

import contextlib  # noqa: E402

from app.config import settings  # noqa: E402

ACCESS_HEADER = "Cf-Access-Authenticated-User-Email"


@contextlib.contextmanager
def auth_mode(mode: str):
    """Flip the mode for one test. settings is read live, so this is enough."""
    previous = settings.auth_mode
    settings.auth_mode = mode  # type: ignore[assignment]
    try:
        yield
    finally:
        settings.auth_mode = previous  # type: ignore[assignment]


def test_cloudflare_mode_accepts_the_access_header(anon):
    with auth_mode("cloudflare"):
        res = anon.get("/api/auth/me", headers={ACCESS_HEADER: "Newbie@School.EDU"})
        assert res.status_code == 200
        body = res.json()
        # Created on first sight — nobody had to make them an account.
        assert body["email"] == "newbie@school.edu"
        assert body["name"] == "Newbie"
        assert anon.get("/api/projects", headers={ACCESS_HEADER: "newbie@school.edu"}).status_code == 200


def test_cloudflare_mode_reuses_the_same_member_on_return_visits(anon):
    with auth_mode("cloudflare"):
        first = anon.get("/api/auth/me", headers={ACCESS_HEADER: "repeat@school.edu"}).json()
        second = anon.get("/api/auth/me", headers={ACCESS_HEADER: "REPEAT@school.edu"}).json()
        assert first["id"] == second["id"], "email match must be case-insensitive"


def test_cloudflare_mode_links_to_an_existing_roster_member(client, anon):
    """Someone already in the roster as an assignee keeps their record — they
    do not get a duplicate the first time they sign in."""
    existing = client.post("/api/members", json={
        "name": "Already Here", "email": "already@school.edu", "subteam": "Brakes",
    }).json()
    with auth_mode("cloudflare"):
        seen = anon.get("/api/auth/me", headers={ACCESS_HEADER: "already@school.edu"}).json()
    assert seen["id"] == existing["id"]
    assert seen["name"] == "Already Here"     # not overwritten
    assert seen["subteam"] == "Brakes"


def test_cloudflare_mode_refuses_a_request_with_no_access_header(anon):
    """No header means the tunnel was bypassed or no policy is attached.
    Fail closed, and say which."""
    with auth_mode("cloudflare"):
        res = anon.get("/api/projects")
        assert res.status_code == 403
        assert "Cloudflare Access" in res.json()["detail"]


def test_built_in_login_is_disabled_outside_password_mode(anon):
    with auth_mode("cloudflare"):
        assert anon.get("/login").status_code == 404
        assert anon.post("/api/auth/login",
                         json={"email": "a@b.c", "password": "x"}).status_code == 404


def test_health_reports_the_mode(anon):
    with auth_mode("cloudflare"):
        assert anon.get("/api/health").json()["auth_mode"] == "cloudflare"


def test_none_mode_is_open_and_needs_no_header(anon):
    with auth_mode("none"):
        assert anon.get("/api/projects").status_code == 200
        assert anon.get("/api/auth/me").json()["email"] == "local@localhost"


def test_password_mode_ignores_the_access_header(anon):
    """A forged header must not grant anything when the app is not behind
    Cloudflare — otherwise switching modes would open a hole."""
    res = anon.get("/api/projects", headers={ACCESS_HEADER: "attacker@evil.com"})
    assert res.status_code == 401
