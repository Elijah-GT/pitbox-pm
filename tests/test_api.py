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


def test_deleting_a_project_removes_it_and_its_nodes_only(client):
    """Deleting a tree takes its whole subtree with it and leaves other trees
    alone. Reachable from the UI now, and there is no undo, so it is worth a
    test that the blast radius is exactly one project."""
    keep = client.post("/api/projects", json={
        "name": "Keep Me", "season": "2030", "template": "blank"}).json()
    doomed = client.post("/api/projects", json={
        "name": "Doomed", "season": "2031", "template": "baja_standard"}).json()

    doomed_nodes = _tree(client, doomed["id"])["nodes"]
    assert len(doomed_nodes) > 1, "template should have produced a real tree"
    keep_before = len(_tree(client, keep["id"])["nodes"])

    assert client.delete(f"/api/projects/{doomed['id']}").status_code == 204

    # Gone from the list, and gone from the database.
    ids = [p["id"] for p in client.get("/api/projects").json()]
    assert doomed["id"] not in ids
    assert keep["id"] in ids
    assert client.get(f"/api/projects/{doomed['id']}/tree").status_code == 404

    # Its nodes went with it; the other project is untouched.
    for node in doomed_nodes:
        assert client.get(f"/api/nodes/{node['id']}").status_code == 404
    assert len(_tree(client, keep["id"])["nodes"]) == keep_before


def test_deleting_a_missing_project_is_404_not_a_crash(client):
    assert client.delete("/api/projects/999999").status_code == 404


# --- auth modes ---------------------------------------------------------------
# The default deployment is Cloudflare Access: no accounts, no passwords, and
# an identity proved by a signature rather than asserted by a header. These
# tests mint their own tokens with a throwaway RSA key and hand the verifier
# the matching public key, so nothing here touches the network.
import contextlib  # noqa: E402
import time  # noqa: E402

import jwt as pyjwt  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from app import access_jwt  # noqa: E402
from app.config import settings  # noqa: E402

EMAIL_HEADER = "Cf-Access-Authenticated-User-Email"
JWT_HEADER = "Cf-Access-Jwt-Assertion"

TEAM_DOMAIN = "testteam.cloudflareaccess.com"
ISSUER = f"https://{TEAM_DOMAIN}"
AUD = "a" * 64          # Access AUD tags are 64 hex characters
KID = "test-key-1"

_PRIVATE_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_WRONG_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def make_token(email="member@school.edu", *, key=None, aud=AUD, issuer=ISSUER,
               expires_in=3600, kid=KID, **extra):
    """A token shaped exactly like the ones Cloudflare Access issues."""
    now = int(time.time())
    claims = {"aud": [aud], "iss": issuer, "iat": now, "exp": now + expires_in,
              "sub": "test-subject", "type": "app"}
    if email is not None:
        claims["email"] = email
    claims.update(extra)
    return pyjwt.encode(claims, key or _PRIVATE_KEY, algorithm="RS256",
                        headers={"kid": kid})


@contextlib.contextmanager
def cloudflare_mode():
    """Switch to cloudflare mode with a verifier that trusts our test key.

    _fetched_at and _last_attempt are pinned to now so the verifier considers
    its key set fresh and never tries to reach Cloudflare.
    """
    previous = (settings.auth_mode, settings.access_team_domain, settings.access_aud)
    settings.auth_mode = "cloudflare"  # type: ignore[assignment]
    settings.access_team_domain = TEAM_DOMAIN
    settings.access_aud = AUD
    access_jwt.reset_verifier()

    verifier = access_jwt.get_verifier()
    jwk_dict = pyjwt.algorithms.RSAAlgorithm.to_jwk(_PRIVATE_KEY.public_key(), as_dict=True)
    jwk_dict.update({"kid": KID, "alg": "RS256", "use": "sig"})
    verifier._keys = {KID: pyjwt.PyJWK.from_dict(jwk_dict)}
    verifier._fetched_at = time.monotonic()
    verifier._last_attempt = time.monotonic()
    try:
        yield verifier
    finally:
        (settings.auth_mode, settings.access_team_domain,
         settings.access_aud) = previous  # type: ignore[assignment]
        access_jwt.reset_verifier()


@contextlib.contextmanager
def auth_mode(mode: str):
    previous = settings.auth_mode
    settings.auth_mode = mode  # type: ignore[assignment]
    try:
        yield
    finally:
        settings.auth_mode = previous  # type: ignore[assignment]


# --- the happy path -----------------------------------------------------------

def test_cloudflare_mode_accepts_a_validly_signed_token(anon):
    with cloudflare_mode():
        res = anon.get("/api/auth/me",
                       headers={JWT_HEADER: make_token("Newbie@School.EDU")})
        assert res.status_code == 200, res.text
        body = res.json()
        # Created on first sight — nobody had to make them an account.
        assert body["email"] == "newbie@school.edu"
        assert body["name"] == "Newbie"
        assert anon.get("/api/projects",
                        headers={JWT_HEADER: make_token("newbie@school.edu")}
                        ).status_code == 200


