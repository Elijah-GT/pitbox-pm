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
    target = _add(client, project["id"], lvl2["id"], "Deep Target", status="not_installed")

    r = client.get(f"/api/projects/{project['id']}/filter", params={"status": ["not_installed"]})
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


# --- the write allowlist ------------------------------------------------------
# The Access policy is a whole email domain, so "signed in" no longer means
# "trusted to change things". These check the line between the two.

def test_a_signed_in_non_admin_can_read_everything(anon, project):
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("reader@school.edu")}
        assert anon.get("/api/projects", headers=h).status_code == 200
        assert anon.get(f"/api/projects/{project['id']}/tree", headers=h).status_code == 200
        assert anon.get("/api/tags", headers=h).status_code == 200
        assert anon.get("/api/members", headers=h).status_code == 200


def test_a_member_can_edit_an_existing_part(client, anon, project):
    """The line is EDIT versus ADD/DELETE. Someone working on their subsystem has
    to be able to mark a part ordered and set its cost without waiting on a lead;
    that is the daily job, and needing an admin for it would make this worse than
    the spreadsheet it replaced."""
    root = _tree(client, project["id"])["nodes"][0]
    part = _add(client, project["id"], root["id"], "Editable Part")
    tag_id = client.get("/api/tags").json()[0]["id"]

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("member@school.edu")}

        res = anon.patch(f"/api/nodes/{part['id']}", headers=h, json={
            "name": "Renamed by a member", "status": "ordered",
            "cost_cents": 4250, "vendor": "McMaster",
        })
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Renamed by a member"
        assert res.json()["status"] == "ordered"

        # Re-parenting and reordering: neither adds nor deletes, and a branch
        # dropped in the wrong place is fixed by dragging it back.
        assert anon.post(f"/api/nodes/{part['id']}/move", headers=h,
                         json={"new_parent_id": root["id"]}).status_code == 200
        assert anon.post("/api/nodes/reorder", headers=h, json={
            "project_id": project["id"], "parent_id": root["id"],
            "ordered_ids": [part["id"]]}).status_code == 204

        # Applying an existing tag is editing the part, not editing the tag.
        assert anon.post(f"/api/nodes/{part['id']}/tags", headers=h,
                         json={"tag_id": tag_id, "cascade": False}).status_code == 201
        assert anon.delete(f"/api/nodes/{part['id']}/tags/{tag_id}",
                           headers=h).status_code == 204

        # Attaching a drawing or datasheet is part of doing the work.
        assert anon.post("/api/attachments", headers=h,
                         files={"file": ("spec.txt", b"hello")},
                         data={"node_id": str(part["id"])}).status_code == 201


def test_a_member_cannot_add_delete_or_restructure(anon, client, project):
    """The whole point: a school-wide login must not be able to wipe a subsystem."""
    root = _tree(client, project["id"])["nodes"][0]
    doomed = _add(client, project["id"], root["id"], "Not Yours To Delete")
    uploaded = client.post("/api/attachments", files={"file": ("x.txt", b"x")},
                           data={"node_id": str(doomed["id"])}).json()

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("vandal@school.edu")}

        # adding
        assert anon.post("/api/nodes", headers=h, json={
            "project_id": project["id"], "parent_id": root["id"], "name": "Sneaky part",
        }).status_code == 403
        assert anon.post(f"/api/nodes/{root['id']}/duplicate", headers=h,
                         json={}).status_code == 403
        # deleting
        assert anon.delete(f"/api/nodes/{doomed['id']}", headers=h).status_code == 403
        assert anon.delete(f"/api/attachments/{uploaded['id']}", headers=h).status_code == 403
        # whole trees
        assert anon.post("/api/projects", headers=h, json={
            "name": "Theirs", "template": "blank"}).status_code == 403
        assert anon.post("/api/projects/clone", headers=h, json={
            "name": "Copy", "source_project_id": project["id"]}).status_code == 403
        assert anon.patch(f"/api/projects/{project['id']}", headers=h,
                          json={"name": "Renamed tree"}).status_code == 403
        assert anon.delete(f"/api/projects/{project['id']}", headers=h).status_code == 403
        # the shared tag vocabulary, which spans every project and season
        assert anon.post("/api/tags", headers=h, json={"name": "Nope"}).status_code == 403
        assert anon.patch("/api/tags/1", headers=h, json={"name": "Nope"}).status_code == 403
        assert anon.delete("/api/tags/1", headers=h).status_code == 403

        # and nothing actually went
        after = anon.get(f"/api/projects/{project['id']}/tree", headers=h).json()
        assert doomed["id"] in {n["id"] for n in after["nodes"]}


def test_the_allowlist_matches_the_routes_that_exist(anon):
    """A renamed route must not silently turn an everyday member action into an
    admin-only one. main.py runs this at import; here it is again as a test, so
    the failure names the offending entry instead of a 403 nobody can explain."""
    from app.main import PROTECTED
    from app.security import validate_member_writable

    validate_member_writable(PROTECTED)  # raises RuntimeError if it drifts


def test_the_refusal_explains_what_to_do(anon, project):
    with cloudflare_mode():
        res = anon.delete(f"/api/projects/{project['id']}",
                          headers={JWT_HEADER: make_token("polite@school.edu")})
        assert res.status_code == 403
        detail = res.json()["detail"]
        assert "team lead" in detail and "admin" in detail


def test_a_new_access_member_is_not_an_admin(anon):
    """No auto-promotion on a database that already has people in it."""
    with cloudflare_mode():
        body = anon.get("/api/auth/me",
                        headers={JWT_HEADER: make_token("nobody@school.edu")}).json()
        assert body["is_admin"] is False


def test_the_first_member_on_an_empty_database_becomes_the_admin():
    """Somebody has to be able to start. On a fresh install it is whoever signs
    in first; after that, admins are only ever made by other admins."""
    import sqlalchemy
    from sqlalchemy.orm import sessionmaker

    from app.models import Base as ModelBase
    from app.security import upsert_access_member

    engine = sqlalchemy.create_engine("sqlite://")  # in-memory, its own world
    ModelBase.metadata.create_all(engine)
    Fresh = sessionmaker(bind=engine)

    with Fresh() as db:
        first = upsert_access_member(db, "founder@school.edu")
        assert first.is_admin is True
        second = upsert_access_member(db, "everyone-else@school.edu")
        assert second.is_admin is False
        # ...and coming back later does not re-run the bootstrap
        assert upsert_access_member(db, "everyone-else@school.edu").is_admin is False


def test_a_non_admin_cannot_promote_themselves(anon):
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("climber@school.edu")}
        me = anon.get("/api/auth/me", headers=h).json()
        assert anon.patch(f"/api/members/{me['id']}/admin", headers=h,
                          json={"is_admin": True}).status_code == 403
        assert anon.get("/api/auth/me", headers=h).json()["is_admin"] is False


def test_the_general_member_edit_cannot_grant_admin(client):
    """is_admin is not a field on MemberIn, so it cannot ride along on a roster
    edit -- Pydantic drops the unknown key rather than applying it."""
    made = client.post("/api/members", json={
        "name": "Ordinary", "email": "ordinary@example.edu"}).json()
    assert made["is_admin"] is False
    res = client.patch(f"/api/members/{made['id']}",
                       json={"name": "Ordinary", "is_admin": True})
    assert res.status_code == 200
    assert res.json()["is_admin"] is False


def test_an_admin_can_promote_and_demote(client):
    made = client.post("/api/members", json={
        "name": "Next Lead", "email": "next-lead@example.edu"}).json()

    res = client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": True})
    assert res.status_code == 200, res.text
    assert res.json()["is_admin"] is True

    res = client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": False})
    assert res.status_code == 200
    assert res.json()["is_admin"] is False


def test_a_promoted_member_can_then_write(anon, project):
    """The promotion has to take effect on the very next request."""
    from app.database import SessionLocal
    from app.models import Member

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("promoted@school.edu")}
        me = anon.get("/api/auth/me", headers=h).json()
        root = anon.get(f"/api/projects/{project['id']}/tree", headers=h).json()["nodes"][0]
        assert anon.post("/api/nodes", headers=h, json={
            "project_id": project["id"], "parent_id": root["id"], "name": "Before",
        }).status_code == 403

    with SessionLocal() as db:
        db.get(Member, me["id"]).is_admin = True
        db.commit()

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("promoted@school.edu")}
        assert anon.post("/api/nodes", headers=h, json={
            "project_id": project["id"], "parent_id": root["id"], "name": "After",
        }).status_code == 201


def test_the_last_admin_cannot_be_demoted(client):
    """Otherwise the instance becomes permanently read-only, fixable only from a
    shell -- the dependency the Team panel exists to remove."""
    from sqlalchemy import select

    from app.database import SessionLocal
    from app.models import Member

    me = client.get("/api/auth/me").json()
    assert me["is_admin"] is True

    # Make sure this really is the last one, whatever earlier tests left behind,
    # and put them back afterwards -- the module shares one database, and
    # silently demoting the auth_mode=none local user here made a later test
    # fail somewhere else entirely.
    with SessionLocal() as db:
        stood_down = [m.id for m in db.scalars(select(Member).where(
            Member.is_admin.is_(True), Member.id != me["id"]
        ))]
        for member_id in stood_down:
            db.get(Member, member_id).is_admin = False
        db.commit()

    try:
        res = client.patch(f"/api/members/{me['id']}/admin", json={"is_admin": False})
        assert res.status_code == 400
        assert "last admin" in res.json()["detail"]
        assert client.get("/api/auth/me").json()["is_admin"] is True
    finally:
        with SessionLocal() as db:
            for member_id in stood_down:
                db.get(Member, member_id).is_admin = True
            db.commit()


