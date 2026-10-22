"""Starter content for the Learn page, created once on a database that has
never had a Learn library.

Two kinds of page, on purpose:

  * The library topics -- Drivetrain, Suspension, Steering, Welding -- get
    STARTER OUTLINES. They say what a page should cover, not how this team
    does it. Settings, materials and procedures are the team's knowledge, and
    inventing them here would put guesses on a page that looks authoritative.
    Each one says so at the top.

  * The CAD best practices get real chapters. Most of it is general Onshape
    practice, and the parts specific to CarHub -- the Onshape part name IS the
    Shop list name, a re-uploaded drawing replaces the old one -- are facts
    about this app, not opinions.

Everything here is ordinary data afterwards: edit it, reorder it or delete it
in the app. It is written once per database and never again -- not even if
the team empties the library -- see seed_learn_library_once().
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import AppMeta, LearnPage, LearnSection, utcnow

# The app_meta key that says this database has had its starter library.
SEEDED_KEY = "learn_library_seeded"

STARTER = (
    "> **Starter outline.** This page was created as a scaffold. Replace it "
    "with how *our* team actually does it — photos, numbers from testing, and "
    "CAD references below."
)


def _outline(intro: str, points: list[str], closing: str | None = None) -> str:
    body = [intro, "", STARTER, "", "## What to cover", ""]
    body += [f"- {p}" for p in points]
    if closing:
        body += ["", closing]
    return "\n".join(body) + "\n"


RULES_NOTE = (
    "> **Check the rules.** Before changing anything here, check the current "
    "Baja SAE rules — they change between seasons, and technical inspection "
    "goes by the current version."
)


LIBRARY: list[dict] = [
    {
        "title": "Drivetrain",
        "icon": "gear",
        "summary": (
            "CVT tuning, the gearbox and final reduction, axles and CV joints "
            "— how power gets from the engine to the ground."
        ),
        "pages": [
            ("CVT tuning", _outline(
                "How the CVT is tuned for the course, and how to tell whether a change helped.",
                [
                    "Which CVT the car runs, and where its tuning parts come from",
                    "Engagement and shift-out RPM: what we target and why",
                    "What each tuning part changes — primary weights, springs, the secondary",
                    "How we test a change: the run, what gets recorded, and where the log lives",
                    "Belt inspection and replacement",
                    "Known-good setups from past seasons, and the conditions they were tuned for",
                ],
            )),
            ("Gearbox & reduction", _outline(
                "The reduction between the CVT and the wheels.",
                [
                    "Overall reduction target, and the trade-off it was chosen on "
                    "(top speed, acceleration, hill climb, pulling)",
                    "Gearbox layout: stages, gears or chain, bought or designed in-house",
                    "Bearings, seals and lubrication",
                    "How the case mounts to the frame",
                    "Inspection and maintenance between events",
                ],
            )),
            ("Axles & CV joints", _outline(
                "Getting torque to the wheels through the full range of suspension travel.",
                [
                    "Axle and CV joint choices, and where they come from",
                    "Plunge and angle at full bump and full droop",
                    "Spline and hub interfaces",
                    "Boots, retention, and what to check before every run",
                    "Failures from past seasons, and what changed because of them",
                ],
            )),
        ],
    },
    {
        "title": "Suspension",
        "icon": "spring",
        "summary": (
            "Geometry and kinematics, shocks and springs, control arms and the "
            "mounts that carry their loads into the frame."
        ),
        "pages": [
            ("Geometry & kinematics", _outline(
                "Where the wheels go as the car moves, and why.",
                [
                    "Front and rear layout — double A-arm, trailing arm, or otherwise — and the reasons",
                    "Camber, caster and toe, and how they change through travel",
                    "Roll centre, scrub radius and motion ratio",
                    "Travel targets in bump and droop",
                    "How we model it, and where the files live",
                ],
            )),
            ("Shocks & springs", _outline(
                "What we run, how it is set up, and how it is looked after.",
                [
                    "Which shocks we run, and their service schedule",
                    "Spring rates and preload, and how they were chosen",
                    "Compression and rebound settings that worked at past events",
                    "Rebuild procedure, and who is trained to do it",
                ],
            )),
            ("Control arms & mounts", _outline(
                "The parts that hold the wheels on and carry the loads into the frame.",
                [
                    "Tube sizes and materials used for the arms",
                    "Rod ends, ball joints and bushings",
                    "Frame tabs, and how load gets into the cage",
                    "The jigs used to build arms accurately — link their drawings from Shop",
                ],
            )),
        ],
    },
    {
        "title": "Steering",
        "icon": "wheel",
        "summary": (
            "The rack, steering geometry and bump steer, and the column, wheel "
            "and quick release in front of the driver."
        ),
        "pages": [
            ("Rack & pinion", _outline(
                "Turning the driver's input into wheel angle.",
                [
                    "The rack we use — bought or made — its ratio and travel",
                    "Lock-to-lock turns, and the turning radius we are aiming for",
                    "How the rack is mounted, and kept from flexing",
                ],
            )),
            ("Steering geometry", _outline(
                "How the front wheels point as the car turns and moves.",
                [
                    "Ackermann: how much, and why",
                    "Bump steer: how we measure it and keep it small",
                    "Tie rod placement relative to the control arms",
                    "Steering effort, and what the driver can actually feel",
                ],
            )),
            ("Column, wheel & quick release", _outline(
                "Everything between the rack and the driver's hands.",
                [
                    "The column, U-joints and support bearings",
                    "The quick-release hub and the wheel",
                    "How the driver gets in and out with the wheel off",
                ],
                RULES_NOTE,
            )),
        ],
    },
    {
        "title": "Welding",
        "icon": "weld",
        "summary": (
            "Shop safety, tube fit-up and coping, TIG technique, and inspecting "
            "a joint before it goes on the car."
        ),
        "pages": [
            ("Shop safety", _outline(
                "Read this before striking an arc in our shop.",
                [
                    "Who is cleared to weld, and how a new member gets cleared",
                    "PPE: helmet, gloves, jacket, closed shoes — cotton or leather, not synthetics, which melt",
                    "Ventilation and fume extraction",
                    "Fire watch, and where the extinguisher is",
                    "Gas cylinders: chained upright, valve closed when you are done",
                    "Keeping chlorinated solvents — including some brake cleaners — away "
                    "from the welding area: the arc can turn their vapour into a toxic gas",
                    "Marking hot metal so nobody picks it up",
                ],
            )),
            ("Tube fit-up & coping", _outline(
                "A good weld starts with a joint that fits.",
                [
                    "Coping tools we have — notcher, hole saw, printed wrap templates — and when to use which",
                    "How tight a gap we aim for",
                    "Cleaning: mill scale, oil, and how clean is clean enough",
                    "Fixturing and tack order to control distortion",
                    "Checking the position against the CAD before the final weld",
                ],
            )),
            ("TIG technique", _outline(
                "How we weld the frame and brackets.",
                [
                    "Machine settings we start from for each wall thickness",
                    "Tungsten type and prep, filler rod, shielding gas and flow",
                    "Torch angle, travel speed, and controlling heat on thin wall",
                    "Whether we back-purge, and how",
                    "Practice coupons before welding anything on the car",
                ],
            )),
            ("Inspecting welds", _outline(
                "Deciding whether a joint is good enough for the car.",
                [
                    "Photos of good and bad welds from our own shop",
                    "Common defects: undercut, porosity, cracking, lack of fusion",
                    "Who signs off a joint, and where that is recorded",
                ],
                RULES_NOTE,
            )),
        ],
    },
]


CAD_GUIDE: dict = {
    "title": "Onshape standards",
    "icon": "cube",
    "summary": (
        "How we set up documents, name parts, build Part Studios and assemblies, "
        "and get drawings to the shop — so anyone can open anyone else's CAD."
    ),
    "pages": [
        ("Why we standardize", """\