def test_cloudflare_mode_reads_the_token_from_the_cookie_too(anon):
    """A browser navigating to the app carries CF_Authorization, not the header."""
    with cloudflare_mode():
        anon.cookies.set("CF_Authorization", make_token("cookie-user@school.edu"))
        try:
            res = anon.get("/api/auth/me")
            assert res.status_code == 200, res.text
            assert res.json()["email"] == "cookie-user@school.edu"
        finally:
            anon.cookies.delete("CF_Authorization")


def test_cloudflare_mode_reuses_the_same_member_on_return_visits(anon):
    with cloudflare_mode():
        first = anon.get("/api/auth/me",
                         headers={JWT_HEADER: make_token("repeat@school.edu")}).json()
        second = anon.get("/api/auth/me",
                          headers={JWT_HEADER: make_token("REPEAT@school.edu")}).json()
        assert first["id"] == second["id"], "email match must be case-insensitive"


def test_cloudflare_mode_links_to_an_existing_roster_member(client, anon):
    """Someone already in the roster as an assignee keeps their record — they
    do not get a duplicate the first time they sign in."""
    existing = client.post("/api/members", json={
        "name": "Already Here", "email": "already@school.edu", "subteam": "Brakes",
    }).json()
    with cloudflare_mode():
        seen = anon.get("/api/auth/me",
                        headers={JWT_HEADER: make_token("already@school.edu")}).json()
    assert seen["id"] == existing["id"]
    assert seen["name"] == "Already Here"     # not overwritten
    assert seen["subteam"] == "Brakes"


# --- the forgeries this whole module exists to stop ---------------------------

def test_a_forged_email_header_alone_gets_nothing(anon):
    """THE test. On Fly.io the app has a public *.fly.dev URL, so anyone can
    send whatever headers they like. Without a signature it must be worthless."""
    with cloudflare_mode():
        res = anon.get("/api/projects", headers={EMAIL_HEADER: "attacker@evil.com"})
        assert res.status_code == 403
        assert "verified" in res.json()["detail"].lower()


def test_the_email_header_cannot_override_the_signed_token(anon):
    """Send a real token for one person and a header naming another. The
    signature wins; the header is not consulted at all."""
    with cloudflare_mode():
        res = anon.get("/api/auth/me", headers={
            JWT_HEADER: make_token("real@school.edu"),
            EMAIL_HEADER: "attacker@evil.com",
        })
        assert res.status_code == 200
        assert res.json()["email"] == "real@school.edu"


def test_a_token_signed_by_the_wrong_key_is_refused(anon):
    """Same key id, different private key: the shape is right, the maths is not."""
    with cloudflare_mode():
        res = anon.get("/api/projects",
                       headers={JWT_HEADER: make_token(key=_WRONG_KEY)})
        assert res.status_code == 403
        assert "rejected" in res.json()["detail"]


def test_a_token_for_another_access_application_is_refused(anon):
    """A valid Cloudflare token minted for a different app on the same team.
    Without the aud check this would sail through."""
    with cloudflare_mode():
        res = anon.get("/api/projects", headers={JWT_HEADER: make_token(aud="b" * 64)})
        assert res.status_code == 403
        assert "different Access application" in res.json()["detail"]


def test_a_token_from_another_cloudflare_team_is_refused(anon):
    with cloudflare_mode():
        res = anon.get("/api/projects", headers={
            JWT_HEADER: make_token(issuer="https://evil.cloudflareaccess.com")})
        assert res.status_code == 403
        assert "different Cloudflare team" in res.json()["detail"]


def test_an_expired_token_is_refused(anon):
    with cloudflare_mode():
        res = anon.get("/api/projects",
                       headers={JWT_HEADER: make_token(expires_in=-60)})
        assert res.status_code == 403
        assert "expired" in res.json()["detail"]


def test_garbage_in_the_jwt_header_is_refused_not_crashed(anon):
    with cloudflare_mode():
        for junk in ("not-a-jwt", "a.b.c", "Bearer " + make_token()):
            res = anon.get("/api/projects", headers={JWT_HEADER: junk})
            assert res.status_code == 403, junk


def test_a_service_token_is_refused_because_it_has_no_person(anon):
    with cloudflare_mode():
        res = anon.get("/api/projects", headers={
            JWT_HEADER: make_token(email=None, common_name="ci-runner.access"),
        })
        assert res.status_code == 403
        assert "service token" in res.json()["detail"]


def test_an_unsigned_none_algorithm_token_is_refused(anon):
    """The classic JWT attack: strip the signature and set alg to none."""
    with cloudflare_mode():
        now = int(time.time())
        forged = pyjwt.encode(
            {"aud": [AUD], "iss": ISSUER, "iat": now, "exp": now + 3600,
             "email": "attacker@evil.com"},
            key="", algorithm="none", headers={"kid": KID},
        )
        res = anon.get("/api/projects", headers={JWT_HEADER: forged})
        assert res.status_code == 403


# --- configuration ------------------------------------------------------------