def test_an_admin_can_step_down_once_someone_else_can_take_over(client):
    """A lead handing over should not need their successor to do it for them."""
    from app.database import SessionLocal
    from app.models import Member

    me = client.get("/api/auth/me").json()
    heir = client.post("/api/members", json={
        "name": "Heir", "email": "heir@example.edu"}).json()
    assert client.patch(f"/api/members/{heir['id']}/admin",
                        json={"is_admin": True}).status_code == 200

    assert client.patch(f"/api/members/{me['id']}/admin",
                        json={"is_admin": False}).status_code == 200

    # Put the fixture's admin back for the tests that follow.
    with SessionLocal() as db:
        db.get(Member, me["id"]).is_admin = True
        db.get(Member, heir["id"]).is_admin = False
        db.commit()


def test_a_deactivated_member_cannot_be_made_admin(client):
    made = client.post("/api/members", json={
        "name": "Gone", "email": "gone@example.edu", "is_active": False}).json()
    res = client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": True})
    assert res.status_code == 400
    assert "deactivated" in res.json()["detail"]


def test_promoting_someone_who_already_is_one_is_not_an_error(client):
    made = client.post("/api/members", json={
        "name": "Twice", "email": "twice@example.edu"}).json()
    client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": True})
    res = client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": True})
    assert res.status_code == 200 and res.json()["is_admin"] is True
    client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": False})


def test_a_non_admin_can_still_name_themselves(anon):
    """PATCH /api/auth/me is a write, but it is about your OWN row and it is the
    fix for showing up as a school ID. Locking it to admins would make every new
    teammate wait on a lead just to be identifiable."""
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("w9999999@school.edu")}
        anon.get("/api/auth/me", headers=h)
        res = anon.patch("/api/auth/me", headers=h,
                         json={"name": "Real Name", "subteam": "Suspension"})
        assert res.status_code == 200, res.text
        assert res.json()["name"] == "Real Name"
        assert res.json()["is_admin"] is False


def test_none_mode_still_lets_you_do_everything(anon, project):
    """auth_mode=none is the offline laptop case. Its local user is an admin, so
    adding the write lock must not have broken working with no login at all."""
    with auth_mode("none"):
        root = anon.get(f"/api/projects/{project['id']}/tree").json()["nodes"][0]
        res = anon.post("/api/nodes", json={
            "project_id": project["id"], "parent_id": root["id"], "name": "Local part",
        })
        assert res.status_code == 201, res.text


def test_deactivating_someone_takes_their_admin_with_it(client):
    """Under Cloudflare Access a deactivated member is reactivated on their next
    sign-in, so a surviving admin flag would quietly hand back the access a lead
    just removed."""
    made = client.post("/api/members", json={
        "name": "Graduating Lead", "email": "graduating@example.edu"}).json()
    assert client.patch(f"/api/members/{made['id']}/admin",
                        json={"is_admin": True}).status_code == 200

    assert client.delete(f"/api/members/{made['id']}").status_code == 204

    after = next(m for m in client.get("/api/members?include_inactive=true").json()
                 if m["id"] == made["id"])
    assert after["is_active"] is False
    assert after["is_admin"] is False


def test_a_deactivated_admin_can_still_be_demoted(client):
    """The last-admin guard counts admins who can actually sign in. A
    deactivated one is not among them, so refusing to clear their flag would
    strand it on the account permanently."""
    from app.database import SessionLocal
    from app.models import Member

    made = client.post("/api/members", json={
        "name": "Stranded", "email": "stranded@example.edu"}).json()

    # Build the state by hand: inactive AND admin, which the API no longer
    # produces on its own but old databases still contain.
    with SessionLocal() as db:
        row = db.get(Member, made["id"])
        row.is_admin = True
        row.is_active = False
        db.commit()

    res = client.patch(f"/api/members/{made['id']}/admin", json={"is_admin": False})
    assert res.status_code == 200, res.text
    assert res.json()["is_admin"] is False


# --- the status vocabulary ----------------------------------------------------

def test_the_new_status_is_accepted_and_the_old_ones_are_not(client, project):
    root = _tree(client, project["id"])["nodes"][0]
    part = _add(client, project["id"], root["id"], "Status Test")

    res = client.patch(f"/api/nodes/{part['id']}", json={"status": "not_installed"})
    assert res.status_code == 200, res.text
    assert res.json()["status"] == "not_installed"

    for gone in ("released", "needs_rework", "scrapped"):
        assert client.patch(f"/api/nodes/{part['id']}",
                            json={"status": gone}).status_code == 422, gone


def test_a_node_on_a_retired_status_does_not_break_the_tree(client, project):
    """The reason retire_dead_statuses() exists. status is validated on the way
    OUT as well as in, so one row left on a removed value breaks the whole tree
    endpoint, not just that node."""
    from pydantic import ValidationError
    from sqlalchemy import text as sql_text

    from app.database import engine
    from app.migrate import retire_dead_statuses

    root = _tree(client, project["id"])["nodes"][0]
    part = _add(client, project["id"], root["id"], "Legacy Part")

    # Write the dead value straight to the database, the way a season-old
    # instance would already have it. The API itself refuses to create one.
    with engine.begin() as conn:
        conn.execute(sql_text("UPDATE nodes SET status = 'scrapped' WHERE id = :i"),
                     {"i": part["id"]})

    try:
        # Serializing the tree now fails on THIS node and takes the request with
        # it. TestClient re-raises server exceptions rather than returning 500.
        with pytest.raises(ValidationError):
            client.get(f"/api/projects/{project['id']}/tree")

        assert retire_dead_statuses(engine) == {"scrapped": 1}

        assert client.get(f"/api/projects/{project['id']}/tree").status_code == 200
        after = client.get(f"/api/nodes/{part['id']}").json()
        assert after["status"] == "concept"
        # The old value is kept, not binned -- somebody entered it on purpose.
        assert after["extra"]["former_status"] == "scrapped"
    finally:
        # The database is shared across this module; never leave a poisoned row
        # behind for whatever runs next.
        retire_dead_statuses(engine)


def test_retiring_statuses_is_idempotent_and_keeps_the_first_value(client, project):
    """Running it twice must not overwrite former_status with a later hop."""
    from sqlalchemy import text as sql_text

    from app.database import engine
    from app.migrate import retire_dead_statuses

    root = _tree(client, project["id"])["nodes"][0]
    part = _add(client, project["id"], root["id"], "Twice Migrated")

    with engine.begin() as conn:
        conn.execute(sql_text("UPDATE nodes SET status = 'released' WHERE id = :i"),
                     {"i": part["id"]})

    try:
        assert retire_dead_statuses(engine) == {"released": 1}
        assert retire_dead_statuses(engine) == {}          # nothing left to do

        after = client.get(f"/api/nodes/{part['id']}").json()
        assert after["status"] == "in_review"
        assert after["extra"]["former_status"] == "released"
    finally:
        retire_dead_statuses(engine)


def test_every_retired_status_maps_to_a_live_one():
    """A typo in RETIRED_STATUSES would move nodes onto a value that is still
    invalid, which is the exact breakage this is supposed to prevent."""
    from app.models import RETIRED_STATUSES, STATUSES

    for old, new in RETIRED_STATUSES.items():
        assert old not in STATUSES, f"{old} is still a live status"
        assert new in STATUSES, f"{old} maps to {new}, which does not exist"


def test_the_two_frontends_agree_with_the_backend_on_statuses():
    """Three copies of this list exist: models.py, the React app, and static/.
    They drift silently -- a status the API accepts but the UI cannot label
    renders as a blank pip with no dropdown entry."""
    import re

    from app.models import STATUSES

    root = Path(__file__).resolve().parent.parent

    ts = (root / "frontend" / "src" / "lib" / "format.ts").read_text(encoding="utf-8")
    block = ts.split("STATUS_LABELS: Record<Status, string> = {")[1].split("}")[0]
    react = re.findall(r"^\s*(\w+):", block, re.M)

    js = (root / "static" / "js" / "treeview.js").read_text(encoding="utf-8")
    block = js.split("export const STATUS_LABELS = {")[1].split("}")[0]
    vanilla = re.findall(r"^\s*(\w+):", block, re.M)

    assert react == list(STATUSES), f"React: {react} != {list(STATUSES)}"
    assert vanilla == list(STATUSES), f"static/: {vanilla} != {list(STATUSES)}"


# --- the project timeline -----------------------------------------------------

def _goal(client, project_id, title, due, **kw):
    r = client.post("/api/milestones", json={
        "project_id": project_id, "title": title, "due_date": due, **kw,
    })
    assert r.status_code == 201, r.text
    return r.json()


