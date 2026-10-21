"""Small wrapper around Gemini: one client, model fallback, JSON output, retries."""
import json
import logging
import os
import re
import time

log = logging.getLogger("pulse.llm")

MODEL_CANDIDATES = [os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite"), "gemini-flash-lite-latest"]
_client = None
_working_model = None


def get_key() -> str | None:
    key = os.environ.get("GEMINI_API_KEY")
    if key:
        return key
    try:  # Streamlit secrets, when running inside the app
        import streamlit as st
        return st.secrets.get("GEMINI_API_KEY")
    except Exception:
        pass
    try:  # local secrets file, when running from the command line
        import tomllib
        from pathlib import Path
        p = Path(__file__).resolve().parent.parent / ".streamlit" / "secrets.toml"
        if p.exists():
            return tomllib.loads(p.read_text()).get("GEMINI_API_KEY") or None
    except Exception:
        pass
    return None


def available() -> bool:
    return bool(get_key())


def _get_client():
    global _client
    if _client is None:
        from google import genai
        from google.genai import types
        _client = genai.Client(api_key=get_key(), http_options=types.HttpOptions(timeout=120000))
    return _client


def generate(prompt: str, *, json_mode: bool = False, temperature: float = 0.2,
             max_retries: int = 4) -> str:
    """Return the model's text. Raises RuntimeError if every model fails."""
    global _working_model
    from google.genai import types
    client = _get_client()
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json" if json_mode else "text/plain",
    )
    models = list(dict.fromkeys(([_working_model] if _working_model else []) + MODEL_CANDIDATES))
    dead = set()
    last_err = None
    for attempt in range(max_retries):
        for model in models:  # alternate models so one busy model does not stall the run
            if model in dead:
                continue
            try:
                resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
                _working_model = model
                return (resp.text or "").strip()
            except Exception as e:  # rate limits and transient errors get a backoff
                last_err = e
                msg = str(e)
                log.warning("Gemini call failed (%s, attempt %d): %s", model, attempt + 1, msg[:200])
                if "404" in msg or "not found" in msg.lower():
                    dead.add(model)  # model retired
                    continue
                m = re.search(r"retry in ([\d.]+)s", msg)
                time.sleep(min(float(m.group(1)) + 1 if m else 4 * (attempt + 1), 60))
    raise RuntimeError(f"Gemini unavailable: {last_err}")


def generate_json(prompt: str, **kw):
    text = generate(prompt, json_mode=True, **kw)
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    return json.loads(text)
