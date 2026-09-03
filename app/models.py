"""Database models.

HIERARCHY STRATEGY -- adjacency list + materialized path (see docs/SCHEMA.md)
----------------------------------------------------------------------------
Node.parent_id is the source of truth: a real foreign key, so the database itself
guarantees you cannot orphan a part, and "add a child" is a single INSERT.

Node.path is a denormalized cache of the ancestor chain, e.g. '/1/7/23/', always
with a leading and trailing slash and always ending in the node's own id. It buys
three things that adjacency-list-alone makes painful:

  * whole subtree in one indexed query:  WHERE path LIKE '/1/7/%'
  * ancestors with no query at all:      parse the ids straight out of the string
  * cascading tags (a tag on a branch)   resolved by prefix match, instead of
                                         copying the tag onto every descendant

The trailing slash is what makes the LIKE safe: '/1/7/%' cannot match '/1/70/'.

We deliberately did NOT use nested sets (every insert renumbers half the table,
and a BOM changes daily) or a closure table (correct, but 3-4x the rows and more
moving parts for a team that hands off every year).
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --- Controlled vocabularies -------------------------------------------------
# Stored as plain strings and validated at the API boundary (app/schemas.py)
# rather than as DB enums. A student team WILL invent a new status mid-season;
# this way that is a one-line change instead of a database migration.

NODE_TYPES = ("vehicle", "subsystem", "assembly", "part")

STATUSES = (
    "concept",
    "design",
    "in_review",
    "ordered",
    "in_fabrication",
    "assembled",
    "not_installed",
    "installed",
)

# Statuses that used to exist, and what a node carrying one becomes. Removing a
# value from STATUSES is not enough on its own: the API validates status against
# a Literal on the way OUT as well as in, so a single surviving row would turn
# the whole tree endpoint into a 500. app/migrate.py drains these on boot and
# keeps the old value in Node.extra["former_status"], because "this was
# scrapped" is real information and a vocabulary change should not silently bin
# it. Every target is a status that understates progress rather than
# overstating it -- a part that looks less finished than it is gets noticed and
# corrected; one that looks more finished does not.
RETIRED_STATUSES = {
    "released": "in_review",
    "needs_rework": "design",
    "scrapped": "concept",
}

SOURCING = ("make", "buy", "na")

ATTACHMENT_KINDS = ("datasheet", "cad", "drawing", "pcb", "firmware", "analysis", "photo", "other")


class Member(Base):
    """A person on the team: both the assignee list and the login account.

    One table for both on purpose. The alternative -- a separate users table --
    means every graduating senior has to be removed from two places, and the
    two lists drift. Here, deactivating someone removes their access and keeps
    their name on the parts they designed.

    A member with no password_hash simply cannot log in, which is exactly what
    you want for people you want to assign work to but who never sign in.
    """

    __tablename__ = "members"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    email: Mapped[str | None] = mapped_column(String(200), unique=True)
    subteam: Mapped[str | None] = mapped_column(String(80))  # Suspension, Drivetrain, Electrical
    role: Mapped[str | None] = mapped_column(String(80))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # --- login ---------------------------------------------------------------
    # Format: scrypt$n$r$p$salt_hex$key_hex -- the parameters travel with the
    # hash so they can be raised later without invalidating existing passwords.
    password_hash: Mapped[str | None] = mapped_column(String(255))
    # Admins manage the roster. Everyone else just uses the app.
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # False means the name was derived from an email local part rather than
    # typed by the person. Under Cloudflare Access a new member arrives as
    # whatever their address happens to be -- often a school ID like W1234567 --
    # so the app asks them once who they actually are.
    name_confirmed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="member", cascade="all, delete-orphan", passive_deletes=True
    )

    @property
    def has_password(self) -> bool:
        """Whether this person can sign in. The hash itself never leaves here."""
        return bool(self.password_hash)


class Session(Base):
    """A logged-in browser.

    Sessions live in the database rather than in a signed cookie so they can be
    revoked: logging out, or deactivating a member, ends access immediately
    instead of waiting for a token to expire.

    Only the SHA-256 of the token is stored. The raw token exists in the user's
    cookie and nowhere else, so a leaked database does not hand over live
    sessions.
    """

    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    member_id: Mapped[int] = mapped_column(
        ForeignKey("members.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))

    member: Mapped["Member"] = relationship(back_populates="sessions")


class Project(Base):
    """One tree. Usually one competition year's car, but also useful for a test
    rig, the trailer, or a spares inventory."""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    season: Mapped[str | None] = mapped_column(String(40))  # "2026"
    description: Mapped[str | None] = mapped_column(Text)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    nodes: Mapped[list["Node"]] = relationship(
        back_populates="project", cascade="all, delete-orphan", passive_deletes=True
    )


class Node(Base):
    """A single element of the tree: the vehicle, a subsystem, an assembly, a part."""

    __tablename__ = "nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"))

    # --- hierarchy cache (maintained by app/tree.py, never edited by hand) ---
    path: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    depth: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # sibling order

    # --- metadata ------------------------------------------------------------
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    node_type: Mapped[str] = mapped_column(String(40), nullable=False, default="part")
    part_number: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="concept")
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    description: Mapped[str | None] = mapped_column(Text)

    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    sourcing: Mapped[str] = mapped_column(String(20), nullable=False, default="na")
    material: Mapped[str | None] = mapped_column(String(120))
    mass_g: Mapped[float | None] = mapped_column(Float)
    cost_cents: Mapped[int | None] = mapped_column(Integer)  # integers only; never float money
    vendor: Mapped[str | None] = mapped_column(String(160))
    lead_time_days: Mapped[int | None] = mapped_column(Integer)

    # Escape hatch for whatever this year's team decides it needs (torque spec,
    # heat treat, inspection date) without a migration.
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship(back_populates="nodes")
    parent: Mapped["Node | None"] = relationship(remote_side=[id], back_populates="children")
    children: Mapped[list["Node"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Node.position",
    )
    assignee: Mapped[Member | None] = relationship()
    tag_links: Mapped[list["NodeTag"]] = relationship(
        back_populates="node", cascade="all, delete-orphan", passive_deletes=True
    )
    attachments: Mapped[list["Attachment"]] = relationship(
        back_populates="node", cascade="all, delete-orphan", passive_deletes=True
    )

    __table_args__ = (
        # The workhorse index: every subtree query is a prefix scan on path.
        Index("ix_nodes_project_path", "project_id", "path"),
        Index("ix_nodes_parent", "parent_id"),
        Index("ix_nodes_status", "project_id", "status"),
        Index("ix_nodes_part_number", "part_number"),
    )

    # --- helpers -------------------------------------------------------------
    @property
    def ancestor_ids(self) -> list[int]:
        """Ancestor ids, root first, with no database round trip -- they are
        already sitting in the path string."""
        parts = [p for p in self.path.split("/") if p]
        return [int(p) for p in parts[:-1]]  # last element is this node's own id

    @property
    def subtree_pattern(self) -> str:
        """LIKE pattern selecting this node and everything beneath it."""
        return f"{self.path}%"


class Tag(Base):
    """A label. Shared across every project so "Pending Machining" means the same
    thing on the 2026 car as it did on the 2025 one."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(String(9), nullable=False, default="#ff6b35")
    category: Mapped[str | None] = mapped_column(String(60))  # discipline / workflow / sourcing
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node_links: Mapped[list["NodeTag"]] = relationship(
        back_populates="tag", cascade="all, delete-orphan", passive_deletes=True
    )


