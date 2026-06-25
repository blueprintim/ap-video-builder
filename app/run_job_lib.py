"""
run_job_lib.py — the render pipeline as an importable function, shared by the
CLI (run_job.py) and the web service (server.py) so there's a single code path.
"""

import json
import os
import shutil

from render_slides import render_all_slides, RATIOS
from assemble_video import assemble


def _load_brand():
    proj_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    brand = json.load(open(os.path.join(proj_root, "config", "brand.json")))
    for k in ("white_logo", "color_logo"):
        if k in brand and not os.path.isabs(brand[k]):
            brand[k] = os.path.join(proj_root, brand[k])
    return brand


def _write_captions_files(caps, out_dir):
    with open(os.path.join(out_dir, "captions.json"), "w") as f:
        json.dump(caps, f, indent=2, ensure_ascii=False)
    order = [
        ("YouTube", "youtube"), ("Instagram", "instagram"),
        ("Facebook", "facebook"), ("X", "x"),
        ("Pinterest", "pinterest"), ("Google Business Profile", "google_business"),
    ]
    lines = []
    for label, key in order:
        lines.append(f"===== {label} =====\n")
        lines.append((caps.get(key, "") or "").strip() + "\n\n")
    with open(os.path.join(out_dir, "captions.txt"), "w") as f:
        f.write("".join(lines))


def run_pipeline(cfg, job_dir, ratios=("16x9", "9x16", "1x1"),
                 do_captions=True, do_upload=False):
    """Render slides, assemble videos, generate captions, optionally upload.
    cfg must include photo/video/voiceover filenames and either _assets_dir or
    an 'assets' path. Returns a result dict with output paths + drive_url."""
    brand = _load_brand()
    assets_dir = cfg.get("_assets_dir") or cfg.get("assets") or "assets"

    def r(p):
        return p if os.path.isabs(p) else os.path.join(assets_dir, p)
    cfg["_photo_path"] = r(cfg["photo"])
    cfg["_video_path"] = r(cfg["video"])
    # Optional per-ratio photos: photo_9x16, photo_1x1, photo_16x9
    for ratio in ("16x9", "9x16", "1x1"):
        key = f"photo_{ratio}"
        if cfg.get(key):
            cfg[f"_photo_path_{ratio}"] = r(cfg[key])

    out_dir = os.path.join(job_dir, "deliverables")
    work = os.path.join(out_dir, "_work")
    os.makedirs(work, exist_ok=True)

    # Voiceover source. Two modes:
    #   voiceover_source == "elevenlabs": generate the MP3 from cfg["script"]
    #       (the approved script) via the ElevenLabs API.
    #   otherwise: use the supplied audio file at cfg["voiceover"] (manual flow).
    vo_source = cfg.get("voiceover_source", "file")
    if vo_source == "elevenlabs":
        if not cfg.get("script", "").strip():
            raise RuntimeError(
                "voiceover_source is 'elevenlabs' but no 'script' provided in config")
        from tts import synthesize
        vo_path = os.path.join(work, "voiceover.mp3")
        synthesize(
            cfg["script"], vo_path,
            voice_id=cfg.get("voice_id"),
            model_id=cfg.get("tts_model"),
        )
        cfg["_voiceover_path"] = vo_path
    else:
        cfg["_voiceover_path"] = r(cfg["voiceover"])

    slides = render_all_slides(cfg, brand, work)
    thumb_final = os.path.join(out_dir, "thumbnail.png")
    shutil.copy(slides["thumbnail"], thumb_final)

    finals = {}
    for ratio in ratios:
        out_mp4 = os.path.join(out_dir, f"{cfg['id']}_{ratio}.mp4")
        assemble(ratio, slides[f"opening_{ratio}"], slides[f"closing_{ratio}"],
                 cfg["_video_path"], cfg["_voiceover_path"], work, out_mp4,
                 keep_source_audio=cfg.get("keep_source_audio", False))
        finals[ratio] = out_mp4

    result = {"outputs": finals, "thumbnail": thumb_final,
              "message": "render complete"}

    if do_captions:
        from captions import generate_captions
        caps = generate_captions(cfg)
        _write_captions_files(caps, out_dir)
        result["captions"] = caps

    if do_upload:
        from drive_upload import upload_job_folder
        result["drive_url"] = upload_job_folder(out_dir, cfg["id"])

    return result
