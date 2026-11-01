"""Register the SIMULATED scan and store the evidence (scan/registration.json).
Operator inputs are emulated: nearest reconstructed point to a known spot + 3 cm click error, tape distance
measured on the true model. The hidden ground truth is used ONLY to report residuals (impossible on a real site)."""
import json, os, sys
import numpy as np
from . import colmap_io as cio, register as reg

def main(scan="assets/scenes/demo-block-a/scan"):
    P, C, T = cio.read_ply(f"{scan}/dense_cloud_colmap_frame.ply"); Pgt, _, _ = cio.read_ply(f"{scan}/dense_cloud_metric_gt_frame.ply")
    ims = cio.read_images_txt(f"{scan}/colmap/images.txt"); gt = json.load(open(f"{scan}/ground_truth_transform.json"))
    rng = np.random.default_rng(5)
    def pick(xyz):
        i = int(np.argmin(np.linalg.norm(Pgt - np.asarray(xyz), axis=1)))
        return P[i] + rng.normal(0, 0.03 * gt["scale"], 3), Pgt[i]
    A, Ag = pick((4, 0, 10)); B, Bg = pick((34, 0, 10)); V1, V1g = pick((7, 0, 3)); V2, V2g = pick((7, 0, 14))
    Tr = reg.register(P, [i["center"] for i in ims], [i["up"] for i in ims], A, B, float(np.linalg.norm(Bg - Ag)),
                      validations=[(V1, V2, float(np.linalg.norm(V2g - V1g)))], operator="simulated-operator", pick_sigma_model=0.03 * gt["scale"],
                      notes="SIMULATED capture; picks emulated; tape distances taken from the synthetic model")
    est = reg.apply(Tr, P); exp = Pgt - np.array([Ag[0], 0, Ag[2]]); err = np.linalg.norm(est - exp, axis=1)
    Tr["simulation_residuals_vs_hidden_truth"] = {"rms_m": round(float(np.sqrt((err ** 2).mean())), 4), "p95_m": round(float(np.percentile(err, 95)), 4),
                                                   "note": "only computable because the scan is simulated"}
    reg.save(Tr, f"{scan}/registration.json"); print(json.dumps({k: Tr[k] for k in ("status", "scale_factor", "simulation_residuals_vs_hidden_truth")}, indent=1)); print(Tr["reference_measurements"])
if __name__ == "__main__": main()