Everyone on the team ends up working in CAD they did not draw. These
conventions exist so that is easy rather than painful.

- **Anyone can pick it up.** A new member can find the part, see how it was
  built, and change it without breaking three other things.
- **Changes are cheap.** When geometry is driven from a layout sketch, moving a
  pickup point is one edit, not a rebuild.
- **The shop gets the right thing.** Part names match the Shop list, and
  drawings come from a known version, so nobody cuts from a stale revision.

> **This is a living document.** If a rule here is wrong for how we work,
> tell a team lead — they keep these pages up to date.
"""),
        ("Naming parts", """\
The name of a part in Onshape is its name on CarHub's **Shop** list —
exactly, character for character. That string is the only link between the
two, so it has to be right.

## Rules

- **Unique across the car.** Two parts with the same name get cut twice, or
  not at all.
- **Say which side.** Left and right are different parts. Put the side in the
  name so the mirror image is never cut by mistake.
- **No spaces.** Use underscores — a space is easy to double or lose when a
  name gets retyped.
- **Stable.** Once a part is on the Shop list, renaming it in Onshape breaks the
  match. Rename it in both places, or not at all.

## Our pattern

Write the team's naming pattern here, with real examples from the current car.
"""),
        ("Document setup", """\
How a subsystem's CAD is laid out in Onshape.