def test_milestones_come_back_in_date_order(client, project):
    _goal(client, project["id"], "Design review", "2026-04-23")
    _goal(client, project["id"], "BOM due", "2026-03-06")
    _goal(client, project["id"], "Roll cage doc package", "2026-02-12")

    rows = client.get(f"/api/milestones?project_id={project['id']}").json()
    assert [r["title"] for r in rows] == [
        "Roll cage doc package", "BOM due", "Design review",
    ]
    assert all(r["done"] is False and r["done_at"] is None for r in rows)


def test_ticking_a_goal_off_stamps_when(client, project):
    made = _goal(client, project["id"], "Frame welded", "2026-01-15")

    done = client.patch(f"/api/milestones/{made['id']}", json={"done": True})
    assert done.status_code == 200, done.text
    assert done.json()["done"] is True
    assert done.json()["done_at"] is not None

    # Un-ticking clears the stamp rather than leaving a date that claims it was
    # finished once.
    undone = client.patch(f"/api/milestones/{made['id']}", json={"done": False})
    assert undone.json()["done"] is False
    assert undone.json()["done_at"] is None


def test_editing_other_fields_does_not_touch_the_done_stamp(client, project):
    made = _goal(client, project["id"], "Seat mounted", "2026-02-01")
    client.patch(f"/api/milestones/{made['id']}", json={"done": True})
    stamped = client.get(f"/api/milestones?project_id={project['id']}").json()
    was = next(r for r in stamped if r["id"] == made["id"])["done_at"]

    client.patch(f"/api/milestones/{made['id']}", json={"title": "Seat mounted and padded"})
    after = client.get(f"/api/milestones?project_id={project['id']}").json()
    row = next(r for r in after if r["id"] == made["id"])
    assert row["title"] == "Seat mounted and padded"
    assert row["done_at"] == was


def test_a_goal_cannot_point_at_a_part_in_another_tree(client, project):
    """Otherwise the timeline offers a jump that lands you in a different
    season with no explanation."""
    other = client.post("/api/projects", json={"name": "Other Car", "template": "blank"}).json()
    foreign = _tree(client, other["id"])["nodes"][0]

    r = client.post("/api/milestones", json={
        "project_id": project["id"], "title": "Wrong tree",
        "due_date": "2026-02-01", "node_id": foreign["id"],
    })
    assert r.status_code == 400
    assert "different tree" in r.json()["detail"]


def test_deleting_the_linked_part_keeps_the_goal(client, project):
    """SET NULL, not CASCADE. A part being deleted is exactly when you still
    want to see the deadline that referred to it."""
    root = _tree(client, project["id"])["nodes"][0]
    part = _add(client, project["id"], root["id"], "Fuel tank mount")
    made = _goal(client, project["id"], "Fuel tank mounted", "2026-01-20", node_id=part["id"])

    assert client.delete(f"/api/nodes/{part['id']}").status_code == 200

    rows = client.get(f"/api/milestones?project_id={project['id']}").json()
    row = next(r for r in rows if r["id"] == made["id"])
    assert row["node_id"] is None
    assert row["title"] == "Fuel tank mounted"


def test_deleting_a_project_takes_its_timeline_with_it(client):
    doomed = client.post("/api/projects", json={"name": "Doomed", "template": "blank"}).json()
    _goal(client, doomed["id"], "Never happens", "2026-05-01")

    assert client.delete(f"/api/projects/{doomed['id']}").status_code == 204
    assert client.get(f"/api/milestones?project_id={doomed['id']}").status_code == 404


def test_a_member_can_tick_a_goal_off_but_not_create_or_delete_one(anon, client, project):
    """The line everywhere else in the app: editing is any member, adding and
    deleting is a lead. Someone who finished the work should not need a lead to
    tick the box."""
    made = _goal(client, project["id"], "DAQ on car", "2026-03-01")

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("member@school.edu")}

        assert anon.get(f"/api/milestones?project_id={project['id']}",
                        headers=h).status_code == 200

        ticked = anon.patch(f"/api/milestones/{made['id']}", headers=h, json={"done": True})
        assert ticked.status_code == 200, ticked.text
        assert ticked.json()["done"] is True

        assert anon.post("/api/milestones", headers=h, json={
            "project_id": project["id"], "title": "Mine", "due_date": "2026-03-02",
        }).status_code == 403
        assert anon.delete(f"/api/milestones/{made['id']}", headers=h).status_code == 403

    # and it really is still there
    rows = client.get(f"/api/milestones?project_id={project['id']}").json()
    assert any(r["id"] == made["id"] for r in rows)


def test_a_goal_needs_a_title_and_a_date(client, project):
    assert client.post("/api/milestones", json={
        "project_id": project["id"], "title": "", "due_date": "2026-02-01"}).status_code == 422
    assert client.post("/api/milestones", json={
        "project_id": project["id"], "title": "No date"}).status_code == 422
    assert client.post("/api/milestones", json={
        "project_id": project["id"], "title": "Bad date", "due_date": "the 12th"}).status_code == 422


# --- goal priority and kind ---------------------------------------------------

def test_a_goal_defaults_to_normal_priority_and_no_particular_kind(client, project):
    made = _goal(client, project["id"], "Something", "2027-01-05")
    assert made["priority"] == "normal"
    assert made["kind"] == "other"


def test_a_goal_can_be_created_as_a_baja_sae_deadline(client, project):
    made = _goal(client, project["id"], "Cost report submission", "2027-02-19",
                 priority="sae", kind="other")
    assert made["priority"] == "sae"

    rows = client.get(f"/api/milestones?project_id={project['id']}").json()
    assert any(r["priority"] == "sae" for r in rows)


def test_priority_and_kind_can_be_changed_later(client, project):
    made = _goal(client, project["id"], "Frame jig", "2026-12-01")
    res = client.patch(f"/api/milestones/{made['id']}",
                       json={"priority": "critical", "kind": "manufacturing"})
    assert res.status_code == 200, res.text
    assert res.json()["priority"] == "critical"
    assert res.json()["kind"] == "manufacturing"


def test_a_member_can_recategorise_a_goal_without_being_an_admin(anon, client, project):
    """Same line as ticking it off: this edits a goal that already exists."""
    made = _goal(client, project["id"], "Uprights machined", "2027-01-30")
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("member@school.edu")}
        res = anon.patch(f"/api/milestones/{made['id']}", headers=h,
                         json={"kind": "manufacturing"})
        assert res.status_code == 200, res.text
        assert res.json()["kind"] == "manufacturing"


@pytest.mark.parametrize("bad", [
    {"priority": "urgent"},      # not one of ours
    {"priority": "SAE"},         # the vocabulary is lowercase
    {"kind": "electrical"},      # a subteam, not a kind of work
    {"kind": ""},
])
def test_a_bogus_priority_or_kind_is_refused(client, project, bad):
    made = _goal(client, project["id"], "Vocabulary check", "2027-03-01")
    assert client.patch(f"/api/milestones/{made['id']}", json=bad).status_code == 422
    assert client.post("/api/milestones", json={
        "project_id": project["id"], "title": "x", "due_date": "2027-03-01", **bad,
    }).status_code == 422


# --- the cut list (manufacturing) ---------------------------------------------

