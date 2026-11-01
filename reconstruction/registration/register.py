"""Metric registration of an arbitrary-frame SfM model into the building frame (spec section 10).

Frame convention of the result: Y up, ground plane X-Z, units metres, origin = operator's origin pick
at the ground-floor surface, +X = direction origin->axis pick.

Inputs an operator really has:
  * the model (points + camera poses) in COLMAP's arbitrary frame,
  * two picked model points A (origin) and B (defines +X) with a *measured* distance D (tape/laser),
  * >=1 additional measured distances for validation (strongly recommended; required for REGISTERED).
Up direction is estimated from the cameras' upright orientation, the floor level from the lowest dense
horizontal surface. If no measurement is supplied the model stays UNREGISTERED / ARBITRARY_SCALE and no
metric claim may be made.
"""
from __future__ import annotations
import datetime as dt
import json
import numpy as np

TRANSFORM_VERSION = 1
TOL_REL = 0.02        # a validation measurement must agree within 2 %
TOL_ABS = 0.10        # ...or within 10 cm


class RegistrationError(ValueError):
    pass


def estimate_up(cam_ups):
    u = np.mean(np.asarray(cam_ups), axis=0)
    n = np.linalg.norm(u)
    if n < 0.8:
        raise RegistrationError(f"camera up vectors disagree (|mean|={n:.2f}); cannot estimate gravity direction")
    return u / n


def rot_between(a, b):
    a = a / np.linalg.norm(a); b = b / np.linalg.norm(b)
    v = np.cross(a, b); c = float(a @ b)
    if np.linalg.norm(v) < 1e-9:
        return np.eye(3) if c > 0 else -np.eye(3)
    K = np.array([[0, -v[2], v[1]], [v[2], 0, -v[0]], [-v[1], v[0], 0]])
    return np.eye(3) + K + K @ K * (1.0 / (1.0 + c))


def floor_level(y, bins=400):
    """Lowest strong horizontal-surface peak of the height histogram (model units)."""
    lo, hi = np.percentile(y, 0.5), np.percentile(y, 99.5)
    h, e = np.histogram(y, bins=bins, range=(lo, hi))
    thr = 0.25 * h.max()
    for i in range(1, bins - 1):
        if h[i] >= thr and h[i] >= h[i - 1] and h[i] >= h[i + 1]:
            return float(0.5 * (e[i] + e[i + 1]))
    raise RegistrationError("no dominant horizontal surface found for the floor")


def register(points, cam_centers, cam_ups, origin_pick, axis_pick, axis_dist_m, validations=(), operator="unknown",
             pick_sigma_model=0.0, notes=""):
    """validations: iterable of (pick_a, pick_b, measured_m). Returns a transform dict (see keys below)."""
    if axis_dist_m is None or axis_dist_m <= 0:
        return unregistered(points, "no measured baseline supplied")
    up = estimate_up(cam_ups)
    R_up = rot_between(up, np.array([0.0, 1.0, 0.0]))
    q = np.asarray(points) @ R_up.T
    y_floor = floor_level(q[:, 1])
    A = R_up @ np.asarray(origin_pick, float); B = R_up @ np.asarray(axis_pick, float)
    d_model = float(np.linalg.norm(B - A))
    if d_model < 1e-6:
        raise RegistrationError("origin and axis picks coincide")
    s = axis_dist_m / d_model
    h = B - A; yaw = np.arctan2(h[2], h[0])
    c, sn = np.cos(yaw), np.sin(yaw)
    R_yaw = np.array([[c, 0, sn], [0, 1, 0], [-sn, 0, c]])        # rotates (hx,hz) onto +X
    R = R_yaw @ R_up
    t = -s * (R_yaw @ np.array([A[0], y_floor, A[2]]))
    T = {"R": R, "s": s, "t": t}
    checks = []
    for (pa, pb, meas) in validations:
        est = float(np.linalg.norm(apply(T, np.asarray(pb)[None]) - apply(T, np.asarray(pa)[None])))
        err = est - meas
        ok = abs(err) <= max(TOL_ABS, TOL_REL * meas)
        checks.append({"measured_m": meas, "registered_m": round(est, 4), "error_m": round(err, 4), "rel_error": round(err / meas, 5), "pass": bool(ok)})
    if not checks:
        status = "REGISTERED_UNVALIDATED"
    else:
        status = "REGISTERED" if all(c_["pass"] for c_ in checks) else "FAILED_VALIDATION"
    scale_unc = float(s * np.sqrt(2) * pick_sigma_model / d_model) if pick_sigma_model else None
    return {
        "version": TRANSFORM_VERSION, "status": status,
        "coordinate_system": "building-local-y-up-v1", "units": "metres",
        "origin_description": "operator origin pick projected to the ground-floor surface; +X towards the axis pick",
        "source_frame": "colmap-arbitrary", "scale_factor": s,
        "rotation_matrix": R.tolist(), "translation_vector": t.tolist(),
        "apply": "p_metric = scale_factor * rotation_matrix @ p_model + translation_vector",
        "reference_measurements": {"baseline_m": axis_dist_m, "validation": checks},
        "uncertainty": {"scale_relative_1sigma": (scale_unc / s) if scale_unc is not None else None,
                        "note": "from pick noise only; excludes SfM drift"},
        "floor_height_model_units": y_floor, "estimated_up_model": up.tolist(),
        "operator": operator, "notes": notes, "timestamp_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "metric_claims_allowed": status in ("REGISTERED",),
    }


def unregistered(points, reason):
    return {"version": TRANSFORM_VERSION, "status": "UNREGISTERED", "coordinate_system": "colmap-arbitrary",
            "units": "arbitrary reconstruction units", "reason": reason, "metric_claims_allowed": False,
            "scale_factor": None, "rotation_matrix": None, "translation_vector": None}


def apply(T, P):
    if T.get("status") == "UNREGISTERED" or T.get("rotation_matrix") is None and "R" not in T:
        raise RegistrationError("cannot apply an UNREGISTERED transform; never silently convert arbitrary units to metres")
    R = np.asarray(T["R"] if "R" in T else T["rotation_matrix"]); s = T["s"] if "s" in T else T["scale_factor"]
    t = np.asarray(T["t"] if "t" in T else T["translation_vector"])
    return s * (np.asarray(P) @ R.T) + t


def save(T, path):
    json.dump(T, open(path, "w"), indent=1)
