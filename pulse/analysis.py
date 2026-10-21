"""Step 1: Review intelligence layer.

reviews.csv -> informative reviews -> up to 5 themes (found by the model)
-> every review labelled with a theme, sentiment and any fee it mentions
-> top 3 themes, 3 verbatim quotes, the most misunderstood fee, weekly trend.

Labels are cached in data/review_labels.csv and the summary in
data/analysis.json, so the app does not re-spend the model quota on every load.
"""
import datetime as dt
import json
import random
import re
from pathlib import Path

import pandas as pd

from . import llm

ROOT = Path(__file__).resolve().parent.parent
REVIEWS_CSV = ROOT / "data" / "reviews.csv"
LABELS_CSV = ROOT / "data" / "review_labels.csv"
THEMES_JSON = ROOT / "data" / "themes.json"
ANALYSIS_JSON = ROOT / "data" / "analysis.json"

MIN_WORDS = 6
BATCH = 100

FEE_TOPICS = {
    "none": "no fee or charge mentioned",
    "brokerage_rate": "the brokerage per order (Rs 20 / 0.1%) is called too high or costlier than other apps",
    "trade_charges_unclear": "other charges, taxes or deductions on a buy/sell beyond brokerage feel hidden, unclear, or eat the profit",
    "dp_charge": "DP / depository charge when selling shares",
    "ddpi_fee": "fee to activate DDPI (selling without TPIN)",
    "auto_square_off": "auto square-off charge on intraday positions",
    "mtf_or_loan_interest": "MTF, pledge or loan interest and closing charges",
    "account_opening_or_maintenance": "account opening or annual maintenance (AMC) charge",
    "sip_or_mandate_charges": "SIP / UPI / NACH mandate or bounce charges",
    "mf_expense_ratio": "mutual fund expense ratio, commission or plan charges",
    "money_deducted_unexplained": "money deducted from balance or withdrawal with no reason given",
    "other_fee": "any other fee",
}
# Fee topics that belong to one user-facing confusion: "what gets deducted on a stock trade"
TRADE_CHARGE_FAMILY = {"brokerage_rate", "trade_charges_unclear", "dp_charge", "ddpi_fee", "auto_square_off"}

PERSON_NAME = re.compile(r"\b(?:Mr|Mrs|Ms|Sir|Madam)\.?\s+[A-Z][a-z]+|\b[A-Z][a-z]+ [A-Z][a-z]+(?= (?:constantly|is|was|did|said))")


# ---------------------------------------------------------------- loading
def load_reviews(path: Path = REVIEWS_CSV) -> pd.DataFrame:
    df = pd.read_csv(path, dtype={"review_id": str})
    df["text"] = df["text"].fillna("").astype(str)
    df["date"] = pd.to_datetime(df["date"])
    df["words"] = df["text"].str.split().str.len()
    return df


def informative(df: pd.DataFrame) -> pd.DataFrame:
    """Reviews with enough words to carry a theme, de-duplicated on text."""
    sub = df[df["words"] >= MIN_WORDS].copy()
    sub["norm"] = sub["text"].str.lower().str.replace(r"\W+", " ", regex=True).str.strip()
    sub = sub.drop_duplicates("norm").drop(columns="norm")
    return sub.reset_index(drop=True)