def _part(client, project_id, name, **kw):
    r = client.post("/api/mfg-parts", json={"project_id": project_id, "name": name, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _put_drawing(client, part_id, filename, data, content_type="application/pdf"):
    return client.put(
        f"/api/mfg-parts/{part_id}/drawing",
        files={"file": (filename, data, content_type)},
    )


def test_the_cut_list_reads_in_shop_order(client, project):
    """Grouped by subsystem so everything for the rollcage is together, and the
    odds and ends with no subsystem sort last rather than leading the list."""
    _part(client, project["id"], "Upper A-arm tube", subsystem="Front Suspension")
    _part(client, project["id"], "Weld fixture")                       # no subsystem
    _part(client, project["id"], "Main hoop", subsystem="Rollcage")
    _part(client, project["id"], "Door bar", subsystem="Rollcage")

    rows = client.get(f"/api/mfg-parts?project_id={project['id']}").json()
    assert [r["name"] for r in rows] == [
        "Upper A-arm tube",   # Front Suspension
        "Door bar",           # Rollcage, alphabetical within the subsystem
        "Main hoop",
        "Weld fixture",       # no subsystem -> last
    ]
    assert all(r["status"] == "todo" and r["has_drawing"] is False for r in rows)


def test_a_part_carries_a_name_subsystem_notes_and_a_person(client, project):
    me = client.get("/api/auth/me").json()
    made = _part(client, project["id"], "Lower A-arm tube",
                 subsystem="Front Suspension",
                 notes="0.058 wall, 4130. Cut 4, miter both ends.",
                 assignee_id=me["id"])
    assert made["subsystem"] == "Front Suspension"
    assert "4130" in made["notes"]
    assert made["assignee_id"] == me["id"]


def test_uploading_a_drawing_then_fetching_it(client, project):
    made = _part(client, project["id"], "Main hoop")
    res = _put_drawing(client, made["id"], "main-hoop.pdf", b"%PDF-1.4 fake drawing")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["has_drawing"] is True
    assert body["drawing_filename"] == "main-hoop.pdf"
    assert body["drawing_content_type"] == "application/pdf"
    assert body["drawing_uploaded_at"] is not None

    got = client.get(f"/api/mfg-parts/{made['id']}/drawing")
    assert got.status_code == 200
    assert got.content == b"%PDF-1.4 fake drawing"


def test_a_drawing_is_shown_inline_and_not_sandboxed(client, project):
    """Deliberately NOT sandboxed.

    A CSP sandbox on a PDF response makes Chrome refuse to render it -- "This
    page has been blocked by Chrome" inside an iframe, or a silent download on
    direct navigation. `sandbox allow-scripts` behaves the same way, because
    the viewer is itself JavaScript. You can sandbox a PDF or display it, not
    both, and a drawing nobody can look at is not worth the header.

    This test exists to stop someone adding the sandbox back for good-sounding
    reasons and quietly breaking every drawing in the shop.
    """
    made = _part(client, project["id"], "Inline check")
    _put_drawing(client, made["id"], "d.pdf", b"%PDF-1.4 x")

    res = client.get(f"/api/mfg-parts/{made['id']}/drawing")
    assert res.headers["content-disposition"].startswith("inline")
    assert res.headers["content-type"].startswith("application/pdf")
    assert res.headers["x-content-type-options"] == "nosniff"
    assert "content-security-policy" not in res.headers, (
        "a CSP sandbox here stops Chrome rendering the drawing at all"
    )


def test_the_download_link_forces_a_save(client, project):
    made = _part(client, project["id"], "Download check")
    _put_drawing(client, made["id"], "d.pdf", b"%PDF-1.4 x")

    res = client.get(f"/api/mfg-parts/{made['id']}/drawing?download=1")
    assert res.headers["content-disposition"].startswith("attachment")
    assert res.headers["content-type"] == "application/octet-stream"


def test_an_unrenderable_drawing_downloads_rather_than_displaying(client, project):
    """A .dxf has no business being inlined, and a helpfully-renamed .html has
    even less."""
    made = _part(client, project["id"], "DXF check")
    _put_drawing(client, made["id"], "flat-pattern.dxf", b"0\nSECTION\n", "image/vnd.dxf")

    res = client.get(f"/api/mfg-parts/{made['id']}/drawing")
    assert res.headers["content-disposition"].startswith("attachment")


def test_a_part_with_no_drawing_says_so(client, project):
    made = _part(client, project["id"], "Nothing attached")
    assert client.get(f"/api/mfg-parts/{made['id']}/drawing").status_code == 404


def test_the_storage_address_never_leaves_the_server(client, project):
    """sha256 is an address into the blob store. Publishing it would let anyone
    probe for files they were never shown."""
    made = _part(client, project["id"], "Hash check")
    body = _put_drawing(client, made["id"], "d.pdf", b"%PDF-1.4 x").json()
    assert "drawing_sha256" not in body


def test_replacing_a_drawing_frees_the_old_one(client, project):
    import hashlib

    from app import storage

    made = _part(client, project["id"], "Revision check")
    _put_drawing(client, made["id"], "rev-a.pdf", b"%PDF revision A")
    old_sha = hashlib.sha256(b"%PDF revision A").hexdigest()
    assert storage.blob_path(old_sha).exists()

    _put_drawing(client, made["id"], "rev-b.pdf", b"%PDF revision B")
    # Five revisions should not leave five dead blobs behind.
    assert not storage.blob_path(old_sha).exists()
    assert client.get(f"/api/mfg-parts/{made['id']}/drawing").content == b"%PDF revision B"


def test_deleting_a_part_frees_its_drawing(client, project):
    import hashlib

    from app import storage

    made = _part(client, project["id"], "Doomed part")
    _put_drawing(client, made["id"], "doomed.pdf", b"%PDF doomed bytes")
    sha = hashlib.sha256(b"%PDF doomed bytes").hexdigest()
    assert storage.blob_path(sha).exists()

    assert client.delete(f"/api/mfg-parts/{made['id']}").status_code == 204
    assert not storage.blob_path(sha).exists()


def test_a_drawing_shared_with_a_node_attachment_survives(client, project):
    """THE trap in content-addressed storage: the same PDF uploaded to a tree
    node and set as a part's drawing is ONE file on disk. Clearing the drawing
    must not pull the bytes out from under the attachment."""
    import hashlib

    from app import storage

    shared = b"%PDF-1.4 the very same bytes"
    sha = hashlib.sha256(shared).hexdigest()

    root = _tree(client, project["id"])["nodes"][0]
    att = client.post("/api/attachments", files={"file": ("shared.pdf", shared)},
                      data={"node_id": str(root["id"])})
    assert att.status_code == 201, att.text
    att_id = att.json()["id"]

    made = _part(client, project["id"], "Shares a file")
    _put_drawing(client, made["id"], "shared.pdf", shared)
    assert storage.blob_path(sha).exists()

    # Drop the part's drawing -- the node attachment still needs these bytes.
    assert client.delete(f"/api/mfg-parts/{made['id']}/drawing").status_code == 200
    assert storage.blob_path(sha).exists(), "clearing a drawing deleted bytes an attachment uses"
    assert client.get(f"/api/attachments/{att_id}/download").content == shared

    # And the mirror image: deleting the attachment must not break the drawing.
    _put_drawing(client, made["id"], "shared.pdf", shared)
    assert client.delete(f"/api/attachments/{att_id}").status_code == 204
    assert storage.blob_path(sha).exists(), "deleting an attachment deleted a part's drawing"
    assert client.get(f"/api/mfg-parts/{made['id']}/drawing").content == shared


def test_the_blob_collector_counts_drawings_too(client, project):
    """scripts/gc_blobs.py builds its 'referenced' set from the database. If it
    only looked at attachments, --delete would wipe every drawing.

    Calls the same function the script calls, rather than re-deriving the set
    here -- a copy of the logic in a test passes even when the script is wrong.
    """
    import hashlib

    from app import storage
    from app.database import SessionLocal

    made = _part(client, project["id"], "Collector check")
    _put_drawing(client, made["id"], "gc.pdf", b"%PDF gc bytes")
    sha = hashlib.sha256(b"%PDF gc bytes").hexdigest()

    with SessionLocal() as db:
        assert sha in storage.referenced_hashes(db)


def test_a_member_can_work_the_list_but_not_add_or_delete_parts(anon, client, project):
    """Same line as everywhere else: the person at the bandsaw marks it done
    and uploads what they cut from; leads decide what is on the list."""
    made = _part(client, project["id"], "Member check")

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("shop@school.edu")}

        assert anon.get(f"/api/mfg-parts?project_id={project['id']}",
                        headers=h).status_code == 200
        assert anon.patch(f"/api/mfg-parts/{made['id']}", headers=h,
                          json={"status": "done", "notes": "cut 4"}).status_code == 200
        assert anon.put(f"/api/mfg-parts/{made['id']}/drawing", headers=h,
                        files={"file": ("m.pdf", b"%PDF m")}).status_code == 200
        assert anon.delete(f"/api/mfg-parts/{made['id']}/drawing",
                           headers=h).status_code == 200

        assert anon.post("/api/mfg-parts", headers=h, json={
            "project_id": project["id"], "name": "Mine"}).status_code == 403
        assert anon.delete(f"/api/mfg-parts/{made['id']}", headers=h).status_code == 403

    assert any(r["id"] == made["id"]
               for r in client.get(f"/api/mfg-parts?project_id={project['id']}").json())


def test_a_part_carries_related_links(client, project):
    made = _part(client, project["id"], "Main hoop", links=[
        {"label": "Onshape", "url": "https://cad.onshape.com/documents/AbC123/w/Xy/e/Zz"},
        {"url": "https://www.mcmaster.com/4322T19/"},
    ])
    assert [link["label"] for link in made["links"]] == ["Onshape", None]
    # Case is preserved: Onshape document ids are mixed case and paths can be
    # case-sensitive.
    assert "AbC123" in made["links"][0]["url"]

    cleared = client.patch(f"/api/mfg-parts/{made['id']}", json={"links": []}).json()
    assert cleared["links"] == []


def test_a_part_defaults_to_no_links(client, project):
    assert _part(client, project["id"], "No links yet")["links"] == []


@pytest.mark.parametrize("bad_url", [
    "javascript:alert(document.cookie)",   # stored XSS, the reason this is checked
    "JavaScript:alert(1)",                 # the check is case-insensitive
    "data:text/html,<script>alert(1)</script>",
    "file:///etc/passwd",
    "ftp://example.com/x",
    "/api/projects",                       # relative, no scheme
    "cad.onshape.com/documents/x",         # bare host, no scheme
])
def test_a_link_must_be_an_http_url(client, project, bad_url):
    """These render as real hrefs, so a javascript: URL stored here would fire
    for whoever clicked it."""
    assert client.post("/api/mfg-parts", json={
        "project_id": project["id"], "name": "Link check",
        "links": [{"url": bad_url}],
    }).status_code == 422

    made = _part(client, project["id"], f"Patch check {abs(hash(bad_url)) % 10000}")
    assert client.patch(f"/api/mfg-parts/{made['id']}",
                        json={"links": [{"url": bad_url}]}).status_code == 422
    # and nothing was written
    assert client.get(f"/api/mfg-parts?project_id={project['id']}").json()
    fresh = next(p for p in client.get(
        f"/api/mfg-parts?project_id={project['id']}").json() if p["id"] == made["id"])
    assert fresh["links"] == []


def test_the_migration_adds_links_to_an_existing_cut_list():
    """mfg_parts shipped before links existed, so a database that already has
    the table needs the column added -- and the default has to be a valid
    empty list, not NULL, or every existing part reads back broken."""
    import json
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy

    from app.migrate import run_migrations

    tmp = Path(tempfile.mkdtemp(prefix="pitbox-mfg-oldschema-")) / "old.db"
    raw = sqlite3.connect(tmp)
    raw.executescript(
        """
        CREATE TABLE mfg_parts (
          id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
          name VARCHAR(200) NOT NULL, subsystem VARCHAR(80),
          status VARCHAR(20) NOT NULL DEFAULT 'todo', notes TEXT,
          assignee_id INTEGER, drawing_sha256 VARCHAR(64),
          drawing_filename VARCHAR(255), drawing_content_type VARCHAR(120),
          drawing_size_bytes INTEGER, drawing_uploaded_at DATETIME,
          created_at DATETIME, updated_at DATETIME);
        INSERT INTO mfg_parts (id, project_id, name) VALUES (1, 1, 'Main hoop');
        """
    )
    raw.commit()
    raw.close()

    engine = sqlalchemy.create_engine(f"sqlite:///{tmp.as_posix()}")
    assert "mfg_parts.links" in run_migrations(engine)

    check = sqlite3.connect(tmp)
    name, links = check.execute("SELECT name, links FROM mfg_parts").fetchone()
    assert name == "Main hoop"
    assert json.loads(links) == [], "the default must parse as an empty list, not NULL"
    check.close()

    assert run_migrations(engine) == []     # idempotent


def test_a_blank_subsystem_is_stored_as_no_subsystem(client, project):
    """Otherwise the list grows two separate "no subsystem" groups -- one for
    NULL and one for "" -- and they sort to opposite ends, which reads as a
    bug. Caught by actually using the thing: a part sent with subsystem="" led
    the list instead of trailing it."""
    blank = _part(client, project["id"], "  Spacer  ", subsystem="   ", notes="  ")
    assert blank["subsystem"] is None
    assert blank["notes"] is None
    assert blank["name"] == "Spacer"          # trimmed on the way in

    named = _part(client, project["id"], "Hoop", subsystem="Rollcage")
    # Emptying it later must land in the same state as never setting it.
    cleared = client.patch(f"/api/mfg-parts/{named['id']}", json={"subsystem": ""}).json()
    assert cleared["subsystem"] is None

    rows = client.get(f"/api/mfg-parts?project_id={project['id']}").json()
    assert [r["subsystem"] for r in rows] == [None, None], "blank must sort with NULL, not before it"


@pytest.mark.parametrize("bad", [{"status": "machining"}, {"status": ""}, {"name": ""},
                                 {"name": "   "}])
def test_a_bogus_part_field_is_refused(client, project, bad):
    made = _part(client, project["id"], "Validation check")
    assert client.patch(f"/api/mfg-parts/{made['id']}", json=bad).status_code == 422


def test_deleting_a_project_takes_its_cut_list_with_it(client):
    doomed = client.post("/api/projects",
                         json={"name": "Doomed shop", "template": "blank"}).json()
    _part(client, doomed["id"], "Goes away")
    assert client.delete(f"/api/projects/{doomed['id']}").status_code == 204
    assert client.get(f"/api/mfg-parts?project_id={doomed['id']}").status_code == 404


def test_the_migration_adds_priority_and_kind_to_an_existing_timeline():
    """The milestones table shipped before these columns existed, so a live
    database has the table and not the columns. create_all() builds missing
    TABLES and never missing columns, so without migrate.py the timeline 500s
    on every read the moment the new code lands."""
    import sqlite3
    import tempfile
    from pathlib import Path

    import sqlalchemy

    from app.migrate import run_migrations

    tmp = Path(tempfile.mkdtemp(prefix="pitbox-oldschema-")) / "old.db"
    raw = sqlite3.connect(tmp)
    raw.executescript(
        """
        CREATE TABLE milestones (
          id INTEGER PRIMARY KEY, project_id INTEGER NOT NULL,
          title VARCHAR(200) NOT NULL, detail TEXT, due_date DATE NOT NULL,
          done BOOLEAN NOT NULL DEFAULT 0, done_at DATETIME,
          owner_id INTEGER, node_id INTEGER,
          created_at DATETIME, updated_at DATETIME);
        INSERT INTO milestones (id, project_id, title, due_date, done)
          VALUES (1, 1, 'Roll cage doc package', '2027-02-12', 0);
        """
    )
    raw.commit()
    raw.close()

    engine = sqlalchemy.create_engine(f"sqlite:///{tmp.as_posix()}")
    applied = run_migrations(engine)
    assert "milestones.priority" in applied
    assert "milestones.kind" in applied

    check = sqlite3.connect(tmp)
    cols = {r[1] for r in check.execute("PRAGMA table_info(milestones)")}
    assert {"priority", "kind"} <= cols
    # The existing row survives and is backfilled, not blanked.
    row = check.execute("SELECT title, priority, kind FROM milestones").fetchone()
    assert row == ("Roll cage doc package", "normal", "other")
    check.close()

    # Idempotent: booting twice must not try to add them again.
    assert run_migrations(engine) == []


# --- the blob store: one list of who points at it ------------------------------

def test_every_blob_column_is_known_to_the_collector():
    """A table that stores a blob address but is missing from
    storage.blob_reference_columns() gets its files deleted by the collector
    and by any delete path that frees bytes. This is how the GC once came
    close to wiping every shop drawing -- so make adding a fourth table
    without registering it fail loudly, here, instead of in production."""
    from app import storage
    from app.models import Base as ModelBase

    found = {
        f"{mapper.class_.__name__}.{col.key}"
        for mapper in ModelBase.registry.mappers
        for col in mapper.column_attrs
        if col.key.endswith("sha256")
    }
    known = {f"{c.class_.__name__}.{c.key}" for c in storage.blob_reference_columns()}
    assert found == known, f"unregistered blob columns: {found - known}"


# --- Learn ---------------------------------------------------------------------

def _library(client):
    r = client.get("/api/learn")
    assert r.status_code == 200, r.text
    return r.json()["sections"]


def _section_named(client, title):
    matches = [s for s in _library(client) if s["title"] == title]
    assert len(matches) == 1, f"expected one {title!r}, got {len(matches)}"
    return matches[0]


def _learn_section(client, title, **kw):
    r = client.post("/api/learn/sections", json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _learn_page(client, section_id, title):
    r = client.post("/api/learn/pages", json={"section_id": section_id, "title": title})
    assert r.status_code == 201, r.text
    return r.json()


def _learn_image(client, section_id, data, filename="photo.png", page_id=None, headers=None):
    form = {"section_id": str(section_id)}
    if page_id is not None:
        form["page_id"] = str(page_id)
    return client.post("/api/learn/images", data=form, headers=headers or {},
                       files={"file": (filename, data)})


def test_learn_starts_with_the_four_topics_and_the_cad_guide(client):
    sections = _library(client)
    library = [s["title"] for s in sections if s["group"] == "library"]
    # [:4] -- later tests add their own sections to the library.
    assert library[:4] == ["Drivetrain", "Suspension", "Steering", "Welding"]
    cad = [s for s in sections if s["group"] == "cad"]
    assert [s["title"] for s in cad] == ["Onshape standards"]
    # The guide is read in order, so its chapters come back in order.
    assert [p["title"] for p in cad[0]["pages"]][:2] == ["Why we standardize", "Naming parts"]
    # Every card has something to click.
    assert all(s["pages"] for s in sections)


def test_the_starter_library_is_written_once_not_on_every_boot(client):
    """Every TestClient here runs the app's startup again, which is exactly
    what a deploy or restart does. Seeding on every boot would put a second
    Welding card on the page each time -- or bring back a section a lead had
    deliberately deleted."""
    with TestClient(app):
        pass
    with TestClient(app) as again:
        from app.database import SessionLocal
        from app.models import LearnSection

        with SessionLocal() as db:
            welding = db.query(LearnSection).filter(LearnSection.title == "Welding").count()
        assert welding == 1
        assert again.get("/api/health").status_code == 200


def _fresh_db():
    """An empty in-memory database with every table, for start-up logic that
    has to be tested from a clean slate rather than the shared test file."""
    import sqlalchemy
    from sqlalchemy.orm import sessionmaker

    from app.models import Base as ModelBase

    engine = sqlalchemy.create_engine("sqlite://")
    ModelBase.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_a_boot_that_died_before_seeding_still_seeds_next_time():
    """The bug this design exists for: a start-up created the Learn tables,
    then failed (missing Cloudflare settings) before seeding. Keying the seed
    on "the table is new" would have left that library empty forever. Tables
    present with no marker is exactly that state -- it must still seed."""
    from app.learn_seed import seed_learn_library_once

    with _fresh_db() as db:
        assert seed_learn_library_once(db) == 5
        assert seed_learn_library_once(db) == 0


def test_emptying_the_library_does_not_bring_the_starter_back():
    from app.learn_seed import seed_learn_library_once
    from app.models import LearnSection

    with _fresh_db() as db:
        seed_learn_library_once(db)
        for section in db.query(LearnSection).all():
            db.delete(section)
        db.commit()

        assert seed_learn_library_once(db) == 0
        assert db.query(LearnSection).count() == 0


def test_a_library_the_team_started_is_never_mixed_with_the_starter():
    from app.learn_seed import SEEDED_KEY, seed_learn_library_once
    from app.models import AppMeta, LearnSection

    with _fresh_db() as db:
        db.add(LearnSection(title="Our own Brakes page", group="library", icon="book"))
        db.commit()

        assert seed_learn_library_once(db) == 0
        assert [s.title for s in db.query(LearnSection)] == ["Our own Brakes page"]
        assert db.get(AppMeta, SEEDED_KEY) is not None


def test_the_library_outlines_say_they_are_outlines(client):
    """The topic pages are scaffolds, not the team's procedures. A page that
    reads as authoritative but was invented is worse than an empty one."""
    welding = _section_named(client, "Welding")
    first = client.get(f"/api/learn/pages/{welding['pages'][0]['id']}").json()
    assert "Starter outline" in first["body"]


def test_a_page_save_records_who_and_bumps_the_version(client):
    section = _learn_section(client, "Brakes test")
    page = _learn_page(client, section["id"], "Bleeding")
    assert page["version"] == 1

    saved = client.patch(f"/api/learn/pages/{page['id']}", json={
        "body": "## Steps\n\n1. Fill the reservoir", "base_version": 1,
    })
    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert body["version"] == 2
    assert body["updated_by_name"] == "Test Admin"
    assert body["body"].startswith("## Steps")


def test_saving_over_someone_elses_newer_edit_is_refused(client):
    """Two people open the welding page; one saves. The second save must not
    silently wipe the first -- it gets a 409 and the page keeps the first."""
    section = _learn_section(client, "Conflict test")
    page = _learn_page(client, section["id"], "Shared page")

    first = client.patch(f"/api/learn/pages/{page['id']}",
                         json={"body": "first edit", "base_version": 1})
    assert first.status_code == 200

    stale = client.patch(f"/api/learn/pages/{page['id']}",
                         json={"body": "second edit, started from v1", "base_version": 1})
    assert stale.status_code == 409
    assert "NOT saved" in stale.json()["detail"]
    assert client.get(f"/api/learn/pages/{page['id']}").json()["body"] == "first edit"


def test_members_can_read_learn_but_not_change_any_of_it(anon, client):
    """Learn is the team's guidance, so it is the one section where a member's
    only access is reading -- no editing a page, no new picture on a card, no
    reordering. Every write route is tried as a real non-admin."""
    section = _learn_section(client, "Read-only test", summary="Lead's words")
    page = _learn_page(client, section["id"], "Guidance")
    written = client.patch(f"/api/learn/pages/{page['id']}",
                           json={"body": "How we do it.", "base_version": 1}).json()
    picture = _learn_image(client, section["id"], b"lead's picture", page_id=page["id"]).json()

    with cloudflare_mode():
        h = {JWT_HEADER: make_token("reader@school.edu")}

        # Reading: all of it.
        assert anon.get("/api/learn", headers=h).status_code == 200
        assert anon.get(f"/api/learn/pages/{page['id']}", headers=h).json()["body"] == "How we do it."
        assert anon.get(picture["url"], headers=h).status_code == 200

        # Changing: none of it -- all eleven write routes.
        sid, pid = section["id"], page["id"]
        attempts = {
            "edit page": anon.patch(f"/api/learn/pages/{pid}", headers=h,
                                    json={"body": "my version", "base_version": written["version"]}),
            "edit section": anon.patch(f"/api/learn/sections/{sid}", headers=h,
                                       json={"summary": "my words"}),
            "move page": anon.post(f"/api/learn/pages/{pid}/move", headers=h,
                                   json={"direction": "down"}),
            "move section": anon.post(f"/api/learn/sections/{sid}/move", headers=h,
                                      json={"direction": "down"}),
            "upload picture": _learn_image(anon, sid, b"member picture", page_id=pid, headers=h),
            "set card picture": anon.put(f"/api/learn/sections/{sid}/image", headers=h,
                                         files={"file": ("card.png", b"member card")}),
            "clear card picture": anon.delete(f"/api/learn/sections/{sid}/image", headers=h),
            "add section": anon.post("/api/learn/sections", headers=h, json={"title": "Mine"}),
            "add page": anon.post("/api/learn/pages", headers=h,
                                  json={"section_id": sid, "title": "Mine"}),
            "delete page": anon.delete(f"/api/learn/pages/{pid}", headers=h),
            "delete section": anon.delete(f"/api/learn/sections/{sid}", headers=h),
        }
        allowed = {name: r.status_code for name, r in attempts.items() if r.status_code != 403}
        assert not allowed, f"a member got through: {allowed}"

    # ...and nothing underneath moved.
    after = client.get(f"/api/learn/pages/{page['id']}").json()
    assert after["body"] == "How we do it."
    assert after["version"] == written["version"]
    assert _section_named(client, "Read-only test")["summary"] == "Lead's words"


def test_no_learn_write_is_on_the_member_allowlist():
    """The structural half of the rule above. Putting a Learn route into
    security.MEMBER_WRITABLE would quietly open it to every member; this fails
    the moment anyone does, whatever the route."""
    from app.routers import learn
    from app.security import MEMBER_WRITABLE

    writes = {
        (method, route.path)
        for route in learn.router.routes
        for method in route.methods
        if method not in ("GET", "HEAD")
    }
    # 6 for sections, 4 for pages, 1 for pictures. If this count changes, a
    # route was added or removed -- make sure the test above tries it.
    assert len(writes) == 11, sorted(writes)
    assert not writes & MEMBER_WRITABLE


def test_moving_a_page_reorders_its_chapters(client):
    section = _learn_section(client, "Order test")
    a = _learn_page(client, section["id"], "A")
    _learn_page(client, section["id"], "B")
    c = _learn_page(client, section["id"], "C")

    r = client.post(f"/api/learn/pages/{c['id']}/move", json={"direction": "up"})
    assert r.status_code == 200
    mine = next(s for s in r.json()["sections"] if s["id"] == section["id"])
    assert [p["title"] for p in mine["pages"]] == ["A", "C", "B"]
    assert [p["position"] for p in mine["pages"]] == [0, 1, 2]

    # Already at the top: a no-op, not an error.
    r = client.post(f"/api/learn/pages/{a['id']}/move", json={"direction": "up"})
    assert r.status_code == 200
    mine = next(s for s in r.json()["sections"] if s["id"] == section["id"])
    assert [p["title"] for p in mine["pages"]] == ["A", "C", "B"]


@pytest.mark.parametrize("bad_url", [
    "javascript:alert(document.cookie)",
    "data:text/html,<script>alert(1)</script>",
    "cad.onshape.com/documents/abc",
])
def test_a_cad_reference_must_be_an_http_link(client, bad_url):
    """References render as real hrefs, so the same rule as shop links."""
    section = _learn_section(client, f"Ref URL test {bad_url[:12]}")
    page = _learn_page(client, section["id"], "Refs")
    r = client.patch(f"/api/learn/pages/{page['id']}", json={
        "references": [{"title": "Bad", "url": bad_url}],
    })
    assert r.status_code == 422
    assert client.get(f"/api/learn/pages/{page['id']}").json()["references"] == []


def test_a_reference_picture_has_to_come_from_the_same_section(client):
    """Otherwise deleting the other section would leave a broken picture."""
    home = _learn_section(client, "Ref image home")
    other = _learn_section(client, "Ref image other")
    page = _learn_page(client, home["id"], "Refs")
    theirs = _learn_image(client, other["id"], b"other section picture").json()
    ours = _learn_image(client, home["id"], b"home section picture").json()

    ref = {"title": "Rack mount", "url": "https://cad.onshape.com/documents/x"}
    wrong = client.patch(f"/api/learn/pages/{page['id']}",
                         json={"references": [{**ref, "image_id": theirs["id"]}]})
    assert wrong.status_code == 400

    right = client.patch(f"/api/learn/pages/{page['id']}",
                         json={"references": [{**ref, "image_id": ours["id"]}]})
    assert right.status_code == 200, right.text
    assert right.json()["references"][0]["image_id"] == ours["id"]


@pytest.mark.parametrize("filename", ["diagram.svg", "notes.html", "tube.pdf", "noext"])
def test_learn_only_takes_pictures(client, filename):
    """Served inline on this origin, so SVG and HTML -- which can carry script
    -- are refused, and the bytes are never written."""
    import hashlib

    from app import storage

    data = f"not a picture {filename}".encode()
    section = _learn_section(client, f"Picture check {filename}")
    r = _learn_image(client, section["id"], data, filename=filename)
    assert r.status_code == 415
    assert not storage.blob_path(hashlib.sha256(data).hexdigest()).exists()


def test_a_learn_picture_is_served_inline_and_cached(client):
    section = _learn_section(client, "Serve check")
    made = _learn_image(client, section["id"], b"\x89PNG served bytes", filename="a.png").json()
    assert made["url"] == f"/api/learn/images/{made['id']}"

    r = client.get(made["url"])
    assert r.status_code == 200
    assert r.content == b"\x89PNG served bytes"
    assert r.headers["content-type"] == "image/png"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert "immutable" in r.headers["cache-control"]
    assert "private" in r.headers["cache-control"]


def test_a_new_card_picture_frees_the_old_one(client):
    import hashlib

    from app import storage

    section = _learn_section(client, "Card swap")
    one = client.put(f"/api/learn/sections/{section['id']}/image",
                     files={"file": ("one.png", b"card picture one")})
    assert one.status_code == 200
    assert one.json()["image_url"]

    two = client.put(f"/api/learn/sections/{section['id']}/image",
                     files={"file": ("two.jpg", b"card picture two")})
    assert two.status_code == 200
    assert two.json()["image_url"] != one.json()["image_url"]
    assert not storage.blob_path(hashlib.sha256(b"card picture one").hexdigest()).exists()
    assert storage.blob_path(hashlib.sha256(b"card picture two").hexdigest()).exists()

    cleared = client.delete(f"/api/learn/sections/{section['id']}/image")
    assert cleared.json()["image_url"] is None
    assert not storage.blob_path(hashlib.sha256(b"card picture two").hexdigest()).exists()


def test_deleting_a_section_takes_its_pages_and_pictures(client):
    import hashlib

    from app import storage

    section = _learn_section(client, "Doomed section")
    page = _learn_page(client, section["id"], "Doomed page")
    _learn_image(client, section["id"], b"doomed picture", page_id=page["id"])

    assert client.delete(f"/api/learn/sections/{section['id']}").status_code == 204
    assert client.get(f"/api/learn/pages/{page['id']}").status_code == 404
    assert all(s["id"] != section["id"] for s in _library(client))
    assert not storage.blob_path(hashlib.sha256(b"doomed picture").hexdigest()).exists()


def test_a_learn_picture_shared_with_a_drawing_survives(client, project):
    """The content-addressed trap again, across a third table: the same file
    as a shop drawing and a Learn picture is ONE blob. Deleting the Learn page
    must not take the drawing's bytes with it."""
    import hashlib

    from app import storage

    shared = b"\x89PNG one file, two homes"
    sha = hashlib.sha256(shared).hexdigest()

    part = _part(client, project["id"], "Shared picture part")
    assert _put_drawing(client, part["id"], "shared.png", shared, "image/png").status_code == 200

    section = _learn_section(client, "Shared picture section")
    page = _learn_page(client, section["id"], "Shared picture page")
    assert _learn_image(client, section["id"], shared, page_id=page["id"]).status_code == 201

    assert client.delete(f"/api/learn/pages/{page['id']}").status_code == 204
    assert storage.blob_path(sha).exists(), "deleting a Learn page deleted a shop drawing"
    assert client.get(f"/api/mfg-parts/{part['id']}/drawing").status_code == 200


# --- Orders --------------------------------------------------------------------

def _order(c, project_id, item, headers=None, **kw):
    r = c.post("/api/purchase-requests", headers=headers or {},
               json={"project_id": project_id, "item": item, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def _set(c, request_id, headers=None, **fields):
    return c.patch(f"/api/purchase-requests/{request_id}", headers=headers or {}, json=fields)


def test_anyone_can_ask_for_something_to_be_bought(anon, client, project):
    """The whole point of the list: a member submits, and the request records
    who asked from the signed-in identity, not from anything they typed."""
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("asker@school.edu")}
        me = anon.get("/api/auth/me", headers=h).json()
        made = _order(anon, project["id"], "Brake line fittings", headers=h,
                      vendor="McMaster-Carr", part_number="5182K113",
                      quantity=4, unit_cost_cents=1275,
                      url="https://www.mcmaster.com/5182K113/",
                      notes="Front brake lines", needed_by="2026-11-07")

    assert made["status"] == "requested"
    assert made["requested_by_id"] == me["id"]
    assert made["total_cents"] == 4 * 1275
    assert made["needed_by"] == "2026-11-07"
    assert [e["status"] for e in made["history"]] == ["requested"]
    assert made["history"][0]["by_name"] == me["name"]


def test_a_member_cannot_slip_in_an_approved_request(anon, project):
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("sneaky@school.edu")}
        for extra in ({"status": "approved"}, {"status": "ordered"},
                      {"tracking_number": "1Z999"}, {"order_number": "PO-1"}):
            r = anon.post("/api/purchase-requests", headers=h,
                          json={"project_id": project["id"], "item": "Shocks", **extra})
            assert r.status_code == 403, extra


def test_you_can_change_your_own_request_until_a_lead_acts_on_it(anon, client, project):
    with cloudflare_mode():
        mine = {JWT_HEADER: make_token("owner@school.edu")}
        theirs = {JWT_HEADER: make_token("bystander@school.edu")}
        made = _order(anon, project["id"], "Rod ends", headers=mine, quantity=8)

        fixed = _set(anon, made["id"], mine, quantity=10, unit_cost_cents=899)
        assert fixed.status_code == 200, fixed.text
        assert fixed.json()["total_cents"] == 8990

        assert _set(anon, made["id"], theirs, quantity=1).status_code == 403

    assert _set(client, made["id"], status="approved").status_code == 200

    with cloudflare_mode():
        locked = _set(anon, made["id"], mine, quantity=99)
        assert locked.status_code == 403
        assert "locked" in locked.json()["detail"]


def test_approving_and_ordering_are_for_leads(anon, client, project):
    made = _order(client, project["id"], "CVT belt")
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("eager@school.edu")}
        for status in ("approved", "denied", "ordered", "shipped"):
            r = _set(anon, made["id"], h, status=status)
            assert r.status_code == 403, status
        assert _set(anon, made["id"], h, tracking_number="1Z123").status_code == 403
        assert anon.delete(f"/api/purchase-requests/{made['id']}", headers=h).status_code == 403


def test_whoever_opens_the_box_can_mark_it_received(anon, client, project):
    """Not just the requester and not just a lead: anyone on the team."""
    made = _order(client, project["id"], "Bearings")
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("unboxer@school.edu")}
        # Not before it has been ordered -- "received" on a bare request
        # would skip the lead's approval entirely.
        assert _set(anon, made["id"], h, status="received").status_code == 403

    assert _set(client, made["id"], status="approved").status_code == 200
    assert _set(client, made["id"], status="ordered", order_number="PO-77").status_code == 200

    with cloudflare_mode():
        got = _set(anon, made["id"], h, status="received")
        assert got.status_code == 200, got.text
        assert got.json()["status"] == "received"


