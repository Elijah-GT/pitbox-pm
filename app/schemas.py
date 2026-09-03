"""Pydantic request/response models -- the validation boundary.

The controlled vocabularies (status, node_type, sourcing) are enforced here as
Literals rather than as database enums. Adding a status is a one-line edit with
no migration; sending a bogus one still gets a 422 with a helpful message.
"""
from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

NodeType = Literal["vehicle", "subsystem", "assembly", "part"]
Status = Literal[
    "concept", "design", "in_review", "ordered",
    "in_fabrication", "assembled", "not_installed", "installed",
]
Sourcing = Literal["make", "buy", "na"]
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
