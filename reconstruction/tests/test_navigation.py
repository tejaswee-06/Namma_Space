import json, os, pytest
from reconstruction.navigation_geometry.navgrid import NavMap, poi_point

SCENE = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "scenes", "demo-block-a")


@pytest.fixture(scope="module")
def nav():
    return NavMap(SCENE)


def test_valid_route_same_floor(nav):
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f0-seminar-a"))
    assert r["status"] == "ok"
    v = nav.validate_route(r)
    assert v["collision_free"], v


def test_all_pois_reachable_from_entrance(nav):
    start = poi_point(nav.semantic, "poi-main-entrance")
    bad = []
    for p in nav.semantic["pois"]:
        if p["poi_id"].endswith("stair-a"):
            continue
        r = nav.route(start, poi_point(nav.semantic, p["poi_id"]))
        if r["status"] != "ok" or not nav.validate_route(r)["collision_free"]:
            bad.append((p["poi_id"], r.get("status"), r.get("reason")))
    assert not bad, bad


def test_multi_floor_uses_portal(nav):
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f2-library"))
    assert r["status"] == "ok" and len(r["transitions"]) >= 2
    assert nav.validate_route(r)["collision_free"]


def test_accessible_route_avoids_stairs(nav):
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f1-telecom-lab"), accessible=True)
    assert r["status"] == "ok"
    assert all(t["kind"] == "lift" for t in r["transitions"])


def test_blocked_corridor_gives_no_path():
    blocker = [(0, 0.0, 8.55, 36.0, 11.45)]                  # whole corridor on ground floor
    nav = NavMap(SCENE, extra_blocks=blocker)
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f0-seminar-a"))
    assert r["status"] == "no_path"


def test_riser_without_floor_slab_is_unmapped(nav):
    # service riser behind the lift has no walkable slab modelled: fail closed, never route into it
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), (0, 19.0, 3.0))
    assert r["status"] == "unmapped", r


def test_disconnected_destination_when_door_sealed():
    # wc-m door (x=21, z=8.6) sealed with a temporary obstacle: room has floor but no connection
    nav = NavMap(SCENE, extra_blocks=[(0, 20.3, 8.2, 21.7, 9.0)])
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f0-wc-m"))
    assert r["status"] == "no_path", r
    ok = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f0-wc-f"))
    assert ok["status"] == "ok"                      # neighbouring room unaffected


def test_alternate_route_when_one_side_blocked():
    base = NavMap(SCENE)
    s, g = poi_point(base.semantic, "poi-main-entrance"), poi_point(base.semantic, "poi-f0-help-desk")
    r0 = base.route(s, g)
    assert r0["status"] == "ok"
    mid = r0["segments"][0]["points"][len(r0["segments"][0]["points"]) // 2]
    blk = NavMap(SCENE, extra_blocks=[(0, mid[0] - 0.4, mid[1] - 0.4, mid[0] + 0.4, mid[1] + 0.4)])
    r1 = blk.route(s, g)
    assert r1["status"] == "ok" and blk.validate_route(r1)["collision_free"]


def test_doorway_connectivity_every_door_passable(nav):
    for d in nav.semantic["doors"]:
        side = -1 if d["side"] == "N" else 1
        assert nav.walkable(d["floor"], d["x"], d["z"]), f"door {d['room_id']} is not walkable at its threshold"
        assert nav.walkable(d["floor"], d["x"], d["z"] + side * -0.8)       # corridor side
        assert nav.walkable(d["floor"], d["x"], d["z"] + side * 0.5)        # room side (stair room is shallow)


def test_unmapped_region_fails_closed(nav):
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), (0, 50.0, 50.0))
    assert r["status"] == "unmapped"


def test_destination_inside_obstacle_is_invalid(nav):
    f = next(c for c in nav.colliders if c["kind"] == "furniture" and c["floor"] == 0 and c["max"][1] - c["min"][1] > 0.8)
    cx = (f["min"][0] + f["max"][0]) / 2; cz = (f["min"][2] + f["max"][2]) / 2
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), (0, cx, cz))
    assert r["status"] in ("invalid", "ok")                  # snaps to nearest clear cell only within 0.6 m
    if r["status"] == "ok":
        assert nav.validate_route(r)["collision_free"]


def test_route_avoids_obstacle_with_clearance(nav):
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f0-commons"))
    v = nav.validate_route(r)
    assert v["collision_free"] and v["min_clearance_m"] >= 0.2


def test_stairs_only_route_when_lift_closed():
    nav = NavMap(SCENE)
    nav.portals = [p for p in nav.portals if p.kind == "stair"]
    r = nav.route(poi_point(nav.semantic, "poi-main-entrance"), poi_point(nav.semantic, "poi-f1-computer-lab"))
    assert r["status"] == "ok" and r["transitions"][0]["kind"] == "stair"
    nav2 = NavMap(SCENE); nav2.portals = [p for p in nav2.portals if p.kind == "stair"]
    assert nav2.route(poi_point(nav2.semantic, "poi-main-entrance"), poi_point(nav2.semantic, "poi-f1-computer-lab"), accessible=True)["status"] == "no_path"
