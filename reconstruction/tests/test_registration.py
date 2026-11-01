import json, os
import numpy as np
import pytest
from reconstruction.registration import colmap_io as cio
from reconstruction.registration import register as reg

SCAN = os.path.join(os.path.dirname(__file__), "..", "..", "assets", "scenes", "demo-block-a", "scan")
pytestmark = pytest.mark.skipif(not os.path.exists(os.path.join(SCAN, "colmap", "images.txt")), reason="run simulate_scan first")


@pytest.fixture(scope="module")
def model():
    P, C, T = cio.read_ply(os.path.join(SCAN, "dense_cloud_colmap_frame.ply"))
    Pgt, _, _ = cio.read_ply(os.path.join(SCAN, "dense_cloud_metric_gt_frame.ply"))
    ims = cio.read_images_txt(os.path.join(SCAN, "colmap", "images.txt"))
    gt = json.load(open(os.path.join(SCAN, "ground_truth_transform.json")))
    return dict(P=P, Pgt=Pgt, ims=ims, gt=gt)


def to_arb(gt, X):
    return gt["scale"] * (np.asarray(X, float) @ np.asarray(gt["R"]).T) + np.asarray(gt["t"])


def pick(m, true_metric_xyz, sigma=0.03, seed=0):
    """Operator clicks the cloud near a known spot: nearest dense point to the true location + click error."""
    rng = np.random.default_rng(seed)
    d = np.linalg.norm(m["Pgt"] - np.asarray(true_metric_xyz), axis=1)
    i = int(np.argmin(d))
    assert d[i] < 0.5, f"no reconstructed point near {true_metric_xyz}"
    return m["P"][i] + rng.normal(0, sigma * m["gt"]["scale"], 3), m["Pgt"][i]


def run(m, baseline_err=0.0, sigma=0.03, val_meas=None):
    A, A_gt = pick(m, (4.0, 0.0, 10.0), sigma, 1)
    B, B_gt = pick(m, (34.0, 0.0, 10.0), sigma, 2)
    D = float(np.linalg.norm(B_gt - A_gt)) + baseline_err                    # "tape measure" of the corridor
    V1, V1g = pick(m, (7.0, 0.0, 3.0), sigma, 3)
    V2, V2g = pick(m, (7.0, 0.0, 14.0), sigma, 4)
    vm = float(np.linalg.norm(V2g - V1g)) if val_meas is None else val_meas
    T = reg.register(m["P"], [i["center"] for i in m["ims"]], [i["up"] for i in m["ims"]], A, B, D,
                     validations=[(V1, V2, vm)], operator="pytest", pick_sigma_model=sigma * m["gt"]["scale"])
    return T, A_gt


def test_registration_recovers_metric_frame(model):
    T, A_gt = run(model)
    assert T["status"] == "REGISTERED" and T["metric_claims_allowed"]
    est = reg.apply(T, model["P"])
    expect = model["Pgt"] - np.array([A_gt[0], 0.0, A_gt[2]])        # origin = operator's origin pick on the floor
    err = np.linalg.norm(est - expect, axis=1)
    assert np.sqrt((err ** 2).mean()) < 0.10, f"RMS {np.sqrt((err**2).mean()):.3f} m"
    assert abs(T["scale_factor"] - 1 / model["gt"]["scale"]) / (1 / model["gt"]["scale"]) < 0.01


def test_up_axis_and_floor_level(model):
    T, A_gt = run(model)
    est = reg.apply(T, model["P"])
    y = est[(est[:, 1] > -0.4) & (est[:, 1] < 0.4)][:, 1]
    h, e = np.histogram(y, bins=80, range=(-0.4, 0.4))
    floor_peak = 0.5 * (e[np.argmax(h)] + e[np.argmax(h) + 1])
    assert abs(floor_peak) < 0.08, floor_peak                            # sensor noise 3-6 cm + pick error
    assert est[:, 1].max() > 7.0                                         # three floors reach ~ 10 m


def test_wrong_tape_measurement_fails_validation(model):
    T, _ = run(model, baseline_err=2.0)                                  # baseline mis-measured by 2 m
    assert T["status"] == "FAILED_VALIDATION" and not T["metric_claims_allowed"]


def test_no_measurement_stays_unregistered(model):
    T = reg.register(model["P"], [i["center"] for i in model["ims"]], [i["up"] for i in model["ims"]],
                     model["P"][0], model["P"][1], None)
    assert T["status"] == "UNREGISTERED"
    with pytest.raises(reg.RegistrationError):
        reg.apply(T, model["P"])


def test_unvalidated_registration_is_not_metric_claim(model):
    A, _ = pick(model, (4.0, 0.0, 10.0)); B, _ = pick(model, (34.0, 0.0, 10.0))
    T = reg.register(model["P"], [i["center"] for i in model["ims"]], [i["up"] for i in model["ims"]], A, B, 32.0)
    assert T["status"] == "REGISTERED_UNVALIDATED" and not T["metric_claims_allowed"]


def test_inconsistent_camera_up_vectors_rejected():
    with pytest.raises(reg.RegistrationError):
        reg.estimate_up([[0, 1, 0], [0, -1, 0], [1, 0, 0], [-1, 0, 0]])