def test_you_can_withdraw_your_own_request(anon, client, project):
    with cloudflare_mode():
        mine = {JWT_HEADER: make_token("withdrawer@school.edu")}
        other = {JWT_HEADER: make_token("not-the-owner@school.edu")}
        made = _order(anon, project["id"], "Spare tie rods", headers=mine)
        assert _set(anon, made["id"], other, status="cancelled").status_code == 403
        done = _set(anon, made["id"], mine, status="cancelled")
        assert done.status_code == 200
        assert done.json()["status"] == "cancelled"


def test_every_status_change_is_written_down(client, project):
    made = _order(client, project["id"], "Fox shocks", quantity=2, unit_cost_cents=45000)
    for status in ("approved", "ordered", "shipped", "received"):
        assert _set(client, made["id"], status=status).status_code == 200
    # Setting the same status again is not a new event.
    final = _set(client, made["id"], status="received").json()

    assert [e["status"] for e in final["history"]] == [
        "requested", "approved", "ordered", "shipped", "received",
    ]
    assert all(e["by_name"] == "Test Admin" for e in final["history"])
    stamps = [e["at"] for e in final["history"]]
    assert stamps == sorted(stamps)


def test_an_unpriced_request_has_no_total_rather_than_zero(client, project):
    """$0 would quietly make the budget look healthier than it is."""
    made = _order(client, project["id"], "Something, price unknown", quantity=3)
    assert made["unit_cost_cents"] is None
    assert made["total_cents"] is None


