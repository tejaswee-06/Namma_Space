"""Layout specification for the synthetic NAMMA demo building ("Block A").

SYNTHETIC / DESIGNED. Not a survey or scan of any real building.
Coordinates: metres, Y up, ground plane X-Z. Origin = south-west outer corner at ground level.
"""
from __future__ import annotations
from dataclasses import dataclass, field

H = 3.6          # floor-to-floor
SLAB = 0.3       # structural slab thickness (below finished floor level)
LEN_X = 36.0
LEN_Z = 20.0
COR_Z0, COR_Z1 = 8.6, 11.4   # corridor band (z)
FLOORS = 3
BUILDING_ID = "bld-namma-demo"
SCENE_ID = "demo-block-a"
SCENE_VERSION = "0.3.0-synthetic"


@dataclass
class RoomSpec:
    slug: str
    name: str
    floor: int
    side: str                 # 'N' (north band, z < corridor) | 'S' (south band)
    x0: float
    x1: float
    kind: str                 # layout / furniture generator key
    category: str             # POI category
    aliases: list[str] = field(default_factory=list)
    door_w: float = 1.2
    door: str = "swing"       # swing | arch | slide | double
    front: str = "solid"      # corridor-facing wall: solid | glass
    floor_mat: str = "tile"
    desc: str = ""
    z0_override: float | None = None
    z1_override: float | None = None

    @property
    def id(self) -> str:
        return f"f{self.floor}-{self.slug}"

    @property
    def z0(self) -> float:
        if self.z0_override is not None:
            return self.z0_override
        return 0.0 if self.side == "N" else COR_Z1

    @property
    def z1(self) -> float:
        if self.z1_override is not None:
            return self.z1_override
        return COR_Z0 if self.side == "N" else LEN_Z

    @property
    def door_x(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def door_z(self) -> float:
        return COR_Z0 if self.side == "N" else COR_Z1


def rooms() -> list[RoomSpec]:
    R = RoomSpec
    out: list[RoomSpec] = []
    for f in range(FLOORS):
        # core (identical every floor)
        out += [
            R("stair-a", "Staircase A", f, "N", 14, 18, "stair", "Stairs", ["stairs", "staircase", "steps"], 1.2, "swing", "solid", "concrete"),
            R("lift", "Lift", f, "N", 18, 20, "lift", "Lift", ["elevator", "lift", "accessible lift"], 1.2, "slide", "solid", "terrazzo",
              z0_override=6.4),
            R("wc-m", "Washroom (Men)", f, "N", 20, 22, "wc", "Washroom", ["restroom", "toilet", "men", "gents", "wc"], 0.95, "swing", "solid", "tile"),
            R("wc-f", "Washroom (Women)", f, "N", 22, 24, "wc", "Washroom", ["restroom", "toilet", "women", "ladies", "wc"], 0.95, "swing", "solid", "tile"),
            R("corridor", "Main Corridor", f, "N", 0, LEN_X, "corridor", "Circulation", ["hall", "corridor", "passage"], 0, "arch", "solid", "terrazzo",
              z0_override=COR_Z0, z1_override=COR_Z1),
        ]
    out += [
        # ---- Ground floor
        R("seminar-a", "Seminar Hall A", 0, "N", 0, 14, "seminar", "Lecture", ["lecture hall", "auditorium", "seminar", "hall a"], 1.8, "double", "solid", "carpet",
          desc="Tiered-seating style seminar hall with projection wall."),
        R("admin-office", "Administrative Office", 0, "N", 24, 36, "office", "Office", ["admin", "administration", "office"], 1.2, "swing", "glass", "carpet"),
        R("lobby", "Entrance Lobby & Reception", 0, "S", 0, 14, "lobby", "Entrance", ["reception", "lobby", "main entrance", "front desk", "entrance"], 2.6, "arch", "glass", "terrazzo",
          desc="Main entrance, reception desk and waiting area."),
        R("commons", "Student Commons & Cafe", 0, "S", 14, 30, "commons", "Dining", ["cafe", "cafeteria", "canteen", "food court", "student commons"], 2.4, "arch", "glass", "oak",
          desc="Informal seating, cafe counter and vending."),
        R("help-desk", "Security & Help Desk", 0, "S", 30, 36, "helpdesk", "Service", ["help desk", "security", "enquiry", "information"], 1.2, "swing", "glass", "tile"),
        # ---- First floor
        R("electronics-lab", "Electronics Lab 1", 1, "N", 0, 14, "lab", "Laboratory", ["electronics lab", "circuits lab", "ece lab", "lab 1"], 1.4, "swing", "glass", "tile",
          desc="Bench-based electronics practical lab."),
        R("telecom-lab", "Telecommunications Lab", 1, "N", 24, 36, "lab", "Laboratory", ["telecom lab", "rf lab", "communication lab", "antenna lab"], 1.4, "swing", "glass", "tile"),
        R("computer-lab", "Computer Lab", 1, "S", 0, 12, "computerlab", "Laboratory", ["computer lab", "it lab", "programming lab", "cs lab"], 1.4, "swing", "glass", "carpet"),
        R("faculty-offices", "Faculty Offices", 1, "S", 12, 24, "office", "Office", ["faculty", "staff room", "professors", "teachers room"], 1.2, "swing", "glass", "carpet"),
        R("project-lab", "Project Lab", 1, "S", 24, 36, "lab", "Laboratory", ["project lab", "makerspace", "workshop", "embedded lab"], 1.4, "swing", "glass", "tile"),
        # ---- Second floor
        R("conference", "Conference Room", 2, "N", 0, 14, "conference", "Meeting", ["meeting room", "board room", "conference"], 1.4, "swing", "glass", "carpet"),
        R("dept-office", "Department Office", 2, "N", 24, 36, "office", "Office", ["department", "hod office", "dept office", "etc department"], 1.2, "swing", "glass", "carpet"),
        R("iot-lab", "IoT Research Lab", 2, "S", 0, 14, "lab", "Laboratory", ["iot lab", "research lab", "sensors lab"], 1.4, "swing", "glass", "tile"),
        R("library", "Library & Reading Room", 2, "S", 14, 28, "library", "Library", ["library", "reading room", "books", "study"], 2.0, "double", "glass", "carpet"),
        R("lounge", "Terrace Lounge", 2, "S", 28, 36, "lounge", "Dining", ["lounge", "terrace", "break room", "chill area"], 1.4, "swing", "glass", "oak"),
    ]
    return out
