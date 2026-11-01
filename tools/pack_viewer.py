"""Pack the viewer (template + JS + scene data) into HTML.
Outputs: dist/namma-twin.artifact.html (fragment, for the Artifact tool) and dist/namma-twin.html (standalone)."""
import argparse, base64, json, pathlib, re
ROOT = pathlib.Path(__file__).resolve().parents[1]
JS = ["10_core", "20_gl", "30_nav", "40_app", "50_ui"]

def b64(p): return base64.b64encode(pathlib.Path(p).read_bytes()).decode()
def compact(p): return json.dumps(json.loads(pathlib.Path(p).read_text()), separators=(",", ":"))

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scene", default=str(ROOT / "assets/scenes/demo-block-a")); ap.add_argument("--out", default=str(ROOT / "dist"))
    a = ap.parse_args(); sc = pathlib.Path(a.scene); out = pathlib.Path(a.out); out.mkdir(exist_ok=True, parents=True)
    frames = {}
    cams = json.loads((sc / "scan/cameras.json").read_text())
    for c in cams:
        f = sc / "scan" / c["image"]
        if f.exists(): frames[c["image"]] = "data:image/jpeg;base64," + b64(f)
    data = [("d-visual", b64(sc / "visual.glb")), ("d-semantic", compact(sc / "semantic.json")), ("d-nav", compact(sc / "navgrid.json")),
            ("d-colliders", compact(sc / "colliders.json")), ("d-cloud", b64(sc / "scan/viewer_cloud.bin")), ("d-cameras", compact(sc / "scan/cameras.json")),
            ("d-report", compact(sc / "scan/scan_report.json")), ("d-reg", compact(sc / "scan/registration.json")), ("d-frames", json.dumps(frames, separators=(",", ":")))]
    blob = "\n".join(f'<script type="application/octet-stream" id="{i}">{v}</script>' for i, v in data)
    js = "\n".join((ROOT / f"viewer/js/{n}.js").read_text() for n in JS)
    assert "</script" not in js.lower()
    tpl = (ROOT / "viewer/template.html").read_text()
    frag = tpl.replace("<!--DATA-->", blob).replace("<!--JS-->", f"<script>\n{js}\n</script>")
    (out / "namma-twin.artifact.html").write_text(frag)
    title = re.search(r"<title>(.*?)</title>", tpl).group(1)
    full = ('<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            + frag.replace(f"<title>{title}</title>", f"<title>{title}</title>", 1) + "</head></html>")
    # standalone: wrap properly (head holds title/link/style, body holds the rest)
    m = re.search(r"</style>", frag); head, body = frag[:m.end()], frag[m.end():]
    full = f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">{head}</head><body>{body}</body></html>'
    (out / "namma-twin.html").write_text(full)
    for n in ("namma-twin.artifact.html", "namma-twin.html"): print(n, round((out / n).stat().st_size / 1e6, 2), "MB")

if __name__ == "__main__": main()
