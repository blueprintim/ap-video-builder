"""
captions.py — generates per-platform social copy for a crane listing using
the Claude API. The page URL is embedded per-platform according to each
channel's link conventions.

Channels: YouTube, Instagram, Facebook, X, Pinterest, Google Business Profile.

Requires env var ANTHROPIC_API_KEY. Model is configurable; defaults to a
current Sonnet for cost/quality balance on this structured writing task.
"""

import json
import os
import urllib.request

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-4-6"

PLATFORM_RULES = """
Write social copy for SIX platforms for a piece of heavy-equipment inventory.
Return STRICT JSON only — an object with keys: youtube, instagram, facebook,
x, pinterest, google_business. No markdown, no preamble.

Rules per platform:
- youtube: description-box copy. The URL IS clickable — include it on its own
  line prefixed with "Get pricing: ". Include phone. End with 5-7 relevant
  hashtags on one line.
- instagram: caption. The URL is NOT clickable in captions — do NOT paste the
  raw URL; instead direct to "Link in bio" and/or "DM us". Use short
  checkmark bullet lines for specs. End with 8-12 hashtags.
- facebook: the URL IS clickable — include it inline after a CTA arrow. Fuller,
  warmer tone. No hashtag wall (0-2 max).
- x: must be <= 280 characters INCLUDING the URL. Punchy. The URL is clickable.
  1-3 hashtags only.
- pinterest: keyword-rich description for search. Include the raw URL at the
  end (it becomes the Pin destination). No hashtags needed.
- google_business: short CTA-driven post. Include phone and the raw URL inline.

Keep all specs accurate to what is provided. Do not invent numbers. Marketing
phrasing around the specs is welcome but must not overstate. Use the exact page
URL provided, unmodified.
"""


def generate_captions(cfg, model=None):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    model = model or os.environ.get("CAPTION_MODEL", DEFAULT_MODEL)

    facts = {
        "title": cfg["title"],
        "subtitle": cfg["subtitle"],
        "specs": cfg.get("specs_for_copy", ""),
        "phone": cfg["phone"],
        "website": cfg["website"],
        "page_url": cfg["page_url"],
        "dealer": cfg.get("dealer", "Atlas Polar"),
    }

    user_content = (
        PLATFORM_RULES
        + "\n\nListing facts (JSON):\n"
        + json.dumps(facts, indent=2)
    )

    body = {
        "model": model,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": user_content}],
    }
    req = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode(),
        headers={
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=90) as resp:
        data = json.loads(resp.read())

    text = "".join(b["text"] for b in data["content"] if b.get("type") == "text")
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.strip()
    return json.loads(text)
