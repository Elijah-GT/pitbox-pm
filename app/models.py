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

from datetime import date, datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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

# How hard a timeline goal's date is.
#
# "sae" is not a severity, it is an authority: Baja SAE sets those dates and
# the team cannot move them, so they are called out separately from anything
# the team decided for itself. Everything else is the team's own judgement.
GOAL_PRIORITIES = ("sae", "critical", "normal", "low")

# What kind of work a goal is. Deliberately short -- "design" and
# "manufacturing" are the two halves of the season the team actually splits on,
# and "other" catches the paperwork and the ordering.
GOAL_KINDS = ("design", "manufacturing", "other")

# Where a shop-floor part has got to. Three states on purpose: a cut list is a
# wall of tape labels, not a workflow engine.
MFG_STATUSES = ("todo", "in_progress", "done")

# The two halves of the Learn page. "library" is topics you dip into --
# drivetrain, suspension, welding. "cad" is how the team models the car, read
# more like a guide. Same data either way; this only decides which heading a
# section sits under.
LEARN_GROUPS = ("library", "cad")

# Line art shown on a section card until someone uploads a real render. A fixed
# set rather than an upload so a brand-new section never looks broken.
LEARN_ICONS = ("gear", "spring", "wheel", "weld", "cube", "book")

# The life of a purchase request. The first five are the happy path in order;
# the last two are the ways a request ends without anything being bought --
# "denied" when a lead says no, "cancelled" when the requester withdraws it.
ORDER_STATUSES = (
    "requested",
    "approved",
    "ordered",
    "shipped",
    "received",
    "denied",
    "cancelled",
)
# Statuses where the request is finished with, one way or the other. Anything
# else is still somebody's job.
ORDER_CLOSED = frozenset({"received", "denied", "cancelled"})


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


class MfgPart(Base):
    """A part to cut, machine or fabricate: one row of the shop's cut list.

    NOT a Node, and deliberately flat. The tree answers "what is the car made
    of"; this answers "what do we have to make this week", and they are not the
    same list -- you cut three tube lengths the tree models as one A-arm, and
    you cut jigs and fixtures that are not part of the car at all. Forcing
    those into the assembly tree would corrupt the BOM and the rollups.

    `name` is meant to match the part's name in Onshape exactly. That string IS
    the join between the two systems: no ids to keep in sync, and somebody
    holding a tube can search the same words in either place.

    THE DRAWING lives in the same content-addressed blob store as node
    attachments (app/storage.py) but is recorded in columns here rather than in
    the attachments table, because attachments.node_id is NOT NULL and SQLite
    cannot drop that without rebuilding the table -- not something to do to a
    database with the team's files already in it. One current drawing per part;
    re-uploading replaces it.

    Because the store is shared and deduplicated, anything that frees blobs has
    to consult BOTH tables -- the same PDF attached to a node and set as a
    drawing is one file on disk. storage.still_referenced() is the one place
    that knows this, and scripts/gc_blobs.py counts both too.
    """

    __tablename__ = "mfg_parts"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Free text rather than an enum: the UI offers this project's own subsystem
    # names taken from its tree, but a jig or a spare belongs to no subsystem,
    # and the vocabulary should not need a code change to say so.
    subsystem: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="todo")
    notes: Mapped[str | None] = mapped_column(Text)
    assignee_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))

    # Related links: the part in Onshape, a vendor page, a bend-table PDF.
    # A JSON list of {"label": str, "url": str} rather than a child table,
    # because nothing ever queries them -- they are only read back with the
    # part. Same reasoning as Node.extra.
    #
    # The URLs are validated at the API boundary (schemas.MfgLink): http and
    # https only. That matters because these render as real hrefs, and a
    # "javascript:" URL stored here would be stored XSS.
    links: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    # --- the current drawing -------------------------------------------------
    drawing_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    drawing_filename: Mapped[str | None] = mapped_column(String(255))
    drawing_content_type: Mapped[str | None] = mapped_column(String(120))
    drawing_size_bytes: Mapped[int | None] = mapped_column(Integer)
    drawing_uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship()
    assignee: Mapped[Member | None] = relationship()

    __table_args__ = (
        # Every read is "this project's cut list", usually grouped by subsystem.
        Index("ix_mfg_parts_project", "project_id", "subsystem"),
    )

    @property
    def has_drawing(self) -> bool:
        return bool(self.drawing_sha256)


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