# ---------------------------------------------------------------- themes
def discover_themes(sub: pd.DataFrame, n_sample: int = 400, seed: int = 7) -> list[dict]:
    rng = random.Random(seed)
    idx = list(sub.index)
    # Over-sample critical reviews so problems are not drowned out by short praise
    crit = [i for i in idx if sub.at[i, "rating"] <= 3]
    rest = [i for i in idx if sub.at[i, "rating"] > 3]
    pick = rng.sample(crit, min(len(crit), n_sample // 2))
    pick += rng.sample(rest, min(len(rest), n_sample - len(pick)))
    lines = "\n".join(f"{sub.at[i, 'rating']}* | {sub.at[i, 'text'][:300]}" for i in pick)
    prompt = f"""You are a product analyst for Groww, an Indian investing app (stocks, F&O, mutual funds, IPOs, MTF).
Below are {len(pick)} recent Google Play reviews (rating | text). Some are in Hindi or Hinglish.

Group them into AT MOST 5 themes that together cover nearly every review.
Rules:
- Each theme is a product area a product team can act on (for example "Charges & fees", not "Angry users").
- Themes must not overlap. Merge small topics into the closest theme.
- If many reviews are general praise with no specific issue, give them one theme of their own.
- Names are at most 5 words. Descriptions are one plain sentence saying what belongs in the theme.

Return JSON only: {{"themes": [{{"id": 1, "name": "...", "description": "..."}}]}}

Reviews:
{lines}"""
    themes = llm.generate_json(prompt)["themes"][:5]
    for n, t in enumerate(themes, 1):
        t["id"] = n
    return themes


def _classify_batch(batch: pd.DataFrame, themes: list[dict]) -> list[list]:
    theme_txt = "\n".join(f"{t['id']}. {t['name']}: {t['description']}" for t in themes)
    fee_txt = "\n".join(f"- {k}: {v}" for k, v in FEE_TOPICS.items())
    rows = "\n".join(f"{n} | {r.rating}* | {r.text[:400]}" for n, r in enumerate(batch.itertuples()))
    prompt = f"""Label each Groww app review. Reviews may be in Hindi or Hinglish.

Themes (pick the single best one):
{theme_txt}

Fee topics (pick one; "none" unless the review talks about a fee, charge, brokerage, tax or deduction):
{fee_txt}

For each review return [index, theme_id, sentiment, fee_topic, fee_confused] where
- sentiment is "pos", "neg" or "mixed"
- fee_confused is 1 if the reviewer seems surprised, unaware or confused about a charge, or calls it hidden,
  unclear, unexpected or deducted without reason; 0 otherwise (including "too high" with no confusion).

Return JSON only, one entry per review in the same order: {{"r": [[0, 2, "neg", "none", 0], ...]}}

Reviews (index | rating | text):
{rows}"""
    out = llm.generate_json(prompt)["r"]
    if len(out) != len(batch):
        raise ValueError(f"expected {len(batch)} labels, got {len(out)}")
    return out


def _label_batch(batch: pd.DataFrame, themes: list[dict]) -> list[list]:
    try:
        return _classify_batch(batch, themes)
    except ValueError:  # retry once in two halves if the count came back wrong
        half = len(batch) // 2
        out = _classify_batch(batch.iloc[:half], themes)
        return out + [[o[0] + half, *o[1:]] for o in _classify_batch(batch.iloc[half:], themes)]


def classify(sub: pd.DataFrame, themes: list[dict], progress=None, workers: int = 4) -> pd.DataFrame:
    from concurrent.futures import ThreadPoolExecutor, as_completed
    valid_theme = {t["id"] for t in themes}
    labels = []
    batches = [sub.iloc[i:i + BATCH] for i in range(0, len(sub), BATCH)]
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_label_batch, b, themes): b for b in batches}
        for fut in as_completed(futures):
            batch, out = futures[fut], fut.result()
            for rid, o in zip(batch["review_id"], out):
                theme = int(o[1]) if int(o[1]) in valid_theme else None
                fee = o[3] if o[3] in FEE_TOPICS else "other_fee"
                labels.append({"review_id": rid, "theme_id": theme, "sentiment": o[2],
                               "fee_topic": fee, "fee_confused": int(bool(o[4])) if fee != "none" else 0})
            done += 1
            if progress:
                progress(done / len(batches), f"Labelled {done} of {len(batches)} batches of reviews")
    return sub.merge(pd.DataFrame(labels), on="review_id", how="left")


# ---------------------------------------------------------------- summary
def _week_start(d: pd.Timestamp) -> pd.Timestamp:
    return (d - pd.Timedelta(days=d.weekday())).normalize()


