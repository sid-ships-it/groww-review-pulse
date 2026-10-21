"""Steps 2 and 3: weekly product pulse and fee explainer.

The model only writes the short judgement parts (theme one-liners, the key
observation, action ideas, explainer wording). Numbers, quotes, links and
structure come from code, and every output is checked before it is used:
- pulse: at most 250 words, quotes word for word from the reviews CSV
- explainer: at most 6 bullets, every number must appear in the verified facts
"""
import datetime as dt
import json
import re
from pathlib import Path

from . import llm

ROOT = Path(__file__).resolve().parent.parent
FACTS_JSON = ROOT / "data" / "fee_facts.json"
OUTPUTS_JSON = ROOT / "data" / "outputs.json"
PULSE_MAX_WORDS = 250
QUOTE_MAX_WORDS = 22
MAX_BULLETS = 6


def word_count(md: str) -> int:
    text = re.sub(r"[#>*_`|]", " ", md)
    return len([w for w in text.split() if re.search(r"\w", w)])


def short_quote(text: str, max_words: int = QUOTE_MAX_WORDS) -> str:
    """A verbatim prefix of the review: whole sentences if they fit, else cut at a word boundary."""
    if len(text.split()) <= max_words:
        return text
    sentences = re.split(r"(?<=[.!?])\s+", text)
    kept = []
    for sent in sentences:
        if len(" ".join(kept + [sent]).split()) > max_words:
            break
        kept.append(sent)
    if kept and len(" ".join(kept).split()) >= max_words // 2:
        return " ".join(kept) + " ..."
    return " ".join(text.split()[:max_words]).rstrip(",;:.!") + "..."


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


def _fmt_day(s: str) -> str:
    d = dt.date.fromisoformat(s)
    return f"{d.day} {d.strftime('%b')}"


# ---------------------------------------------------------------- step 2
def _theme_samples(a: dict, per_theme: int = 12) -> dict:
    """A few recent critical reviews per top theme, so the model can say what users report."""
    try:
        from .analysis import load_labels
        lab = load_labels()
    except Exception:  # noqa: BLE001
        return {}
    out = {}
    for t in a["top_themes"]:
        g = lab[(lab["theme_id"] == t["id"]) & lab["sentiment"].isin(["neg", "mixed"]) & (lab["words"] >= 10)]
        g = g.sort_values("date", ascending=False).head(per_theme)
        out[t["name"]] = [x[:220] for x in g["text"]]
    return out


def weekly_pulse(a: dict) -> dict:
    top = a["top_themes"]
    fee = a["fee_issue"]
    ws, we = a["window"]["latest_week"].split(" to ")
    stats = [{"name": t["name"], "share_of_analysed": _pct(t["share"]), "avg_rating": t["avg_rating"],
              "negative_or_mixed": _pct(t["negative_share"]),
              "latest_week_vs_prior_9_weeks": f"{_pct(t['latest_week_share'])} vs {_pct(t['prior_weeks_share'])} "
                                              f"({'up' if t['latest_week_share'] > t['prior_weeks_share'] else 'down'})"}
             for t in top]
    weekly_fee = fee["weekly_issue_reviews"]
    prompt = f"""You write a weekly product pulse for the Groww product team from app-review analysis.
Plain, specific, no hype, no em dashes. Use only the numbers given.

Top 3 themes: {json.dumps(stats)}
All 5 themes: {json.dumps([{"name": t["name"], "share": _pct(t["share"])} for t in a["themes"]])}
Most misunderstood fee: {fee.get("name")}: {fee.get("summary")}
Fee reviews: {fee["issue_reviews"]} reviews about this fee, {fee["issue_confused_reviews"]} of them confused or surprised; avg rating {fee["issue_avg_rating"]}.
Weekly count of reviews on this fee (week start: count): {json.dumps(weekly_fee)}
Quotes that will be shown: {json.dumps([q["text"][:200] for q in a["quotes"]])}
Recent critical reviews per top theme: {json.dumps(_theme_samples(a), ensure_ascii=False)}

Return JSON only:
{{"theme_lines": ["<= 14 words: what users report in theme 1 (specific problems, not the numbers)", "... theme 2", "... theme 3"],
  "observation": "<= 35 words: lead with what got worse in the latest week (themes marked up), with the numbers, then tie it to the fee confusion",
  "actions": ["<= 14 words: a concrete, testable idea for the product team", "...", "..."]}}"""
    for attempt in range(3):
        out = llm.generate_json(prompt)
        md = _assemble_pulse(a, out, ws, we)
        if word_count(md) <= PULSE_MAX_WORDS:
            break
        prompt += "\nThe last draft was too long. Use fewer words in every field."
    else:  # last resort: drop quote length until it fits
        md = _assemble_pulse(a, out, ws, we, quote_words=15)
    return {"markdown": md, "words": word_count(md), "parts": out,
            "week": f"{ws} to {we}"}


