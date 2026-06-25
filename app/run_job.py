"""
run_job.py — CLI entry point. Thin wrapper over run_job_lib.run_pipeline so the
CLI and the web service share one code path.

  python run_job.py --config ../config/hiab-425k.json --assets ../assets --out ../output
  add --no-captions to skip the API call (offline render test)
  add --upload to push results to Google Drive
  add --ratios 16x9,9x16 to render a subset
"""

import argparse
import json
import os

import run_job_lib as J


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", required=True)
    ap.add_argument("--assets", default="assets")
    ap.add_argument("--out", default="output")
    ap.add_argument("--no-captions", action="store_true")
    ap.add_argument("--upload", action="store_true")
    ap.add_argument("--ratios", default="16x9,9x16,1x1")
    args = ap.parse_args()

    cfg = json.load(open(args.config))
    cfg["_assets_dir"] = os.path.abspath(args.assets)
    job_dir = os.path.join(args.out, cfg["id"])
    ratios = tuple(r.strip() for r in args.ratios.split(",") if r.strip())

    print(f"Rendering {cfg['id']} — ratios: {', '.join(ratios)}")
    result = J.run_pipeline(
        cfg, job_dir, ratios=ratios,
        do_captions=not args.no_captions,
        do_upload=args.upload,
    )

    print("\nDone. Deliverables:")
    for r, p in result["outputs"].items():
        print(f"  {r:5s} -> {p}")
    print(f"  thumb -> {result['thumbnail']}")
    if "captions" in result:
        print("  captions -> captions.json + captions.txt")
    if "drive_url" in result:
        print(f"  Drive -> {result['drive_url']}")


if __name__ == "__main__":
    main()