def summarize(all_reviews: pd.DataFrame, lab: pd.DataFrame, themes: list[dict]) -> dict:
    lab = lab.dropna(subset=["theme_id"]).copy()
    lab["theme_id"] = lab["theme_id"].astype(int)
    lab["week"] = lab["date"].map(_week_start)
    weeks = sorted(lab["week"].unique())
    latest, prior = weeks[-1], weeks[:-1]

    theme_rows = []
    for t in themes:
        g = lab[lab["theme_id"] == t["id"]]
        share = len(g) / len(lab)
        lw = lab[lab["week"] == latest]
        latest_share = (lw["theme_id"] == t["id"]).mean() if len(lw) else 0
        pw = lab[lab["week"].isin(prior)]
        prior_share = (pw["theme_id"] == t["id"]).mean() if len(pw) else 0
        theme_rows.append({
            **t, "reviews": int(len(g)), "share": round(share, 4),
            "critical_reviews": int(g["sentiment"].isin(["neg", "mixed"]).sum()),
            "avg_rating": round(float(g["rating"].mean()), 2) if len(g) else None,
            "negative_share": round(float(g["sentiment"].isin(["neg", "mixed"]).mean()), 3) if len(g) else None,
            "latest_week_share": round(float(latest_share), 4),
            "prior_weeks_share": round(float(prior_share), 4),
        })
    theme_rows.sort(key=lambda r: r["reviews"], reverse=True)
    # Top themes = the biggest problem areas: most negative or mixed reviews.
    # A pure-praise theme is still reported in the theme table, but it carries no issue to act on.
    top = sorted(theme_rows, key=lambda r: r["critical_reviews"], reverse=True)[:3]

    weekly = (lab.groupby(["week", "theme_id"]).size().unstack(fill_value=0)
              .rename(columns={t["id"]: t["name"] for t in themes}))
    weekly.index = [w.strftime("%Y-%m-%d") for w in weekly.index]

    return {
        "generated_on": dt.date.today().isoformat(),
        "source": "Google Play reviews of Groww (India, English listing)",
        "window": {"start": all_reviews["date"].min().strftime("%Y-%m-%d"),
                   "end": all_reviews["date"].max().strftime("%Y-%m-%d"),
                   "weeks": len(weeks),
                   "latest_week": f"{latest.strftime('%Y-%m-%d')} to {(latest + pd.Timedelta(days=6)).strftime('%Y-%m-%d')}"},
        "counts": {"all_reviews": int(len(all_reviews)), "analysed": int(len(lab)),
                   "avg_rating_all": round(float(all_reviews["rating"].mean()), 2),
                   "one_star_share": round(float((all_reviews["rating"] == 1).mean()), 3)},
        "themes": theme_rows,
        "top_themes": top,
        "top_themes_basis": "most negative or mixed reviews",
        "weekly_counts": weekly.to_dict(orient="index"),
    }


def identify_fee_issue(lab: pd.DataFrame) -> dict:
    fee = lab[lab["fee_topic"].fillna("none") != "none"].copy()
    by_topic = (fee.groupby("fee_topic").agg(mentions=("review_id", "size"), confused=("fee_confused", "sum"))
                .sort_values(["confused", "mentions"], ascending=False))
    family = fee[fee["fee_topic"].isin(TRADE_CHARGE_FAMILY)]
    fam_conf = int(family["fee_confused"].sum())
    # The headline issue is the fee family with the most "confused / surprised" reviews.
    top_single = by_topic.index[0]
    if fam_conf >= int(by_topic.loc[top_single, "confused"]):
        issue_key, members = "stock_trade_charges", family
    else:
        issue_key, members = top_single, fee[fee["fee_topic"] == top_single]
    lab = lab.copy()
    lab["week"] = lab["date"].map(_week_start)
    weekly = members.assign(week=members["date"].map(_week_start)).groupby("week").size()
    return {
        "issue_key": issue_key,
        "fee_reviews_total": int(len(fee)),
        "fee_reviews_share_of_analysed": round(len(fee) / max(len(lab), 1), 4),
        "issue_reviews": int(len(members)),
        "issue_confused_reviews": int(members["fee_confused"].sum()),
        "issue_avg_rating": round(float(members["rating"].mean()), 2) if len(members) else None,
        "by_topic": {k: {"mentions": int(v.mentions), "confused": int(v.confused)} for k, v in by_topic.iterrows()},
        "weekly_issue_reviews": {w.strftime("%Y-%m-%d"): int(n) for w, n in weekly.items()},
        "example_ids": members.sort_values(["fee_confused", "thumbs_up", "words"], ascending=False)
                              ["review_id"].head(25).tolist(),
    }


def describe_fee_issue(lab: pd.DataFrame, fee: dict) -> dict:
    ex = lab[lab["review_id"].isin(fee["example_ids"])]
    lines = "\n".join(f"- {r.rating}* {r.text[:350]}" for r in ex.itertuples())
    prompt = f"""These Groww Play Store reviews are about charges. Counts by fee topic: {json.dumps(fee['by_topic'])}.
In plain, neutral words, state the single recurring fee confusion they share.
Use neutral words: no accusations such as "hidden", "scam" or "loot", even if reviewers use them.
Return JSON only: {{"name": "<= 8 words, neutral, names the specific charge (e.g. 'Charges deducted on ... orders')", "summary": "one or two sentences: what users expect vs what they see deducted",
"what_users_expect": "short phrase", "what_surprises_them": "short phrase"}}

Reviews:
{lines}"""
    return llm.generate_json(prompt)


