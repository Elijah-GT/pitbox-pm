"""Templates and first-run seed data.

BAJA_TEMPLATE is the skeleton a new car starts from. Edit it to match how your
team actually divides work -- it is just a nested list, no database involved.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import tree
from .models import Member, Node, NodeTag, Project, Tag

# name, node_type, children
BAJA_TEMPLATE: list[dict] = [
    {"name": "Frame & Chassis", "children": [
        {"name": "Primary Roll Cage"},
        {"name": "Secondary Members"},
        {"name": "Firewall"},
        {"name": "Skid Plate"},
        {"name": "Mounting Tabs & Brackets"},
    ]},
    {"name": "Front Suspension", "children": [
        {"name": "Upper Control Arms"},
        {"name": "Lower Control Arms"},
        {"name": "Uprights / Knuckles"},
        {"name": "Shocks & Springs"},
        {"name": "Hubs & Bearings"},
    ]},
    {"name": "Rear Suspension", "children": [
        {"name": "Trailing Arms"},
        {"name": "Camber Links"},
        {"name": "Uprights / Carriers"},
        {"name": "Shocks & Springs"},
    ]},
    {"name": "Steering", "children": [
        {"name": "Steering Rack"},
        {"name": "Tie Rods"},
        {"name": "Steering Column & U-Joints"},
        {"name": "Steering Wheel & Quick Release"},
    ]},
    {"name": "Drivetrain", "children": [
        {"name": "CVT / Primary & Secondary"},
        {"name": "Gearbox"},
        {"name": "Axles & CV Joints"},
        {"name": "Engine Mounts"},
    ]},
    {"name": "Brakes", "children": [
        {"name": "Master Cylinders"},
        {"name": "Pedal Assembly"},
        {"name": "Calipers"},
        {"name": "Rotors"},
        {"name": "Brake Lines"},
    ]},
    {"name": "Powertrain", "children": [
        {"name": "Engine (Briggs & Stratton 10 HP)", "node_type": "part", "sourcing": "buy"},
        {"name": "Throttle & Kill Switch"},
        {"name": "Fuel System"},
        {"name": "Exhaust & Heat Shielding"},
    ]},
    {"name": "Electrical & Data", "children": [
        {"name": "Wiring Harness"},
        {"name": "Battery & Power Distribution"},
        {"name": "Kill Switches"},
        {"name": "Data Acquisition"},
        {"name": "Brake Light"},
    ]},
    {"name": "Ergonomics & Safety", "children": [
        {"name": "Seat & Mounts"},
        {"name": "Harness (5-point)"},
        {"name": "Firewall & Guards"},
        {"name": "Driver Controls"},
    ]},
    {"name": "Body & Aesthetics", "children": [
        {"name": "Body Panels"},
        {"name": "Nose Cone"},
        {"name": "Numbers & Livery"},
    ]},
]

# Slug, name, color, category. Kept small on purpose -- a tag list nobody can
# hold in their head stops being a filter and starts being clutter.
DEFAULT_TAGS: list[dict] = [
    {"name": "Electrical", "color": "#3b82f6", "category": "discipline"},
    {"name": "Mechanical", "color": "#8b5cf6", "category": "discipline"},
    {"name": "Manufacturing", "color": "#f59e0b", "category": "discipline"},
    {"name": "Pending Machining", "color": "#ef4444", "category": "workflow"},
    {"name": "Needs Drawing", "color": "#ec4899", "category": "workflow"},
    {"name": "Awaiting Delivery", "color": "#14b8a6", "category": "workflow"},
    {"name": "COTS", "color": "#64748b", "category": "sourcing"},
    {"name": "In House", "color": "#22c55e", "category": "sourcing"},
    {"name": "Safety Critical", "color": "#dc2626", "category": "risk"},
    {"name": "Rules Critical", "color": "#f97316", "category": "risk"},
    {"name": "Weight Critical", "color": "#a3e635", "category": "risk"},
]


def build_template(db: Session, project_id: int, root: Node, spec: list[dict]) -> None:
    """Recursively materialize a nested template under a root node."""
    for entry in spec:
        children = entry.get("children", [])
        fields = {k: v for k, v in entry.items() if k != "children"}
        fields.setdefault("node_type", "subsystem" if children else "assembly")
        node = tree.create_node(db, project_id=project_id, parent=root, **fields)
        if children:
            build_template(db, project_id, node, children)


def ensure_default_tags(db: Session) -> list[Tag]:
    """Create any missing default tags. Safe to call on every startup."""
    created = []
    for spec in DEFAULT_TAGS:
        slug = tree.slugify(spec["name"])
        if db.scalar(select(Tag).where(Tag.slug == slug)):
            continue
        tag = Tag(slug=slug, **spec)
        db.add(tag)
        created.append(tag)
    if created:
        db.commit()
    return created


# The demo roster, named here so scripts/remove_demo_members.py deletes exactly
# these and cannot drift out of sync with what gets seeded.
DEMO_MEMBER_NAMES = (
    "Alex Rivera",
    "Priya Nair",
    "Sam Okafor",
    "Jordan Blake",
    "Casey Lam",
)


def seed_demo(db: Session) -> Project | None:
    """Populate a realistic-looking car so the UI has something to show on a
    fresh clone. Returns None if any project already exists."""
    if db.scalar(select(func.count()).select_from(Project)):
        return None

    ensure_default_tags(db)
    tags = {t.slug: t for t in db.scalars(select(Tag))}

    roster = [
        Member(name="Alex Rivera", subteam="Suspension", role="Lead"),
        Member(name="Priya Nair", subteam="Drivetrain", role="Lead"),
        Member(name="Sam Okafor", subteam="Electrical", role="Lead"),
        Member(name="Jordan Blake", subteam="Frame", role="Fabrication"),
        Member(name="Casey Lam", subteam="Brakes", role="Member"),
    ]
    db.add_all(roster)
    db.flush()
    by_name = {m.name: m for m in roster}

    project = Project(
        name="Baja 2026 Car",
        slug=tree.unique_slug(db, "Baja 2026 Car"),
        season="2026",
        description="Competition vehicle for the 2026 season.",
    )
    db.add(project)
    db.flush()

    root = tree.create_node(
        db, project_id=project.id, parent=None,
        name="Baja 2026 Car", node_type="vehicle", status="design",
    )
    build_template(db, project.id, root, BAJA_TEMPLATE)
    db.flush()

    def find(name: str) -> Node | None:
        return db.scalar(select(Node).where(Node.project_id == project.id, Node.name == name))

    # A few real parts so filtering and rollups have something to chew on.
    uprights = find("Uprights / Knuckles")
    if uprights:
        tree.create_node(
            db, project_id=project.id, parent=uprights,
            name="Front Upright, LH", node_type="part", part_number="SUS-FU-001",
            status="in_fabrication", sourcing="make", material="7075-T6 Aluminum",
            mass_g=640.0, cost_cents=8500, quantity=1,
            assignee_id=by_name["Alex Rivera"].id,
            description="CNC machined upright, mirror of RH.",
        )
        tree.create_node(
            db, project_id=project.id, parent=uprights,
            name="Front Upright, RH", node_type="part", part_number="SUS-FU-002",
            status="design", sourcing="make", material="7075-T6 Aluminum",
            mass_g=640.0, cost_cents=8500, quantity=1,
            assignee_id=by_name["Alex Rivera"].id,
        )

    hubs = find("Hubs & Bearings")
    if hubs:
        tree.create_node(
            db, project_id=project.id, parent=hubs,
            name="Tapered Roller Bearing 32005X", node_type="part", part_number="BRG-32005X",
            status="ordered", sourcing="buy", vendor="McMaster-Carr",
            cost_cents=1450, quantity=4, lead_time_days=5,
            assignee_id=by_name["Alex Rivera"].id,
        )

    harness = find("Wiring Harness")
    if harness:
        tree.create_node(
            db, project_id=project.id, parent=harness,
            name="Main Harness Loom", node_type="assembly", part_number="ELE-HRN-001",
            status="design", sourcing="make",
            assignee_id=by_name["Sam Okafor"].id,
        )

    daq = find("Data Acquisition")
    if daq:
        tree.create_node(
            db, project_id=project.id, parent=daq,
            name="DAQ Mainboard Rev B", node_type="part", part_number="ELE-DAQ-002",
            status="in_review", sourcing="make", cost_cents=6200, quantity=1,
            assignee_id=by_name["Sam Okafor"].id,
            description="STM32-based logger, CAN + SD card.",
        )

    pedals = find("Pedal Assembly")
    if pedals:
        tree.create_node(
            db, project_id=project.id, parent=pedals,
            name="Brake Pedal Weldment", node_type="part", part_number="BRK-PDL-001",
            status="needs_rework", sourcing="make", material="4130 Chromoly",
            mass_g=410.0, quantity=1, assignee_id=by_name["Casey Lam"].id,
        )

    db.flush()

    # Branch tags (cascade=True) vs. part tags -- this is the distinction the
    # whole filtering model turns on.
    electrical = find("Electrical & Data")
    brakes = find("Brakes")
    frame = find("Frame & Chassis")
    assignments = [
        (electrical, "electrical", True),      # whole branch is Electrical
        (brakes, "safety-critical", True),     # whole branch is Safety Critical
        (frame, "rules-critical", True),
        (find("Front Upright, LH"), "pending-machining", False),
        (find("Front Upright, RH"), "needs-drawing", False),
        (find("Tapered Roller Bearing 32005X"), "cots", False),
        (find("Tapered Roller Bearing 32005X"), "awaiting-delivery", False),
        (find("Brake Pedal Weldment"), "in-house", False),
    ]
    for node, slug, cascade in assignments:
        if node is not None and slug in tags:
            db.add(NodeTag(node_id=node.id, tag_id=tags[slug].id, cascade=cascade))

    db.commit()
    return project