@pytest.mark.parametrize("bad", [
    {"url": "javascript:alert(1)"},
    {"quantity": 0},
    {"unit_cost_cents": -5},
    {"status": "lost_in_the_mail"},
    {"item": "   "},
])
def test_a_bogus_request_is_refused(client, project, bad):
    r = client.post("/api/purchase-requests",
                    json={"project_id": project["id"], "item": "Thing", **bad})
    assert r.status_code == 422, bad


def test_a_blank_link_means_no_link(client, project):
    made = _order(client, project["id"], "No link", url="   ", vendor="")
    assert made["url"] is None
    assert made["vendor"] is None


def test_clearing_a_required_field_is_a_422_not_a_crash(client, project):
    made = _order(client, project["id"], "Required check")
    assert _set(client, made["id"], item=None).status_code == 422
    assert _set(client, made["id"], quantity=None).status_code == 422


def test_deleting_a_project_takes_its_orders_with_it(client):
    doomed = client.post("/api/projects", json={"name": "Doomed orders car", "template": "blank"})
    pid = doomed.json()["id"]
    made = _order(client, pid, "Orphan-to-be")
    assert client.delete(f"/api/projects/{pid}").status_code == 204

    from app.database import SessionLocal
    from app.models import PurchaseRequest

    with SessionLocal() as db:
        assert db.get(PurchaseRequest, made["id"]) is None