def _assemble_pulse(a: dict, out: dict, ws: str, we: str, quote_words: int = QUOTE_MAX_WORDS) -> str:
    c, top = a["counts"], a["top_themes"]
    lines = [f"# Groww Weekly Product Pulse: week of {_fmt_day(ws)} to {_fmt_day(we)} {we[:4]}",
             f"*Source: {c['all_reviews']:,} Google Play reviews, {_fmt_day(a['window']['start'])} to "
             f"{_fmt_day(a['window']['end'])}; {c['analysed']:,} detailed reviews themed.*", "",
             "## Top themes"]
    for i, (t, line) in enumerate(zip(top, out["theme_lines"]), 1):
        lines.append(f"{i}. **{t['name']}** ({t['critical_reviews']} critical reviews, avg {t['avg_rating']:.1f}★): {line}")
    lines += ["", "## What users are saying"]
    for i, q in enumerate(a["quotes"], 1):
        lines.append(f"> \"{short_quote(q['text'], quote_words)}\" ({q['rating']}★, theme {i})")
        lines.append("")
    lines += ["## Key observation", out["observation"], "", "## Action ideas"]
    lines += [f"{i}. {x}" for i, x in enumerate(out["actions"][:3], 1)]
    return "\n".join(lines).strip() + "\n"


# ---------------------------------------------------------------- step 3
def _numbers(s: str) -> set[str]:
    return {n.rstrip(".").lstrip("0") or "0" for n in re.findall(r"\d+(?:\.\d+)?", s.replace(",", ""))}


def fee_explainer(a: dict, today: str | None = None) -> dict:
    facts_all = json.loads(FACTS_JSON.read_text())
    key = a["fee_issue"]["issue_key"]
    if key not in facts_all:
        raise ValueError(f"No verified facts for fee issue '{key}'. Add them to data/fee_facts.json first.")
    spec, sources = facts_all[key], facts_all["sources"]
    facts = spec["facts"]
    allowed = set().union(*(_numbers(f["text"]) for f in facts))
    links = [sources[s] for s in spec["explainer_links"]]
    prompt = f"""Write a customer-facing explainer for Groww users who are confused about this:
{a['fee_issue'].get('summary')}

Use ONLY the facts below. Neutral, facts-only tone: no opinions, no advice, no comparisons with other brokers,
no words like "only", "just", "nominal" or "small". Plain English, no em dashes.
At most {MAX_BULLETS} bullets, each at most 35 words. Merge facts if needed (for example delivery and intraday
taxes in one bullet). Every number must come from the facts. Keep the ₹ and % symbols exactly as in the facts, and keep the
specific rates and amounts (do not replace them with vague words like "varies").
The last bullet must state the contract-note and pricing-page fact.

Facts:
{json.dumps([f["text"] for f in facts], ensure_ascii=False, indent=1)}

Return JSON only: {{"title": "<= 10 words", "bullets": ["...", "..."]}}"""
    must = spec.get("must_include", [])
    problems = []
    for attempt in range(2):
        problems = []
        try:
            out = llm.generate_json(prompt)
            bullets = [b.strip() for b in out["bullets"] if b.strip()][:MAX_BULLETS]
            title = out.get("title") or spec["name"]
            bad = [b for b in bullets if not _numbers(b) <= allowed]
            if bad:
                problems.append(f"model used numbers not in the facts: {bad}")
            missing = [m for m in must if m.lower() not in " ".join(bullets).lower()]
            if missing:
                problems.append(f"missing key facts: {missing}")
                prompt += f"\nYour last draft left out: {missing}. Include them."
        except Exception as e:  # noqa: BLE001
            problems.append(f"model unavailable: {e}")
        if not problems:
            break
    if problems:  # fall back to the hand-checked wording in fee_facts.json
        title, bullets = spec["name"], spec["fallback_bullets"][:MAX_BULLETS]
    today = today or dt.date.today().isoformat()
    md = [f"### {title}", ""] + [f"- {b}" for b in bullets] + [""]
    md += ["**Official sources:** " + " | ".join(f"[{l['title']}]({l['url']})" for l in links), "",
           f"*Last checked: {spec['last_checked']}*"]
    return {"title": title, "bullets": bullets, "links": links, "last_checked": spec["last_checked"],
            "markdown": "\n".join(md) + "\n", "fallback_used": bool(problems), "problems": problems,
            "generated_on": today}


