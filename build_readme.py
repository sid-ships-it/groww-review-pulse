"""Build README.md from the saved analysis and outputs, so every number in it matches the app."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).parent
a = json.loads((ROOT / "data" / "analysis.json").read_text())
o = json.loads((ROOT / "data" / "outputs.json").read_text())
fee = a["fee_issue"]
c = a["counts"]
APP_URL = "https://<your-app>.streamlit.app"  # replace after deploying

themes_tbl = "\n".join(
    f"| {i} | {t['name']} | {t['reviews']} | {t['share'] * 100:.0f}% | {t['critical_reviews']} | {t['avg_rating']:.1f}★ |"
    for i, t in enumerate(a["themes"], 1))
fee_tbl = "\n".join(f"| {k.replace('_', ' ')} | {v['mentions']} | {v['confused']} |" for k, v in fee["by_topic"].items())
quotes = "\n".join(f"{i}. \"{q['text']}\" ({q['rating']}★, {q['date']}, theme: {q['theme']})"
                   for i, q in enumerate(a["quotes"], 1))
with (ROOT / "sources.csv").open() as f:
    sources = "\n".join(f"| {r['title']} | {r['url']} | {r['used_for']} |" for r in csv.DictReader(f))
notes_doc = (ROOT / "outputs" / "notes_doc_after_append.md").read_text()
email_txt = (ROOT / "outputs" / "email_draft.txt").read_text()
top_names = ", ".join(t["name"] for t in a["top_themes"])

readme = f"""# Groww Review Pulse

An AI workflow that turns raw Groww app reviews into a weekly product pulse for the product team and a
ready-to-use fee explanation for the support team, then logs both to internal tools through **MCP, only after a
human approves**.

- **Product:** Groww (same product as the earlier milestones)
- **Live app:** {APP_URL}
- **Input:** {c['all_reviews']:,} public Google Play reviews, {a['window']['start']} to {a['window']['end']} ({a['window']['weeks']} weeks), in `data/reviews.csv`

## What fee issue was identified from the reviews

**{fee['name']}.** {fee['summary']}

