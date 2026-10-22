"""Pydantic request/response models -- the validation boundary.

The controlled vocabularies (status, node_type, sourcing) are enforced here as
Literals rather than as database enums. Adding a status is a one-line edit with
no migration; sending a bogus one still gets a 422 with a helpful message.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeType = Literal["vehicle", "subsystem", "assembly", "part"]
Status = Literal[
    "concept", "design", "in_review", "ordered",
    "in_fabrication", "assembled", "not_installed", "installed",
]
Sourcing = Literal["make", "buy", "na"]
GoalPriority = Literal["sae", "critical", "normal", "low"]
GoalKind = Literal["design", "manufacturing", "other"]
MfgStatus = Literal["todo", "in_progress", "done"]
LearnGroup = Literal["library", "cad"]
LearnIcon = Literal["gear", "spring", "wheel", "weld", "cube", "book"]
OrderStatus = Literal[
    "requested", "approved", "ordered", "shipped", "received", "denied", "cancelled",
]
AttachmentKind = Literal[
    "datasheet", "cad", "drawing", "pcb", "firmware", "analysis", "photo", "other"
]

ORM = ConfigDict(from_attributes=True)


# --- members -----------------------------------------------------------------

class MemberIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str | None = Field(default=None, max_length=200)
    subteam: str | None = Field(default=None, max_length=80)
    role: str | None = Field(default=None, max_length=80)
    is_active: bool = True


class MemberOut(MemberIn):
    model_config = ORM
    id: int
    is_admin: bool = False
    # password_hash is deliberately absent — this model is what the API returns.
    has_password: bool = False
    name_confirmed: bool = False


class AdminUpdate(BaseModel):
    """Promote or demote one member. Its own endpoint, and its own model, so
    the flag can never ride along on a general member edit -- MemberIn has no
    is_admin field, which is what stops PATCH /api/members/{id} from being a
    self-promotion route."""

    is_admin: bool


class ProfileUpdate(BaseModel):
    """What a person may change about their OWN record.

    Deliberately not email: that is the identity Cloudflare verified, and letting
    someone edit it would let them impersonate a teammate on their next visit."""

    name: str = Field(min_length=1, max_length=120)
    subteam: str | None = Field(default=None, max_length=80)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=1, max_length=200)


class PasswordSet(BaseModel):
    """Admins set another member's password; members change their own."""
    password: str = Field(min_length=8, max_length=200)


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=200)


# --- tags --------------------------------------------------------------------

class TagIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    color: str = Field(default="#ff6b35", pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    category: str | None = Field(default=None, max_length=60)
    description: str | None = None


class TagUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    color: str | None = Field(default=None, pattern=r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
    category: str | None = Field(default=None, max_length=60)
    description: str | None = None


class TagOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    slug: str
    color: str
    category: str | None = None
    description: str | None = None


class TagWithUsage(TagOut):
    node_count: int = 0


class TagAssignment(BaseModel):
    """Attach a tag to a node.

    cascade=True is the 'tag this whole branch' switch: every descendant, present
    and future, inherits the tag until this single link is removed.
    """
    tag_id: int
    cascade: bool = False
    note: str | None = Field(default=None, max_length=300)


class EffectiveTag(BaseModel):
    tag_id: int
    slug: str
    name: str
    color: str
    category: str | None = None
    cascade: bool = False
    inherited: bool = False
    source_node_id: int


# --- attachments -------------------------------------------------------------

class AttachmentOut(BaseModel):
    model_config = ORM
    id: int
    node_id: int
    filename: str
    content_type: str
    size_bytes: int
    sha256: str
    kind: str
    version: int
    is_current: bool
    notes: str | None = None
    uploaded_by_id: int | None = None
    uploaded_at: datetime


# --- nodes -------------------------------------------------------------------

class NodeBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    node_type: NodeType = "part"
    part_number: str | None = Field(default=None, max_length=80)
    status: Status = "concept"
    assignee_id: int | None = None
    description: str | None = None
    quantity: int = Field(default=1, ge=0)
    sourcing: Sourcing = "na"
    material: str | None = Field(default=None, max_length=120)
    mass_g: float | None = Field(default=None, ge=0)
    cost_cents: int | None = Field(default=None, ge=0)
    vendor: str | None = Field(default=None, max_length=160)
    lead_time_days: int | None = Field(default=None, ge=0)
    extra: dict[str, Any] = Field(default_factory=dict)


class NodeCreate(NodeBase):
    project_id: int
    parent_id: int | None = None
    position: int | None = None


class NodeUpdate(BaseModel):
    """All-optional patch. Every field must be explicitly settable to null except
    name, so we rely on exclude_unset at the call site to tell 'clear this' apart
    from 'leave it alone'."""
    name: str | None = Field(default=None, min_length=1, max_length=200)
    node_type: NodeType | None = None
    part_number: str | None = None
    status: Status | None = None
    assignee_id: int | None = None
    description: str | None = None
    quantity: int | None = Field(default=None, ge=0)
    sourcing: Sourcing | None = None
    material: str | None = None
    mass_g: float | None = Field(default=None, ge=0)
    cost_cents: int | None = Field(default=None, ge=0)
    vendor: str | None = None
    lead_time_days: int | None = Field(default=None, ge=0)
    extra: dict[str, Any] | None = None


class NodeOut(NodeBase):
    model_config = ORM
    id: int
    project_id: int
    parent_id: int | None
    path: str
    depth: int
    position: int
    created_at: datetime
    updated_at: datetime


class NodeDetail(NodeOut):
    """A node plus everything the detail panel needs, in one request."""
    tags: list[EffectiveTag] = Field(default_factory=list)
    attachments: list[AttachmentOut] = Field(default_factory=list)
    ancestor_ids: list[int] = Field(default_factory=list)
    child_count: int = 0
    descendant_count: int = 0
    rollup_cost_cents: int = 0
    rollup_mass_g: float = 0.0


class NodeMove(BaseModel):
    new_parent_id: int | None = None
    position: int | None = None


class NodeReorder(BaseModel):
    project_id: int
    parent_id: int | None = None
    ordered_ids: list[int]


class NodeDuplicate(BaseModel):
    new_parent_id: int | None = None
    name: str | None = None
    reset_status: Status | None = None
    copy_tags: bool = True
    copy_attachments: bool = True


# --- projects ----------------------------------------------------------------

class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    season: str | None = Field(default=None, max_length=40)
    description: str | None = None


class ProjectCreate(ProjectIn):
    """template picks what the new tree starts as.

    blank         -- just a root node, build it yourself
    baja_standard -- the eight standard Baja SAE subsystems, pre-seeded
    """
    template: Literal["blank", "baja_standard"] = "baja_standard"


class ProjectClone(ProjectIn):
    """Start a new season from an existing car."""
    source_project_id: int
    reset_status: Status | None = "concept"
    copy_tags: bool = True
    copy_attachments: bool = True


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    season: str | None = None
    description: str | None = None
    is_archived: bool | None = None


class ProjectOut(BaseModel):
    model_config = ORM
    id: int
    name: str
    slug: str
    season: str | None = None
    description: str | None = None
    is_archived: bool
    created_at: datetime
    updated_at: datetime


class ProjectSummary(ProjectOut):
    node_count: int = 0
    attachment_count: int = 0


# --- milestones (the project timeline) --------------------------------------

class MilestoneIn(BaseModel):
    """A dated goal. Everything except the title and the date is optional."""

    project_id: int
    title: str = Field(min_length=1, max_length=200)
    due_date: date
    detail: str | None = None
    priority: GoalPriority = "normal"
    kind: GoalKind = "other"
    owner_id: int | None = None
    node_id: int | None = None


class MilestoneUpdate(BaseModel):
    """A partial edit. project_id is absent on purpose -- moving a goal to
    another tree is not an edit, it is a different goal."""

    title: str | None = Field(default=None, min_length=1, max_length=200)
    due_date: date | None = None
    detail: str | None = None
    priority: GoalPriority | None = None
    kind: GoalKind | None = None
    owner_id: int | None = None
    node_id: int | None = None
    done: bool | None = None


class MilestoneOut(BaseModel):
    model_config = ORM
    id: int
    project_id: int
    title: str
    detail: str | None = None
    due_date: date
    priority: GoalPriority = "normal"
    kind: GoalKind = "other"
    done: bool = False
    done_at: datetime | None = None
    owner_id: int | None = None
    node_id: int | None = None


# --- manufacturing (the cut list) --------------------------------------------

class MfgLink(BaseModel):
    """A related link on a shop part: the part in Onshape, a vendor page.

    The scheme check is the whole reason this model exists. These render as
    real <a href> values, so a stored "javascript:..." URL would be stored XSS
    that fires for whoever clicks it. Allowing only http and https rules out
    data: and file: at the same time.
    """

    label: str | None = Field(default=None, max_length=80)
    url: str = Field(min_length=1, max_length=2000)

    @field_validator("label")
    @classmethod
    def _tidy_label(cls, v: str | None) -> str | None:
        return None if v is None else (v.strip() or None)

    @field_validator("url")
    @classmethod
    def _only_web_urls(cls, v: str) -> str:
        return _web_url(v)


def _web_url(value: str) -> str:
    """Trim, and refuse anything that is not an http(s) URL.

    Shared by every model whose URL ends up as a real href -- shop links, Learn
    CAD references, purchase-request product pages -- so the rule that keeps
    "javascript:" out is written once rather than three slightly different times.
    """
    url = value.strip()
    # Compared on a lowered copy but stored as typed: some paths are
    # case-sensitive, and Onshape document ids are mixed case.
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("A link must start with http:// or https://")
    return url


def _blank_to_none(value: str | None) -> str | None:
    """Trim, and treat "" as "not set".

    An empty subsystem and a missing one mean the same thing to a person, and
    letting both into the database means the cut list grows two separate "no
    subsystem" groups -- one for NULL and one for "" -- which reads as a bug.
    Sorting splits the same way: "" lands before "Front Suspension" while NULL
    is deliberately sorted last.
    """
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class MfgPartIn(BaseModel):
    """A new part for the shop. Only the name is required -- the rest gets
    filled in as the part moves from "somebody should cut this" to done."""

    project_id: int
    name: str = Field(min_length=1, max_length=200)
    subsystem: str | None = Field(default=None, max_length=80)
    status: MfgStatus = "todo"
    notes: str | None = None
    assignee_id: int | None = None
    # Capped: these are a handful of references, not a bookmark folder, and an
    # unbounded JSON list is an easy way to bloat every read of the cut list.
    links: list[MfgLink] = Field(default_factory=list, max_length=12)

    @field_validator("subsystem", "notes")
    @classmethod
    def _tidy(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("name")
    @classmethod
    def _tidy_name(cls, v: str) -> str:
        name = v.strip()
        if not name:
            raise ValueError("A part needs a name.")
        return name


class MfgPartUpdate(BaseModel):
    """A partial edit. project_id is absent on purpose: moving a part to
    another car is not an edit, it is a different part."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    subsystem: str | None = Field(default=None, max_length=80)
    status: MfgStatus | None = None
    notes: str | None = None
    assignee_id: int | None = None
    links: list[MfgLink] | None = Field(default=None, max_length=12)

    @field_validator("subsystem", "notes")
    @classmethod
    def _tidy(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("name")
    @classmethod
    def _tidy_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        name = v.strip()
        if not name:
            raise ValueError("A part needs a name.")
        return name


class MfgPartOut(BaseModel):
    model_config = ORM
    id: int
    project_id: int
    name: str
    subsystem: str | None = None
    status: MfgStatus = "todo"
    notes: str | None = None
    assignee_id: int | None = None
    links: list[MfgLink] = Field(default_factory=list)

    # The drawing. sha256 is deliberately NOT exposed: it is an internal
    # storage address, and publishing it would let anyone probe the blob store
    # for files they were never shown.
    has_drawing: bool = False
    drawing_filename: str | None = None
    drawing_content_type: str | None = None
    drawing_size_bytes: int | None = None
    drawing_uploaded_at: datetime | None = None


class TreeResponse(BaseModel):
    """The whole tree in one payload.

    Deliberately flat: the client builds the parent/child links itself. A flat
    list is cheaper to serialize, trivial to filter, and does not blow the stack
    on a deep assembly the way nested JSON does.
    """
    project: ProjectOut
    nodes: list[NodeOut]
    tags_by_node: dict[int, list[EffectiveTag]] = Field(default_factory=dict)
    attachment_counts: dict[int, int] = Field(default_factory=dict)
    tags: list[TagWithUsage] = Field(default_factory=list)
    members: list[MemberOut] = Field(default_factory=list)


class FilterResult(BaseModel):
    """Server-side filtering, for when a tree gets big enough that the client
    should not do it, or when you want a shareable filtered URL.

    matched_ids   -- nodes that actually satisfy the filter
    visible_ids   -- matched nodes plus the ancestors needed to reach them, which
                     is what you must render to avoid a tree full of holes
    """
    matched_ids: list[int]
    visible_ids: list[int]
    matched_count: int


def _required(value: str, what: str) -> str:
    """Trim a required text field, and refuse one that is only whitespace --
    min_length=1 alone lets "   " through as a title."""
    text = value.strip()
    if not text:
        raise ValueError(f"{what} cannot be blank.")
    return text


def _optional_url(value: str | None) -> str | None:
    """An optional link: blank means none, anything else must be http(s)."""
    if value is None or not value.strip():
        return None
    return _web_url(value)


# --- learn -------------------------------------------------------------------

class LearnReference(BaseModel):
    """One "CAD reference" card under a writeup: a picture, a title, a line of
    description, and a link to the model in Onshape."""

    title: str = Field(min_length=1, max_length=120)
    url: str = Field(min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=300)
    # A LearnImage in the same section; checked by the router.
    image_id: int | None = None

    @field_validator("title")
    @classmethod
    def _tidy_title(cls, v: str) -> str:
        return _required(v, "A reference title")

    @field_validator("description")
    @classmethod
    def _tidy_description(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("url")
    @classmethod
    def _only_web_urls(cls, v: str) -> str:
        return _web_url(v)


class LearnSectionIn(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=600)
    group: LearnGroup = "library"
    icon: LearnIcon = "book"

    @field_validator("title")
    @classmethod
    def _tidy_title(cls, v: str) -> str:
        return _required(v, "A section title")

    @field_validator("summary")
    @classmethod
    def _tidy_summary(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class LearnSectionUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=120)
    summary: str | None = Field(default=None, max_length=600)
    group: LearnGroup | None = None
    icon: LearnIcon | None = None

    @field_validator("title")
    @classmethod
    def _tidy_title(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "A section title")

    @field_validator("summary")
    @classmethod
    def _tidy_summary(cls, v: str | None) -> str | None:
        return _blank_to_none(v)


class LearnMove(BaseModel):
    """Swap with the neighbour above or below. One step at a time, because
    that is all an up/down button needs and it cannot leave a gap."""

    direction: Literal["up", "down"]


class LearnPageSummary(BaseModel):
    """A page as it appears in a card's chips and the sidebar: no body."""

    model_config = ORM
    id: int
    section_id: int
    title: str
    position: int = 0


class LearnSectionOut(BaseModel):
    model_config = ORM
    id: int
    title: str
    summary: str | None = None
    group: LearnGroup = "library"
    icon: LearnIcon = "book"
    position: int = 0
    # Where the card's render is served from, or None for the line-art icon.
    image_url: str | None = None
    pages: list[LearnPageSummary] = Field(default_factory=list)


class LearnLibraryOut(BaseModel):
    """The whole Learn index in one call. It is a few dozen rows -- not worth a
    request per card."""

    sections: list[LearnSectionOut]


class LearnPageIn(BaseModel):
    section_id: int
    title: str = Field(min_length=1, max_length=160)

    @field_validator("title")
    @classmethod
    def _tidy_title(cls, v: str) -> str:
        return _required(v, "A page title")


class LearnPageUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    # Markdown. Capped generously -- a long writeup is a few thousand words.
    body: str | None = Field(default=None, max_length=100_000)
    references: list[LearnReference] | None = Field(default=None, max_length=24)
    # The version the editor started from. The app always sends it, so two
    # people editing the same page cannot silently overwrite each other; it is
    # optional so a deliberate script can still write without one.
    base_version: int | None = None

    @field_validator("title")
    @classmethod
    def _tidy_title(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "A page title")


class LearnPageOut(BaseModel):
    model_config = ORM
    id: int
    section_id: int
    title: str
    body: str = ""
    references: list[LearnReference] = Field(default_factory=list)
    position: int = 0
    version: int = 1
    updated_at: datetime | None = None
    updated_by_id: int | None = None
    # Resolved by the router, so "last edited by" survives without the client
    # needing the roster.
    updated_by_name: str | None = None


class LearnImageOut(BaseModel):
    id: int
    url: str
    filename: str


# --- orders ------------------------------------------------------------------

class _OrderFields(BaseModel):
    """What a requester fills in. Shared by create and edit so the two cannot
    disagree about what a valid request looks like."""

    vendor: str | None = Field(default=None, max_length=120)
    url: str | None = Field(default=None, max_length=2000)
    part_number: str | None = Field(default=None, max_length=120)
    # Capped as typo guards: nobody orders 100,001 bolts or a $1M part, but
    # an extra zero or two is easy to type and silently wrecks the totals.
    unit_cost_cents: int | None = Field(default=None, ge=0, le=100_000_000)
    notes: str | None = Field(default=None, max_length=4000)
    subsystem: str | None = Field(default=None, max_length=80)
    needed_by: date | None = None
    # Filled in by whoever places the order. The router stops a member setting
    # these: they describe an order a lead placed, not the request itself.
    order_number: str | None = Field(default=None, max_length=120)
    tracking_number: str | None = Field(default=None, max_length=120)

    @field_validator(
        "vendor", "part_number", "notes", "subsystem", "order_number", "tracking_number"
    )
    @classmethod
    def _tidy(cls, v: str | None) -> str | None:
        return _blank_to_none(v)

    @field_validator("url")
    @classmethod
    def _only_web_urls(cls, v: str | None) -> str | None:
        return _optional_url(v)


class PurchaseRequestIn(_OrderFields):
    project_id: int
    item: str = Field(min_length=1, max_length=200)
    quantity: int = Field(default=1, ge=1, le=100_000)
    # Leads only. A member's request always starts as "requested" -- the
    # router refuses anything else from them rather than quietly ignoring it.
    status: OrderStatus | None = None

    @field_validator("item")
    @classmethod
    def _tidy_item(cls, v: str) -> str:
        return _required(v, "What you want bought")


class PurchaseRequestUpdate(_OrderFields):
    """A partial edit. project_id is absent on purpose, as for shop parts."""

    item: str | None = Field(default=None, min_length=1, max_length=200)
    quantity: int | None = Field(default=None, ge=1, le=100_000)
    status: OrderStatus | None = None

    @field_validator("item")
    @classmethod
    def _tidy_item(cls, v: str | None) -> str | None:
        return None if v is None else _required(v, "What you want bought")


class OrderEvent(BaseModel):
    """One entry in a request's history: it became `status`, at `at`, by `by`."""

    status: OrderStatus
    at: datetime
    by: int | None = None
    by_name: str | None = None


class PurchaseRequestOut(BaseModel):
    model_config = ORM
    id: int
    project_id: int
    item: str
    vendor: str | None = None
    url: str | None = None
    part_number: str | None = None
    quantity: int = 1
    unit_cost_cents: int | None = None
    # quantity x unit price, or None when unpriced -- never 0 for "unknown".
    total_cents: int | None = None
    notes: str | None = None
    subsystem: str | None = None
    needed_by: date | None = None
    status: OrderStatus = "requested"
    order_number: str | None = None
    tracking_number: str | None = None
    history: list[OrderEvent] = Field(default_factory=list)
    requested_by_id: int | None = None
    created_at: datetime
    updated_at: datetime
