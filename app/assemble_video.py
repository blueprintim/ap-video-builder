"""
assemble_video.py — merges opening slide + main video + closing slide into a
final MP4, in a given aspect ratio, with the voiceover laid over the start
of the main video.

Timing rules (agreed with client):
  - Opening slide: 2 seconds, SILENT
  - Main video: plays full length (1-3 min). Voiceover overlaid starting at the
    video's first frame; voiceover is ~60s and simply ends — video continues
    silent (original audio choice configurable) until it finishes.
  - Closing slide: 3 seconds, SILENT
  - Bookend slides carry no audio.

The main video is scaled/cropped to the target aspect ratio so all three
masters share one source. Original video audio is dropped by default (the
voiceover is the only narration); set keep_source_audio=True to mix it under.
"""

import json
import os
import subprocess

RATIO_DIMS = {
    "16x9": (1920, 1080),
    "9x16": (1080, 1920),
    "1x1": (1080, 1080),
}

OPENING_SEC = 2.0
CLOSING_SEC = 3.0


def _run(cmd):
    # Force ffmpeg/libs to use a roomy temp dir on disk rather than a small
    # RAM-backed tmpfs (/dev/shm), which otherwise causes spurious
    # "No space left on device" errors on long 1080p filter graphs.
    env = dict(os.environ)
    tmp = env.get("RENDER_TMPDIR") or os.path.join(os.getcwd(), ".fftmp")
    os.makedirs(tmp, exist_ok=True)
    env["TMPDIR"] = tmp
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg failed:\n{' '.join(cmd)}\n\n{p.stderr[-2000:]}")
    return p


def _probe_duration(path):
    p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
              "-of", "json", path])
    return float(json.loads(p.stdout)["format"]["duration"])


def _slide_to_clip(png, seconds, W, H, fps, out):
    """Turn a still PNG into a silent video clip of N seconds."""
    _run([
        "ffmpeg", "-y", "-loop", "1", "-i", png,
        "-f", "lavfi", "-i", f"anullsrc=channel_layout=stereo:sample_rate=48000",
        "-t", str(seconds),
        "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={fps}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest",
        out
    ])
    return out


def _prep_main(video, voiceover, W, H, fps, keep_source_audio, out):
    """Scale/crop the main video to WxH and overlay the voiceover from t=0.
    Voiceover ends naturally; video continues to its full length."""
    vdur = _probe_duration(video)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},setsar=1,fps={fps}")
    if keep_source_audio:
        # mix source audio (lowered) with voiceover, bounded to video length
        cmd = [
            "ffmpeg", "-y", "-i", video, "-i", voiceover,
            "-filter_complex",
            f"[0:v]{vf}[v];"
            f"[0:a]volume=0.25[a0];"
            f"[1:a]apad=whole_dur={vdur}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:dropout_transition=0[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{vdur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            out
        ]
    else:
        # voiceover only; pad with silence up to the exact video length
        cmd = [
            "ffmpeg", "-y", "-i", video, "-i", voiceover,
            "-filter_complex",
            f"[0:v]{vf}[v];[1:a]apad=whole_dur={vdur}[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{vdur}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac",
            out
        ]
    _run(cmd)
    return out


def _concat(clips, out):
    """Concatenate clips that share codec/params via the concat demuxer."""
    listfile = out + ".txt"
    with open(listfile, "w") as f:
        for c in clips:
            f.write(f"file '{os.path.abspath(c)}'\n")
    _run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listfile,
        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", out
    ])
    os.remove(listfile)
    return out


def assemble(ratio, opening_png, closing_png, main_video, voiceover,
             workdir, out_path, fps=30, keep_source_audio=False):
    W, H = RATIO_DIMS[ratio]
    op_clip = _slide_to_clip(opening_png, OPENING_SEC, W, H, fps,
                             os.path.join(workdir, f"op_{ratio}.mp4"))
    main_clip = _prep_main(main_video, voiceover, W, H, fps, keep_source_audio,
                           os.path.join(workdir, f"main_{ratio}.mp4"))
    cl_clip = _slide_to_clip(closing_png, CLOSING_SEC, W, H, fps,
                             os.path.join(workdir, f"cl_{ratio}.mp4"))
    _concat([op_clip, main_clip, cl_clip], out_path)
    return out_path
