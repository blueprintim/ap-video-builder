"""
tts.py — generates a voiceover MP3 from script text using the ElevenLabs API.

Endpoint: POST https://api.elevenlabs.io/v1/text-to-speech/{voice_id}
Auth:     header  xi-api-key: <ELEVENLABS_API_KEY>
Output:   MP3 (default)

For crane narration we default to the high-quality multilingual model rather
than a low-latency model — latency is irrelevant for batch voiceovers, and
quality matters. Scripts (~900 chars) are far under the model's input limit, so
no chunking/stitching is needed.

Env:
  ELEVENLABS_API_KEY   (required)
  ELEVENLABS_VOICE_ID  (default voice; can be overridden per job in config)
  ELEVENLABS_MODEL     (default 'eleven_multilingual_v2')
"""

import json
import os
import urllib.request
import urllib.error

API_BASE = "https://api.elevenlabs.io/v1/text-to-speech"
DEFAULT_MODEL = "eleven_multilingual_v2"
# A widely-available default premade voice; override with your chosen voice id.
DEFAULT_VOICE = "21m00Tcm4TlvDq8ikWAM"


def synthesize(script_text, out_mp3, voice_id=None, model_id=None,
               stability=0.5, similarity_boost=0.75, style=0.0):
    """Generate speech from script_text and write it to out_mp3.
    Returns out_mp3 on success; raises on failure."""
    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise RuntimeError("ELEVENLABS_API_KEY not set")

    voice_id = voice_id or os.environ.get("ELEVENLABS_VOICE_ID") or DEFAULT_VOICE
    model_id = model_id or os.environ.get("ELEVENLABS_MODEL") or DEFAULT_MODEL

    if not script_text or not script_text.strip():
        raise RuntimeError("empty script_text")

    url = f"{API_BASE}/{voice_id}"
    body = {
        "text": script_text,
        "model_id": model_id,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": similarity_boost,
            "style": style,
        },
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={
            "xi-api-key": api_key,
            "content-type": "application/json",
            "accept": "audio/mpeg",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            audio = resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:500]
        raise RuntimeError(f"ElevenLabs API error {e.code}: {detail}")

    if not audio or len(audio) < 1024:
        raise RuntimeError("ElevenLabs returned no/too-little audio")

    with open(out_mp3, "wb") as f:
        f.write(audio)
    return out_mp3
