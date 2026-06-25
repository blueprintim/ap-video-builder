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

    # A system prompt that hard-constrains the output to a single JSON object.
    system = (
        "You output ONLY a single valid JSON object and nothing else. "
        "No markdown, no code fences, no preamble. The object has exactly these "
        "string keys: youtube, instagram, facebook, x, pinterest, google_business. "
        "CRITICAL: inside string values, every double-quote character must be "
        "escaped as \\\". Prefer straight apostrophes for measurements (use 71'5\\\" "
        "style only if you escape the inch mark). Do not include literal newlines "
        "that break JSON; use \\n for line breaks within a value."
    )

    def _call(extra_user=None):
        msgs = [{"role": "user", "content": user_content}]
        if extra_user:
            msgs.append({"role": "user", "content": extra_user})
        body = {
            "model": model,
            "max_tokens": 2000,
            "system": system,
            "messages": msgs,
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
        return "".join(b["text"] for b in data["content"]
                       if b.get("type") == "text").strip()

    def _strip_fences(t):
        t = t.strip()
        if t.startswith("```"):
            t = t.split("```", 2)[1]
            if t.startswith("json"):
                t = t[4:]
            t = t.strip()
        return t

    def _extract_object(t):
        # Pull just the outermost {...} in case there's stray text around it.
        i, j = t.find("{"), t.rfind("}")
        return t[i:j + 1] if (i != -1 and j != -1 and j > i) else t

    KEYS = ["youtube", "instagram", "facebook", "x", "pinterest", "google_business"]

    def _salvage(t):
        # Last resort: pull each platform's value by key, tolerant of unescaped
        # quotes inside values. Captures everything up to the next "key": or end.
        import re
        out = {}
        for idx, k in enumerate(KEYS):
            nexts = "|".join(f'"{n}"\\s*:' for n in KEYS if n != k)
            pat = rf'"{k}"\s*:\s*"(.*?)"\s*(?:,\s*(?:{nexts})|}}\s*$)'
            m = re.search(pat, t, re.DOTALL)
            if m:
                out[k] = m.group(1).replace('\\n', '\n').replace('\\"', '"').strip()
        return out

    # Attempt 1: normal parse
    text = _strip_fences(_call())
    try:
        return json.loads(_extract_object(text))
    except json.JSONDecodeError:
        pass

    # Attempt 2: ask the model to fix its own JSON
    fix_msg = (
        "Your previous response was not valid JSON (a quote or delimiter was "
        "unescaped). Return the SAME content as a single strictly-valid JSON "
        "object, with every internal double-quote escaped as \\\". Output only "
        "the JSON object."
    )
    text2 = _strip_fences(_call(extra_user=fix_msg))
    try:
        return json.loads(_extract_object(text2))
    except json.JSONDecodeError:
        pass

    # Attempt 3: salvage by regex so the job still completes with captions
    salvaged = _salvage(_extract_object(text2)) or _salvage(_extract_object(text))
    if salvaged:
        return salvaged

    # If everything failed, raise with a short preview for debugging
    raise RuntimeError(
        "Caption JSON could not be parsed after retries. "
        f"First 200 chars: {text[:200]!r}")