class Milestone(Base):
    """A dated goal on the project timeline.

    The team already plans on a whiteboard: a horizontal line from October to
    competition, with dates hung off it -- "roll cage doc package 2/12", "BOM",
    "car fully assembled". This is that board, so it survives the room being
    wiped.

    Deliberately NOT a Node. A milestone is not part of the car: it has no
    quantity, no cost, no vendor, no place in the assembly tree, and it would
    pollute every rollup and BOM export if it lived there. What it has that a
    node does not is a date.

    due_date is a DATE, not a datetime. A deadline is a day -- "2/12", not
    "2/12 at 00:00 UTC" -- and storing an instant means the deadline silently
    lands on a different day depending on the reader's timezone.
    """

    __tablename__ = "milestones"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str | None] = mapped_column(Text)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)

    # See GOAL_PRIORITIES. Validated at the API boundary, not as a DB enum, for
    # the same reason as every other vocabulary here: adding a level should be
    # a one-line edit, not a migration.
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="other")

    done: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # When it was ticked off, for "we said 2/12 and it landed 2/27" after the
    # season. Set and cleared by the API, never by hand.
    done_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner_id: Mapped[int | None] = mapped_column(ForeignKey("members.id", ondelete="SET NULL"))
    # Optional link to the part or subsystem this goal is about, so "fuel tank
    # mount" on the timeline can jump to the actual node. SET NULL rather than
    # CASCADE: deleting a part should not silently delete the deadline that
    # referred to it -- that is exactly when you want to still see the goal.
    node_id: Mapped[int | None] = mapped_column(ForeignKey("nodes.id", ondelete="SET NULL"))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship()
    owner: Mapped[Member | None] = relationship()
    node: Mapped["Node | None"] = relationship()

    __table_args__ = (
        # Every read is "this project's milestones, in date order".
        Index("ix_milestones_project_due", "project_id", "due_date"),
    )


# --- Learn: the team's own reference library ---------------------------------

class LearnSection(Base):
    """One card on the Learn page: "Suspension", "Welding", "CAD best practices".

    NOT scoped to a project. Everything else in the app belongs to one car;
    this belongs to the team. How to TIG a cope joint does not change when you
    start next season's tree, and cloning a project should not fork the
    knowledge base into two copies that drift apart.

    Content lives in the database, edited in the app, rather than as Markdown
    files in the repo. Leads rotate every year, and the person fixing the
    welding page next season should not need git, a terminal or a redeploy --
    the same reason the admin list is managed in-app.

    image_id points at a LearnImage but is deliberately NOT a foreign key.
    LearnImage already points back here (section_id), and the two FKs together
    are a cycle that SQLite's CREATE TABLE cannot express. The API keeps the
    two consistent, and a dangling id serves a 404 rather than a crash.
    """

    __tablename__ = "learn_sections"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    # The one or two sentences under the title on the card.
    summary: Mapped[str | None] = mapped_column(Text)
    # Stored as section_group: GROUP is reserved in SQL, and a column named
    # that works through the ORM but trips up anyone querying the file by hand.
    group: Mapped[str] = mapped_column(
        "section_group", String(20), nullable=False, default="library"
    )
    icon: Mapped[str] = mapped_column(String(20), nullable=False, default="book")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    image_id: Mapped[int | None] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    pages: Mapped[list["LearnPage"]] = relationship(
        back_populates="section",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="LearnPage.position",
    )


class LearnPage(Base):
    """A writeup inside a section, followed by its CAD references.

    `body` is Markdown. It is rendered in the browser by a small parser that
    builds React elements directly and never produces an HTML string, so
    nothing typed here can become markup -- see frontend/src/lib/markdown.ts.

    `references` is a JSON list of {title, url, description, image_id}: the
    "CAD references" cards under the writeup. JSON rather than a child table
    for the same reason as MfgPart.links -- nothing queries them on their own.

    `version` goes up by one on every save. An editor sends back the version
    it started from, and a save against a newer one is refused instead of
    silently overwriting a teammate's hour of writing.
    """

    __tablename__ = "learn_pages"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("learn_sections.id", ondelete="CASCADE"), nullable=False
    )
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    references: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    updated_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    section: Mapped[LearnSection] = relationship(back_populates="pages")
    updated_by: Mapped[Member | None] = relationship()

    __table_args__ = (Index("ix_learn_pages_section", "section_id", "position"),)