# ---------------------------------------------------------------- tool payloads
def notes_payload(a: dict, pulse: dict, expl: dict) -> dict:
    """Exactly the fields the brief asks to append to the notes doc."""
    fee = a["fee_issue"]
    return {
        "date": dt.date.today().isoformat(),
        "top_themes": [t["name"] for t in a["top_themes"]],
        "weekly_pulse": pulse["markdown"],
        "identified_fee_issue": f"{fee.get('name')}: {fee.get('summary')}",
        "explanation_bullets": expl["bullets"],
        "source_links": [l["url"] for l in expl["links"]],
    }


def email_payload(a: dict, pulse: dict, expl: dict, to: str = "") -> dict:
    d = dt.date.today()
    subject = f"Weekly Product Pulse + Customer Clarification - {d.day} {d.strftime('%b %Y')}"
    snippet = "\n".join(f"- {b}" for b in expl["bullets"])
    links = "\n".join(f"- {l['title']}: {l['url']}" for l in expl["links"])
    body = (
        "Hi team,\n\nHere is this week's product pulse from Groww app reviews, followed by a reusable "
        "support snippet for the fee users are most confused about.\n\n"
        "=== WEEKLY PRODUCT PULSE ===\n\n" + _plain(pulse["markdown"]) +
        "\n=== SUPPORT SNIPPET: " + expl["title"].upper() + " ===\n"
        "(Copy and paste for customer replies)\n\n" + snippet +
        "\n\nOfficial sources:\n" + links + f"\n\nLast checked: {expl['last_checked']}\n\n"
        "This is a draft for review. It has not been sent.\n"
    )
    return {"to": to, "subject": subject, "body": body}


def _plain(md: str) -> str:
    md = re.sub(r"^#+\s*", "", md, flags=re.M)
    md = re.sub(r"\*\*(.+?)\*\*", r"\1", md)
    md = re.sub(r"^\*(.+)\*$", r"\1", md, flags=re.M)
    return md


# ---------------------------------------------------------------- cache
def build_all(a: dict, force: bool = False) -> dict:
    if OUTPUTS_JSON.exists() and not force:
        return json.loads(OUTPUTS_JSON.read_text())
    pulse = weekly_pulse(a)
    expl = fee_explainer(a)
    res = {"pulse": pulse, "explainer": expl,
           "notes_payload": notes_payload(a, pulse, expl), "email_payload": email_payload(a, pulse, expl)}
    OUTPUTS_JSON.write_text(json.dumps(res, indent=2, ensure_ascii=False))
    return res