# ---------------------------------------------------------------- quotes
def pick_quotes(lab: pd.DataFrame, top_themes: list[dict], fee: dict) -> list[dict]:
    quotes = []
    for t in top_themes:
        c = lab[(lab["theme_id"] == t["id"]) & lab["words"].between(12, 70)
                & ~lab["text"].str.contains(r"\[redacted\]") & ~lab["text"].str.contains(PERSON_NAME)]
        c = c[c["text"].str.contains(r"[a-zA-Z]{3}")]  # needs some English for the readers of the pulse
        if (c["sentiment"] != "pos").sum() >= 5 and t.get("negative_share", 0) >= 0.4:
            c = c[c["sentiment"] != "pos"]
        recent = c[c["date"] >= c["date"].max() - pd.Timedelta(days=27)]  # prefer the last 4 weeks
        if len(recent) >= 5:
            c = recent
        c = c.sort_values(["thumbs_up", "words"], ascending=False).head(12)
        if c.empty:
            continue
        lines = "\n".join(f"{r.review_id} | {r.text}" for r in c.itertuples())
        prompt = f"""Theme: {t['name']} ({t['description']}).
Pick the ONE review below that best represents this theme for a product team: specific, clear, no personal names.
Return JSON only: {{"review_id": "..."}}

{lines}"""
        try:
            rid = llm.generate_json(prompt)["review_id"]
        except Exception:
            rid = c.iloc[0]["review_id"]
        row = c[c["review_id"] == rid]
        row = row.iloc[0] if len(row) else c.iloc[0]
        quotes.append({"theme": t["name"], "review_id": row["review_id"], "rating": int(row["rating"]),
                       "date": row["date"].strftime("%Y-%m-%d"), "text": row["text"]})
    return quotes


def check_quotes(quotes: list[dict], df: pd.DataFrame) -> bool:
    """Every quote must appear word for word in the reviews CSV."""
    texts = set(df["text"])
    return all(q["text"] in texts for q in quotes)


# ---------------------------------------------------------------- orchestration
def run(force: bool = False, progress=None) -> dict:
    if ANALYSIS_JSON.exists() and not force:
        return json.loads(ANALYSIS_JSON.read_text())
    df = load_reviews()
    if not force and LABELS_CSV.exists() and THEMES_JSON.exists():  # labels saved, only re-summarise
        return finish(df, load_labels(), json.loads(THEMES_JSON.read_text()))
    sub = informative(df)
    if progress:
        progress(0.0, f"Finding themes in {len(sub)} informative reviews")
    themes = discover_themes(sub)
    THEMES_JSON.write_text(json.dumps(themes, indent=2, ensure_ascii=False))
    lab = classify(sub, themes, progress=progress)
    lab[["review_id", "date", "rating", "theme_id", "sentiment", "fee_topic", "fee_confused", "text"]] \
        .to_csv(LABELS_CSV, index=False)
    return finish(df, lab, themes)


def finish(df: pd.DataFrame, lab: pd.DataFrame, themes: list[dict]) -> dict:
    summary = summarize(df, lab, themes)
    fee = identify_fee_issue(lab)
    fee.update(describe_fee_issue(lab, fee))
    facts = json.loads((ROOT / "data" / "fee_facts.json").read_text())
    if fee["issue_key"] in facts:  # use the same plain name as the verified explainer
        fee["model_name"], fee["name"] = fee.get("name"), facts[fee["issue_key"]]["name"]
    summary["fee_issue"] = fee
    summary["quotes"] = pick_quotes(lab, summary["top_themes"], fee)
    summary["quotes_verified_verbatim"] = check_quotes(summary["quotes"], df)
    ANALYSIS_JSON.write_text(json.dumps(summary, indent=2, ensure_ascii=False, default=str))
    return summary


def load_labels() -> pd.DataFrame:
    lab = pd.read_csv(LABELS_CSV, dtype={"review_id": str})
    df = load_reviews()
    return df.merge(lab[["review_id", "theme_id", "sentiment", "fee_topic", "fee_confused"]], on="review_id")