- {fee['issue_reviews']} of the {c['analysed']:,} themed reviews are about charges on stock trades, and
  {fee['issue_confused_reviews']} of them read as confused or surprised (for example "brokerage is 20 but other
  charges will take all your profits", "Dp charge 24 rupees"), not only "the price is high". Their average rating is
  {fee['issue_avg_rating']}★.
- It sits inside the theme **Charges, Fees & Financial Transparency**, one of the top 3 themes.
- The explainer answers exactly that question: what is deducted on a buy or a sell beyond the ₹20 brokerage. The
  ₹23.60 DP charge it explains is the "24 rupees" users mention.

Fee mentions by type (model labels, every themed review):

| Fee type | Mentions | Confused or surprised |
|---|---|---|
{fee_tbl}

## Where the MCP approval happens

1. **In the app, tab "4. Approve and log (MCP)".** The app is an MCP client. It starts the MCP server
   (`mcp_server.py`) over stdio, lists its tools, and shows the two proposed actions with their full payloads.
   Each action has its own **Approve** and **Reject** button. Nothing is written before you click Approve.
2. **In the terminal**, `python run_pipeline.py` shows each payload and asks `Approve append_to_notes? [y/N]`.
3. **On the server side too.** The write tools refuse to run without a one-time approval token, created only when a
   human approves, that matches a SHA-256 hash of the exact payload. A token cannot be reused, and an approved
   payload cannot be swapped for another one. Every approval and rejection is logged (`outputs/approval_log_sample.json`).

MCP tools exposed by the server:

| Tool | What it does |
|---|---|
| `append_to_notes` | Appends `{{date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links}}` to the team notes document |
| `create_email_draft` | Saves an email **draft** (`.eml`, opens as an editable draft in Mail or Outlook). There is no send tool, so nothing can be auto-sent |
| `read_notes` | Reads back the latest notes entries (read only) |

## How to run

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
mkdir -p .streamlit && echo 'GEMINI_API_KEY = "your-key"' > .streamlit/secrets.toml   # free key: aistudio.google.com
streamlit run app.py
```

- Terminal version with y/N approval: `python run_pipeline.py --to team@example.com`
- Re-write Steps 2 and 3 with the model: `python run_pipeline.py --regenerate` (or the sidebar button in the app)
- Redo Step 1 from scratch (themes and labels for every review, about 5 minutes): `python run_pipeline.py --reanalyse`
- Fetch fresh reviews: `python fetch_reviews.py --weeks 10`
- Deploy: Streamlit Community Cloud, main file `app.py`, add `GEMINI_API_KEY` under Settings > Secrets.

Without a key the app still works: it shows the saved analysis and outputs, and the MCP step runs normally.

## How it works

```
reviews.csv (10 weeks, Play Store)
  -> Step 1  Review intelligence  (pulse/analysis.py)
       keep reviews with 6+ words, remove duplicates            -> {c['analysed']:,} reviews
       model proposes max 5 themes from a sample of 400
       model labels every review: theme, sentiment, fee type, confused yes/no (batches of 100)
       code counts themes, picks top 3, finds the fee with the most confused reviews, tracks weekly trend
       model picks 3 representative quotes, code checks they appear word for word in the CSV
  -> Step 2  Weekly pulse  (pulse/writer.py)    model writes short parts; code builds the note, enforces <= 250 words
  -> Step 3  Fee explainer (pulse/writer.py)    model rewrites verified facts (data/fee_facts.json) into <= 6 bullets;
                                                code rejects any number not in the facts and any missing key fact
  -> Step 4  MCP (mcp_server.py + pulse/mcp_client.py)   human approval -> append to notes doc, create email draft
```

Context engineering choices: the model never sees the whole CSV at once. It gets a sample to find themes, small
batches to label, computed numbers to write the pulse, and only verified facts to write the explainer. Numbers,
quotes, links and structure come from code, and each output is checked before it is shown.

## Step 1 results

{c['all_reviews']:,} reviews in the window, average rating {c['avg_rating_all']}★, {c['one_star_share'] * 100:.0f}% one-star.
{c['analysed']:,} detailed reviews were themed.

| # | Theme | Reviews | Share | Critical (negative or mixed) | Avg rating |
|---|---|---|---|---|---|
{themes_tbl}

**Top 3 themes:** {top_names}. They are ranked by the number of critical reviews, because they are the problem
areas a product team acts on. "General Praise & User Experience" is the largest theme by volume but has almost no
issues in it, so it is reported in the table and not ranked.

**3 real user quotes** (word for word from `data/reviews.csv`):

{quotes}

## Weekly product pulse ({o['pulse']['words']} words)

Also in `outputs/weekly_pulse.md`.

{o['pulse']['markdown'].replace('# Groww Weekly', '### Groww Weekly').replace(chr(10) + '## ', chr(10) + '#### ')}
## Fee explainer

Also in `outputs/fee_explainer.md`.

{o['explainer']['markdown']}
## Notes document after the approved append

From `outputs/notes_doc_after_append.md`:

<details><summary>Show the appended entry</summary>

{notes_doc.replace(chr(10) + '# ', chr(10) + '### ')}
</details>

## Email draft (not sent)

From `outputs/email_draft.txt` (the `.eml` version is `outputs/email_draft.eml`):

```text
{email_txt.strip()}
```

## Source list

| Source | URL | Used for |
|---|---|---|
{sources}

## Deliverables in this repo

| Deliverable | File |
|---|---|
| Working prototype | {APP_URL} (code: `app.py`) |
| Weekly product pulse | `outputs/weekly_pulse.md` |
| Notes doc snippet with the appended entry | `outputs/notes_doc_after_append.md` |
| Email draft | `outputs/email_draft.txt`, `outputs/email_draft.eml` |
| Reviews CSV | `data/reviews.csv` (full), `data/reviews_sample.csv` (150 rows with labels) |
| Source list | `sources.csv` (5 URLs) |
| Fee explainer | `outputs/fee_explainer.md` |

## Known limits

- Reviews come from Google Play only (India listing, English and Hinglish text). App Store reviews are not included.
- Theme and fee labels are model judgements. Spot checks looked right, but a few reviews will sit in the wrong theme.
- The notes document and email drafts are local files written by the MCP server. On the hosted app they reset when
  the app restarts, so download them from the app. Swapping in Google Docs, Notion or Gmail means changing only the
  two tool functions in `mcp_server.py`.
- Fee facts were checked by hand against the official pages on {o['explainer']['last_checked']}. Charges can change, so
  the explainer shows its "Last checked" date.

## Privacy

Only public review text is kept. Reviewer names and photos are dropped, and anything that looks like an email,
phone number, PAN, Aadhaar or account number inside a review is replaced with `[redacted]`. Quotes that name a
person are skipped.

## Disclaimer

Facts-only. This tool summarises public reviews and official fee information. It does not give investment advice.
"""
(ROOT / "README.md").write_text(readme, encoding="utf-8")
print("README.md written,", len(readme.split()), "words")