- **One document per subsystem**, named for it, in the team's folder for the
  season. Change this if we split things differently.
- **A layout sketch first.** Hardpoints, envelopes and the key dimensions live
  in one sketch that everything else references. This is top-down design: the
  layout drives the parts, not the other way round.
- **Part Studios for parts, Assemblies for how they go together.** Keep each
  Part Studio small enough to regenerate quickly.
- **Versions mark milestones.** Make one when a design is reviewed, released to
  the shop, or about to change a lot, and name it so it reads well in a list —
  `V3 - released to shop`.
- **Branch to experiment.** Try a risky idea on a branch, and merge it back
  only if it works.
"""),
        ("Part Studios", """\
- **Fully define sketches.** Black lines, not blue. An under-defined sketch
  moves when something upstream changes.
- **Reference the layout sketch, not other parts' faces.** Faces created late
  in the feature list make fragile references.
- **Name the features that matter.** `Front_Hoop_Tube` reads better in the
  feature list than `Sweep 4`.
- **Use variables for numbers that change.** Tube diameter and wall thickness
  as variables means a material change is one edit.
- **Keep the feature list short.** If a Part Studio is slow to regenerate,
  split it.
- **Set materials**, so the mass and centre of gravity in the assembly mean
  something.
"""),
        ("Assemblies", """\
- **Fix one thing** — usually the frame — and mate everything else to it.
- **Mate to mate connectors** rather than arbitrary edges; they survive
  geometry changes better.
- **Group parts that move together**, so the assembly solves faster.
- **Use standard content for fasteners** instead of modelling them.
- **Check interference through full travel** before calling a design done:
  suspension at full bump and full droop, steering lock to lock.
- **One sub-assembly per subsystem**, so the top-level assembly stays quick to
  open.
"""),
        ("Drawings for the shop", """\
The **Shop** list is where a drawing meets the person cutting the part.

1. **Version the document first**, so the PDF matches a version anyone can
   reopen later.
2. **Put on it what the cutter needs:** tube diameter and wall, cut length,
   cope or notch angles and how they are oriented, and the revision.
3. **Export it as a PDF** and upload it to the part's card in Shop. It shows
   right there on the card, and anyone can download it.
4. **Re-uploading replaces the old drawing** — the previous one is not kept —
   so make sure the revision on the drawing is correct.
5. **Match the name.** The part's name on its Shop card is its Onshape name.
   See *Naming parts*.
"""),
    ],
}


def seed_learn_library_once(db: Session) -> int:
    """Write the starter library the first time this database is used, and
    never again. Returns how many sections it created. Safe on every boot.

    The marker is committed together with the seeded rows, so the two land or
    fail as one. That matters because the obvious alternative -- "seed if the
    table did not exist before create_all" -- breaks if a boot creates the
    tables and then dies before seeding: every later boot sees the table and
    skips the seed for good. (This happened during development: a start-up
    that failed on missing Cloudflare settings left an empty library behind.)

    A database that somehow already has sections but no marker gets the marker
    and nothing else -- the team's own content is never mixed with the starter.
    """
    if db.get(AppMeta, SEEDED_KEY) is not None:
        return 0
    made = 0
    if not db.scalar(select(func.count()).select_from(LearnSection)):
        made = _add_starter_library(db)
    db.add(AppMeta(key=SEEDED_KEY, value=utcnow().isoformat()))
    db.commit()
    return made


def _add_starter_library(db: Session) -> int:
    """Add the starter sections and pages. Flushes; the caller commits."""
    made = 0
    for group, specs in (("library", LIBRARY), ("cad", [CAD_GUIDE])):
        for position, spec in enumerate(specs):
            section = LearnSection(
                title=spec["title"],
                summary=spec["summary"],
                group=group,
                icon=spec["icon"],
                position=position,
            )
            db.add(section)
            db.flush()
            for page_position, (title, body) in enumerate(spec["pages"]):
                db.add(LearnPage(
                    section_id=section.id,
                    title=title,
                    body=body,
                    references=[],
                    position=page_position,
                ))
            made += 1
    db.flush()
    return made