class NodeTag(Base):
    """Many-to-many between nodes and tags, with one extra bit that does a lot of work.

    cascade=True means "this tag applies to this node AND everything under it".
    That is how you tag a whole branch. We resolve it at read time by prefix-matching
    paths rather than copying the tag onto each descendant -- so a part added to the
    branch next week inherits it automatically, and un-tagging is one DELETE.
    """

    __tablename__ = "node_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)
    tag_id: Mapped[int] = mapped_column(ForeignKey("tags.id", ondelete="CASCADE"), nullable=False)
    cascade: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship(back_populates="tag_links")
    tag: Mapped[Tag] = relationship(back_populates="node_links")

    __table_args__ = (
        UniqueConstraint("node_id", "tag_id", name="uq_node_tag"),
        Index("ix_node_tags_tag", "tag_id"),
    )


class Attachment(Base):
    """A file attached to a node.

    Bytes live on disk under storage/blobs/<aa>/<bb>/<sha256>, addressed by content
    hash: uploading the same CAD file to five nodes stores it once. This row is the
    metadata. Re-uploading the same filename to the same node creates a new version
    rather than overwriting -- you can always get last week's STEP file back.
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    node_id: Mapped[int] = mapped_column(ForeignKey("nodes.id", ondelete="CASCADE"), nullable=False)

    filename: Mapped[str] = mapped_column(String(255), nullable=False)  # sanitized display name
    content_type: Mapped[str] = mapped_column(
        String(120), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    kind: Mapped[str] = mapped_column(String(40), nullable=False, default="other")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notes: Mapped[str | None] = mapped_column(Text)

    uploaded_by_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    node: Mapped[Node] = relationship(back_populates="attachments")
    uploaded_by: Mapped[Member | None] = relationship()

    __table_args__ = (
        UniqueConstraint("node_id", "filename", "version", name="uq_attachment_version"),
        Index("ix_attachments_node_current", "node_id", "is_current"),
    )