# --- Resources -----------------------------------------------------------------

def _resource(c, title, headers=None, **kw):
    r = c.post("/api/resources", headers=headers or {}, json={"title": title, **kw})
    assert r.status_code == 201, r.text
    return r.json()


def test_anyone_can_add_a_resource_and_it_says_who_found_it(anon):
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("researcher@school.edu")}
        me = anon.get("/api/auth/me", headers=h).json()
        made = _resource(anon, "Team 42 design report", headers=h,
                         url="https://example.edu/baja-report.pdf", kind="report",
                         topic="Suspension", notes="Good **A-arm** analysis.")
        listed = anon.get("/api/resources", headers=h).json()

    assert made["added_by_id"] == me["id"]
    assert made["added_by_name"] == me["name"]
    assert made["kind"] == "report"
    assert any(r["id"] == made["id"] for r in listed)


def test_you_can_change_what_you_found_but_not_a_teammates(anon, client):
    """Adding is everyone's job; editing or removing someone else's find is
    not. Their own, or any if you are an admin."""
    with cloudflare_mode():
        finder = {JWT_HEADER: make_token("finder@school.edu")}
        other = {JWT_HEADER: make_token("someone-else@school.edu")}
        mine = _resource(anon, "CVT tuning paper", headers=finder)
        rid = mine["id"]

        for attempt in (
            anon.patch(f"/api/resources/{rid}", headers=other, json={"title": "Mine now"}),
            anon.delete(f"/api/resources/{rid}", headers=other),
            anon.put(f"/api/resources/{rid}/file", headers=other, files={"file": ("x.pdf", b"%PDF other")}),
            anon.delete(f"/api/resources/{rid}/file", headers=other),
        ):
            assert attempt.status_code == 403, attempt.text

        fixed = anon.patch(f"/api/resources/{rid}", headers=finder, json={"topic": "Drivetrain"})
        assert fixed.status_code == 200 and fixed.json()["topic"] == "Drivetrain"

        theirs = _resource(anon, "Somebody else's find", headers=other)

    # An admin can tidy up anyone's.
    assert client.patch(f"/api/resources/{theirs['id']}", json={"kind": "video"}).status_code == 200
    assert client.delete(f"/api/resources/{theirs['id']}").status_code == 204

    with cloudflare_mode():
        assert anon.delete(f"/api/resources/{rid}", headers=finder).status_code == 204