class LearnImage(Base):
    """A picture used on the Learn pages: a card render, a photo in a writeup,
    or the thumbnail on a CAD reference.

    The bytes live in the shared content-addressed blob store, so this is the
    third table that can reference a blob. storage.blob_reference_columns()
    lists all of them, and both the delete path and scripts/gc_blobs.py read
    that one list -- add a fourth table there or its files get collected.

    Every image belongs to a section, so deleting a section takes its pictures
    with it. page_id is set for images uploaded while editing a page, so
    deleting just that page can free them too.
    """

    __tablename__ = "learn_images"

    id: Mapped[int] = mapped_column(primary_key=True)
    section_id: Mapped[int] = mapped_column(
        ForeignKey("learn_sections.id", ondelete="CASCADE"), nullable=False
    )
    page_id: Mapped[int | None] = mapped_column(ForeignKey("learn_pages.id", ondelete="CASCADE"))

    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    uploaded_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL")
    )
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


# --- Orders: parts the team wants bought -------------------------------------

class PurchaseRequest(Base):
    """Somebody needs something bought.

    Scoped to a project, unlike Learn: a season's budget belongs to that car,
    and last year's orders should stay with last year's tree rather than
    padding this year's totals.

    requested_by_id is set by the API from whoever is signed in. It is not a
    field anyone can type, because "who asked for this" is the one fact the
    approval step relies on.

    `history` is a JSON list, one entry per status change:
        [{"status": "approved", "at": "<ISO-8601>", "by": <member id>,
          "by_name": "<their name at the time>"}]
    The name is copied in, not just the id, so the record still reads right
    after a member is removed from the roster. Nothing queries it, so it is a
    column rather than a table -- same reasoning as MfgPart.links.

    Money is integer cents, like Node.cost_cents, so totals never pick up
    floating-point pennies.
    """

    __tablename__ = "purchase_requests"

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )

    item: Mapped[str] = mapped_column(String(200), nullable=False)
    vendor: Mapped[str | None] = mapped_column(String(120))
    # The product page. http/https only, validated at the API boundary,
    # because it renders as a real href.
    url: Mapped[str | None] = mapped_column(String(2000))
    # The vendor's own number -- a McMaster part number, a SKU.
    part_number: Mapped[str | None] = mapped_column(String(120))
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    unit_cost_cents: Mapped[int | None] = mapped_column(Integer)
    # Why it is needed. The single most useful thing for whoever approves it.
    notes: Mapped[str | None] = mapped_column(Text)
    # Free text, like MfgPart.subsystem: the UI suggests this car's own
    # subsystem names, but shop consumables belong to none of them.
    subsystem: Mapped[str | None] = mapped_column(String(80))
    # A DATE, like Milestone.due_date: "needed by Friday" is a day, not an
    # instant that lands on Thursday for anyone west of UTC.
    needed_by: Mapped[date | None] = mapped_column(Date)

    status: Mapped[str] = mapped_column(String(20), nullable=False, default="requested")
    # Filled in by whoever places the order.
    order_number: Mapped[str | None] = mapped_column(String(120))
    tracking_number: Mapped[str | None] = mapped_column(String(120))
    history: Mapped[list] = mapped_column(JSON, nullable=False, default=list)

    requested_by_id: Mapped[int | None] = mapped_column(
        ForeignKey("members.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )

    project: Mapped[Project] = relationship()
    requested_by: Mapped[Member | None] = relationship()

    __table_args__ = (Index("ix_purchase_requests_project", "project_id", "status"),)

    @property
    def total_cents(self) -> int | None:
        """Quantity times unit price, or None when nobody has priced it yet --
        an unpriced request must not count as $0 in the budget."""
        if self.unit_cost_cents is None:
            return None
        return self.unit_cost_cents * self.quantity


class AppMeta(Base):
    """Facts about this database itself, as key/value pairs.

    It exists for one-time setup that must happen exactly once and survive a
    crash. "Has the starter Learn library been written?" cannot be inferred
    from whether its table exists: a boot that creates the tables and then
    fails before seeding leaves them there, empty, and every later boot would
    skip the seed for good. Writing a marker here in the SAME commit as the
    seeded rows makes the two succeed or fail together.
    """

    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