def test_cloudflare_mode_refuses_to_run_without_a_team_and_aud():
    """No silent fallback to header trust. Missing config is a hard error."""
    with auth_mode("cloudflare"):
        previous = (settings.access_team_domain, settings.access_aud)
        settings.access_team_domain = ""
        settings.access_aud = ""
        access_jwt.reset_verifier()
        try:
            with pytest.raises(access_jwt.AccessConfigError):
                access_jwt.get_verifier()
        finally:
            settings.access_team_domain, settings.access_aud = previous
            access_jwt.reset_verifier()


@pytest.mark.parametrize("given", [
    "myteam",
    "myteam.cloudflareaccess.com",
    "https://myteam.cloudflareaccess.com",
    "https://myteam.cloudflareaccess.com/",
    "  MyTeam  ",
])
def test_team_domain_accepts_whatever_shape_you_paste(given):
    assert access_jwt.normalize_team_domain(given) == "myteam.cloudflareaccess.com"


# --- display names ------------------------------------------------------------

def test_access_member_starts_unconfirmed_and_can_name_themselves(anon):
    """A school address is often an ID, not a name. The member is created with
    name_confirmed=False so the UI knows to ask, and setting a name is
    self-service -- no admin has to fix it."""
    with cloudflare_mode():
        token = make_token("w1234567@school.edu")
        me = anon.get("/api/auth/me", headers={JWT_HEADER: token}).json()
        assert me["name"] == "W1234567"          # derived from the address
        assert me["name_confirmed"] is False

        res = anon.patch("/api/auth/me", headers={JWT_HEADER: token},
                         json={"name": "  Dana Whitfield  ", "subteam": "Brakes"})
        assert res.status_code == 200, res.text
        updated = res.json()
        assert updated["name"] == "Dana Whitfield"   # trimmed
        assert updated["subteam"] == "Brakes"
        assert updated["name_confirmed"] is True

        # Sticks, and is not asked for again.
        again = anon.get("/api/auth/me", headers={JWT_HEADER: token}).json()
        assert again["name"] == "Dana Whitfield"
        assert again["name_confirmed"] is True


def test_you_cannot_change_your_email_through_the_profile_endpoint(anon):
    """Email is the identity Cloudflare verified. If it were editable, someone
    could point their record at a teammate's address and become them."""
    with cloudflare_mode():
        token = make_token("impostor@school.edu")
        anon.get("/api/auth/me", headers={JWT_HEADER: token})
        anon.patch("/api/auth/me", headers={JWT_HEADER: token},
                   json={"name": "Nice Try", "email": "captain@school.edu"})
        me = anon.get("/api/auth/me", headers={JWT_HEADER: token}).json()
        assert me["email"] == "impostor@school.edu"


def test_naming_yourself_requires_being_signed_in(anon):
    with cloudflare_mode():
        assert anon.patch("/api/auth/me", json={"name": "Nobody"}).status_code == 403


def test_a_roster_member_added_by_hand_is_already_named(client):
    """Someone typed that name, so they should never see the "who are you?" prompt."""
    m = client.post("/api/members", json={"name": "Typed By A Human"}).json()
    assert m["name_confirmed"] is True


# --- the other modes ----------------------------------------------------------

def test_built_in_login_is_disabled_outside_password_mode(anon):
    with cloudflare_mode():
        assert anon.get("/login").status_code == 404
        assert anon.post("/api/auth/login",
                         json={"email": "a@b.c", "password": "x"}).status_code == 404


def test_health_reports_the_mode_without_a_token(anon):
    """Health stays public so `fly status` works, and leaks nothing but the mode."""
    with cloudflare_mode():
        body = anon.get("/api/health").json()
        assert body["auth_mode"] == "cloudflare"
        assert set(body) == {"status", "team", "auth_mode"}


def test_none_mode_is_open_and_needs_no_token(anon):
    with auth_mode("none"):
        assert anon.get("/api/projects").status_code == 200
        assert anon.get("/api/auth/me").json()["email"] == "local@localhost"


def test_password_mode_ignores_both_cloudflare_headers(anon):
    """A forged header must not grant anything when the app is not behind
    Cloudflare — otherwise switching modes would open a hole."""
    res = anon.get("/api/projects", headers={
        EMAIL_HEADER: "attacker@evil.com",
        JWT_HEADER: "irrelevant",
    })
    assert res.status_code == 401


@pytest.mark.parametrize("raw,expected", [
    ("", []),
    ("pitbox.yourteam.org", ["pitbox.yourteam.org"]),
    ("a.org, b.org ,, c.org ", ["a.org", "b.org", "c.org"]),
])
def test_allowed_hosts_parsing(raw, expected):
    """Comma-separated rather than JSON, because this is typed into fly.toml by
    hand and `["a"]` in a TOML string is a miserable thing to get wrong."""
    previous = settings.allowed_hosts
    settings.allowed_hosts = raw
    try:
        assert settings.allowed_host_list == expected
    finally:
        settings.allowed_hosts = previous