@pytest.mark.parametrize("bad", [
    {"url": "javascript:alert(1)"},
    {"url": "data:text/html,hi"},
    {"kind": "rumour"},
    {"title": "   "},
])
def test_a_bogus_resource_is_refused(client, bad):
    r = client.post("/api/resources", json={"title": "Thing", **bad})
    assert r.status_code == 422, bad


def test_a_blank_resource_link_means_no_link(client):
    made = _resource(client, "No link", url="  ", topic="")
    assert made["url"] is None
    assert made["topic"] is None


def test_a_resource_file_is_shown_downloaded_and_freed(client):
    import hashlib

    from app import storage

    data = b"%PDF resource file bytes"
    sha = hashlib.sha256(data).hexdigest()
    made = _resource(client, "With a PDF")
    up = client.put(f"/api/resources/{made['id']}/file", files={"file": ("paper.pdf", data)})
    assert up.status_code == 200, up.text
    assert up.json()["has_file"] is True
    assert "file_sha256" not in up.json()

    shown = client.get(f"/api/resources/{made['id']}/file")
    assert shown.headers["content-type"] == "application/pdf"
    assert shown.headers["content-disposition"].startswith("inline")
    assert shown.headers["x-content-type-options"] == "nosniff"
    saved = client.get(f"/api/resources/{made['id']}/file?download=1")
    assert saved.headers["content-disposition"].startswith("attachment")

    assert client.delete(f"/api/resources/{made['id']}").status_code == 204
    assert not storage.blob_path(sha).exists()


def test_a_resource_file_shared_with_a_drawing_survives(client, project):
    """The content-addressed trap, across a fourth table."""
    import hashlib

    from app import storage

    shared = b"%PDF one paper, two homes"
    part = _part(client, project["id"], "Shared with a resource")
    assert _put_drawing(client, part["id"], "shared.pdf", shared).status_code == 200
    made = _resource(client, "Same PDF as a drawing")
    client.put(f"/api/resources/{made['id']}/file", files={"file": ("shared.pdf", shared)})

    assert client.delete(f"/api/resources/{made['id']}").status_code == 204
    assert storage.blob_path(hashlib.sha256(shared).hexdigest()).exists()
    assert client.get(f"/api/mfg-parts/{part['id']}/drawing").status_code == 200


# --- the doomsday countdown -----------------------------------------------------

def test_the_countdown_is_unset_until_an_admin_sets_it(client):
    from datetime import datetime, timezone

    client.delete("/api/countdown")
    assert client.get("/api/countdown").json() == {"label": None, "at": None, "doomsday": False}

    # Set in Pacific time; stored and returned as the same instant in UTC.
    r = client.put("/api/countdown", json={"label": "Competition", "at": "2027-05-01T08:00:00-07:00"})
    assert r.status_code == 200, r.text
    got = client.get("/api/countdown").json()
    assert got["label"] == "Competition"
    assert datetime.fromisoformat(got["at"]) == datetime(2027, 5, 1, 15, 0, tzinfo=timezone.utc)

    assert client.delete("/api/countdown").status_code == 204
    assert client.get("/api/countdown").json() == {"label": None, "at": None, "doomsday": False}


def test_doomsday_is_how_one_site_shows_the_timer_not_a_default(client, monkeypatch):
    """The big red Doomsday clock is this team's taste, switched on in its
    fly.toml. Anyone else running the app gets the plain countdown."""
    client.put("/api/countdown", json={"label": "Competition", "at": "2027-05-01T15:00:00Z"})
    assert client.get("/api/countdown").json()["doomsday"] is False

    monkeypatch.setattr(settings, "doomsday", True)
    got = client.get("/api/countdown").json()
    assert got["doomsday"] is True
    assert got["label"] == "Competition"  # still said in the tooltip

    # It is the site's look, so it holds with no date set too -- the admin's
    # "set it" button should already say Doomsday.
    client.delete("/api/countdown")
    assert client.get("/api/countdown").json() == {"label": None, "at": None, "doomsday": True}


def test_a_member_cannot_move_the_doomsday_clock(anon, client):
    client.put("/api/countdown", json={"label": "Competition", "at": "2027-05-01T15:00:00Z"})
    with cloudflare_mode():
        h = {JWT_HEADER: make_token("clock-watcher@school.edu")}
        assert anon.get("/api/countdown", headers=h).json()["label"] == "Competition"
        assert anon.put("/api/countdown", headers=h,
                        json={"label": "Later", "at": "2028-01-01T00:00:00Z"}).status_code == 403
        assert anon.delete("/api/countdown", headers=h).status_code == 403
    assert client.get("/api/countdown").json()["label"] == "Competition"
    client.delete("/api/countdown")


def test_a_countdown_without_a_timezone_is_refused(client):
    """"8 am" with no zone would be read as 8 am UTC -- the wrong second for
    everyone counting down to it."""
    r = client.put("/api/countdown", json={"label": "Competition", "at": "2027-05-01T08:00:00"})
    assert r.status_code == 422


def test_timestamps_people_see_carry_their_timezone(client, project):
    """SQLite returns timestamps with no zone. Sent like that, a browser reads
    them as local time, and in the evening "added today" showed as tomorrow.
    Every timestamp the UI puts in front of a person must say it is UTC."""
    from datetime import datetime

    def zoned(value):
        return datetime.fromisoformat(value).utcoffset() is not None

    resource = _resource(client, "Zone check")
    assert zoned(resource["created_at"]), resource["created_at"]
    assert zoned(client.get("/api/resources").json()[0]["updated_at"])

    order = _order(client, project["id"], "Zone check")
    assert zoned(order["created_at"]) and zoned(order["updated_at"])

    section = _learn_section(client, "Zone check section")
    page = _learn_page(client, section["id"], "Zone check page")
    saved = client.patch(f"/api/learn/pages/{page['id']}", json={"body": "x", "base_version": 1}).json()
    assert zoned(saved["updated_at"]), saved["updated_at"]
    assert zoned(client.get(f"/api/learn/pages/{page['id']}").json()["updated_at"])


def test_a_mangled_countdown_shows_as_unset_rather_than_breaking_the_page(client):
    from app.database import SessionLocal
    from app.models import AppMeta

    with SessionLocal() as db:
        db.merge(AppMeta(key="countdown", value="{not json"))
        db.commit()
    assert client.get("/api/countdown").json() == {"label": None, "at": None, "doomsday": False}
    client.delete("/api/countdown")
