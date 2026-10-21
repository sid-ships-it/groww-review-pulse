# Groww Review Pulse

An AI workflow that turns raw Groww app reviews into a weekly product pulse for the product team and a
ready-to-use fee explanation for the support team, then logs both to internal tools through **MCP, only after a
human approves**.

- **Product:** Groww (same product as the earlier milestones)
- **Live app:** https://<your-app>.streamlit.app
- **Input:** 10,537 public Google Play reviews, 2026-08-10 to 2026-10-18 (10 weeks), in `data/reviews.csv`

## What fee issue was identified from the reviews

**Charges on a stock trade beyond the ₹20 brokerage.** Users expect transaction costs to align with advertised rates, but they often find the final deducted amounts higher or less transparent than anticipated. This discrepancy between expected and actual net proceeds leads to confusion regarding the composition of various fees and taxes.

- 197 of the 2,321 themed reviews are about charges on stock trades, and
  47 of them read as confused or surprised (for example "brokerage is 20 but other
  charges will take all your profits", "Dp charge 24 rupees"), not only "the price is high". Their average rating is
  2.42★.
- It sits inside the theme **Charges, Fees & Financial Transparency**, one of the top 3 themes.
- The explainer answers exactly that question: what is deducted on a buy or a sell beyond the ₹20 brokerage. The
  ₹23.60 DP charge it explains is the "24 rupees" users mention.

Fee mentions by type (model labels, every themed review):

| Fee type | Mentions | Confused or surprised |
|---|---|---|
| trade charges unclear | 43 | 35 |
| money deducted unexplained | 28 | 25 |
| other fee | 22 | 8 |
| brokerage rate | 140 | 7 |
| mtf or loan interest | 11 | 3 |
| account opening or maintenance | 7 | 3 |
| auto square off | 5 | 3 |
| sip or mandate charges | 18 | 2 |
| mf expense ratio | 6 | 2 |
| ddpi fee | 4 | 2 |
| dp charge | 5 | 0 |

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
| `append_to_notes` | Appends `{date, top_themes, weekly_pulse, identified_fee_issue, explanation_bullets, source_links}` to the team notes document |
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
       keep reviews with 6+ words, remove duplicates            -> 2,321 reviews
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

10,537 reviews in the window, average rating 4.39★, 11% one-star.
2,321 detailed reviews were themed.

| # | Theme | Reviews | Share | Critical (negative or mixed) | Avg rating |
|---|---|---|---|---|---|
| 1 | General Praise & User Experience | 956 | 41% | 24 | 4.9★ |
| 2 | App Performance & Technical Stability | 541 | 23% | 531 | 1.5★ |
| 3 | Trading Features & UI Improvements | 352 | 15% | 152 | 3.4★ |
| 4 | Customer Support & Service Quality | 266 | 11% | 260 | 1.4★ |
| 5 | Charges, Fees & Financial Transparency | 206 | 9% | 180 | 2.3★ |

**Top 3 themes:** App Performance & Technical Stability, Customer Support & Service Quality, Charges, Fees & Financial Transparency. They are ranked by the number of critical reviews, because they are the problem
areas a product team acts on. "General Praise & User Experience" is the largest theme by volume but has almost no
issues in it, so it is reported in the table and not ranked.

**3 real user quotes** (word for word from `data/reviews.csv`):

1. "Groww is constantly lagging, hanging, and taking too long to load. Charts and chart properties often don’t open properly, and F&O trading/options are also not working smoothly. Because of these issues, I have suffered significant financial losses. This is a completely unacceptable and frustrating experience from such a nonsense app. Please fix these issues urgently." (1★, 2026-09-21, theme: App Performance & Technical Stability)
2. "It was 5 star until now. My order got rejected so I tried approaching customer care and the process is horrible. AI in chat, AI on call. After 4 minutes of discussion with AI I could finally reach an executive. After giving him information he put me on never ending hold and then disconnected the call." (1★, 2026-10-16, theme: Customer Support & Service Quality)
3. "Brokarage fees are too high , Dp charge 24 rupees , I have। switched to another platform, when I calculate my monthly brokerage charge i am fully shocked and immediately change my reading platform" (1★, 2026-10-12, theme: Charges, Fees & Financial Transparency)

## Weekly product pulse (228 words)

Also in `outputs/weekly_pulse.md`.

### Groww Weekly Product Pulse: week of 12 Oct to 18 Oct 2026
*Source: 10,537 Google Play reviews, 10 Aug to 18 Oct; 2,321 detailed reviews themed.*

#### Top themes
1. **App Performance & Technical Stability** (531 critical reviews, avg 1.5★): Users report lagging charts, slow order execution, and app crashes during trading.
2. **Customer Support & Service Quality** (260 critical reviews, avg 1.4★): Users report unhelpful AI chat support and long wait times for issue resolution.
3. **Charges, Fees & Financial Transparency** (180 critical reviews, avg 2.3★): Users report confusion regarding high brokerage and unexpected deductions on stock trades.

#### What users are saying
> "Groww is constantly lagging, hanging, and taking too long to load. ..." (1★, theme 1)

> "It was 5 star until now. My order got rejected so I tried approaching customer care and the process is horrible. ..." (1★, theme 2)

> "Brokarage fees are too high , Dp charge 24 rupees , I have। switched to another platform, when I calculate my monthly..." (1★, theme 3)

#### Key observation
Customer Support and Charges saw increases in negative reviews, moving to 14 percent versus 11 percent and 12 percent versus 9 percent respectively. This aligns with 47 fee confusion reviews out of 197 total fee reviews.

#### Action ideas
1. Add a detailed fee breakdown screen before order placement.
2. Improve live agent routing to reduce support wait times.
3. Optimize chart loading and trade execution speed.

## Fee explainer

Also in `outputs/fee_explainer.md`.

### Understanding Your Transaction Costs and Charges

- Equity brokerage is ₹20 or 0.1% per executed order, whichever is lower, with a minimum of ₹5. Buying and selling are separate orders, so each one is charged.
- Selling delivery shares adds a DP charge per sell transaction: ₹3.5 depository fee (₹3.25 for women account holders) plus ₹16.5 Groww fee, with 18% GST on top, which comes to about ₹23.60. Intraday trades have no DP charge.
- Delivery trades pay STT of 0.1% on buy and sell and stamp duty of 0.015% on buy. Intraday trades pay STT of 0.025% on sell and stamp duty of 0.003% on buy. Exchange transaction charges (NSE 0.00297%, BSE 0.00375%) and the SEBI turnover charge (0.0001%) apply on both sides.
- GST of 18% is added on brokerage, DP charges, exchange transaction charges, IPFT, SEBI turnover charges, DDPI charges and auto square-off charges.
- DDPI charges are ₹100 + GST, and the system's auto square-off of an open intraday position costs ₹50 per position + GST. Fixed amounts like the ₹5 minimum brokerage and DP charge take a larger share of small trades.
- SEBI advises investors to insist on a contract note for every trade within 24 hours and to note all charges, fees and brokerage that apply to their account. Groww lists every charge on its pricing page.

**Official sources:** [Groww: Pricing and charges](https://groww.in/pricing) | [SEBI investor website: Securities market do's and don'ts](https://investor.sebi.gov.in/securities-dos_and_donts.html)

*Last checked: 2026-10-20*

## Notes document after the approved append

From `outputs/notes_doc_after_append.md`:

<details><summary>Show the appended entry</summary>

# Groww Product Notes

Weekly entries appended by the review-pulse workflow.

---

## Entry: 2026-10-20

**Top themes:** App Performance & Technical Stability, Customer Support & Service Quality, Charges, Fees & Financial Transparency

**Identified fee issue:** Charges on a stock trade beyond the ₹20 brokerage: Users expect transaction costs to align with advertised rates, but they often find the final deducted amounts higher or less transparent than anticipated. This discrepancy between expected and actual net proceeds leads to confusion regarding the composition of various fees and taxes.

**Weekly pulse:**

### Groww Weekly Product Pulse: week of 12 Oct to 18 Oct 2026
*Source: 10,537 Google Play reviews, 10 Aug to 18 Oct; 2,321 detailed reviews themed.*

#### Top themes
1. **App Performance & Technical Stability** (531 critical reviews, avg 1.5★): Users report lagging charts, slow order execution, and app crashes during trading.
2. **Customer Support & Service Quality** (260 critical reviews, avg 1.4★): Users report unhelpful AI chat support and long wait times for issue resolution.
3. **Charges, Fees & Financial Transparency** (180 critical reviews, avg 2.3★): Users report confusion regarding high brokerage and unexpected deductions on stock trades.

#### What users are saying
> "Groww is constantly lagging, hanging, and taking too long to load. ..." (1★, theme 1)

> "It was 5 star until now. My order got rejected so I tried approaching customer care and the process is horrible. ..." (1★, theme 2)

> "Brokarage fees are too high , Dp charge 24 rupees , I have। switched to another platform, when I calculate my monthly..." (1★, theme 3)

#### Key observation
Customer Support and Charges saw increases in negative reviews, moving to 14 percent versus 11 percent and 12 percent versus 9 percent respectively. This aligns with 47 fee confusion reviews out of 197 total fee reviews.

#### Action ideas
1. Add a detailed fee breakdown screen before order placement.
2. Improve live agent routing to reduce support wait times.
3. Optimize chart loading and trade execution speed.

**Fee explanation (support snippet):**

- Equity brokerage is ₹20 or 0.1% per executed order, whichever is lower, with a minimum of ₹5. Buying and selling are separate orders, so each one is charged.
- Selling delivery shares adds a DP charge per sell transaction: ₹3.5 depository fee (₹3.25 for women account holders) plus ₹16.5 Groww fee, with 18% GST on top, which comes to about ₹23.60. Intraday trades have no DP charge.
- Delivery trades pay STT of 0.1% on buy and sell and stamp duty of 0.015% on buy. Intraday trades pay STT of 0.025% on sell and stamp duty of 0.003% on buy. Exchange transaction charges (NSE 0.00297%, BSE 0.00375%) and the SEBI turnover charge (0.0001%) apply on both sides.
- GST of 18% is added on brokerage, DP charges, exchange transaction charges, IPFT, SEBI turnover charges, DDPI charges and auto square-off charges.
- DDPI charges are ₹100 + GST, and the system's auto square-off of an open intraday position costs ₹50 per position + GST. Fixed amounts like the ₹5 minimum brokerage and DP charge take a larger share of small trades.
- SEBI advises investors to insist on a contract note for every trade within 24 hours and to note all charges, fees and brokerage that apply to their account. Groww lists every charge on its pricing page.

**Sources:** https://groww.in/pricing | https://investor.sebi.gov.in/securities-dos_and_donts.html

</details>

## Email draft (not sent)

From `outputs/email_draft.txt` (the `.eml` version is `outputs/email_draft.eml`):

```text
To: product-team@example.com
Subject: Weekly Product Pulse + Customer Clarification - 20 Oct 2026

Hi team,

Here is this week's product pulse from Groww app reviews, followed by a reusable support snippet for the fee users are most confused about.

=== WEEKLY PRODUCT PULSE ===

Groww Weekly Product Pulse: week of 12 Oct to 18 Oct 2026
Source: 10,537 Google Play reviews, 10 Aug to 18 Oct; 2,321 detailed reviews themed.

Top themes
1. App Performance & Technical Stability (531 critical reviews, avg 1.5★): Users report lagging charts, slow order execution, and app crashes during trading.
2. Customer Support & Service Quality (260 critical reviews, avg 1.4★): Users report unhelpful AI chat support and long wait times for issue resolution.
3. Charges, Fees & Financial Transparency (180 critical reviews, avg 2.3★): Users report confusion regarding high brokerage and unexpected deductions on stock trades.

What users are saying
> "Groww is constantly lagging, hanging, and taking too long to load. ..." (1★, theme 1)

> "It was 5 star until now. My order got rejected so I tried approaching customer care and the process is horrible. ..." (1★, theme 2)

> "Brokarage fees are too high , Dp charge 24 rupees , I have। switched to another platform, when I calculate my monthly..." (1★, theme 3)

Key observation
Customer Support and Charges saw increases in negative reviews, moving to 14 percent versus 11 percent and 12 percent versus 9 percent respectively. This aligns with 47 fee confusion reviews out of 197 total fee reviews.

Action ideas
1. Add a detailed fee breakdown screen before order placement.
2. Improve live agent routing to reduce support wait times.
3. Optimize chart loading and trade execution speed.

=== SUPPORT SNIPPET: UNDERSTANDING YOUR TRANSACTION COSTS AND CHARGES ===
(Copy and paste for customer replies)

- Equity brokerage is ₹20 or 0.1% per executed order, whichever is lower, with a minimum of ₹5. Buying and selling are separate orders, so each one is charged.
- Selling delivery shares adds a DP charge per sell transaction: ₹3.5 depository fee (₹3.25 for women account holders) plus ₹16.5 Groww fee, with 18% GST on top, which comes to about ₹23.60. Intraday trades have no DP charge.
- Delivery trades pay STT of 0.1% on buy and sell and stamp duty of 0.015% on buy. Intraday trades pay STT of 0.025% on sell and stamp duty of 0.003% on buy. Exchange transaction charges (NSE 0.00297%, BSE 0.00375%) and the SEBI turnover charge (0.0001%) apply on both sides.
- GST of 18% is added on brokerage, DP charges, exchange transaction charges, IPFT, SEBI turnover charges, DDPI charges and auto square-off charges.
- DDPI charges are ₹100 + GST, and the system's auto square-off of an open intraday position costs ₹50 per position + GST. Fixed amounts like the ₹5 minimum brokerage and DP charge take a larger share of small trades.
- SEBI advises investors to insist on a contract note for every trade within 24 hours and to note all charges, fees and brokerage that apply to their account. Groww lists every charge on its pricing page.

Official sources:
- Groww: Pricing and charges: https://groww.in/pricing
- SEBI investor website: Securities market do's and don'ts: https://investor.sebi.gov.in/securities-dos_and_donts.html

Last checked: 2026-10-20

This is a draft for review. It has not been sent.
```

## Source list

| Source | URL | Used for |
|---|---|---|
| Groww: Pricing and charges | https://groww.in/pricing | Fee explainer: every Groww charge and rate (official link 1) |
| SEBI investor website: Securities market do's and don'ts | https://investor.sebi.gov.in/securities-dos_and_donts.html | Fee explainer: contract note within 24 hours, note all charges (official link 2) |
| CDSL: DP tariff structure (Rs 3.50 per debit transaction) | https://www.cdslindia.com/DP/CurrentDPs.html | Cross-check of the ₹3.50 depository part of the DP charge |
| SEBI investor charter (contract notes in complaint documents) | https://investor.sebi.gov.in/Investor-charter.html | Contract notes as the record of a trade |
| Groww on Google Play (review source) | https://play.google.com/store/apps/details?id=com.nextbillion.groww | Source of the public reviews in data/reviews.csv |

## Deliverables in this repo

| Deliverable | File |
|---|---|
| Working prototype | https://<your-app>.streamlit.app (code: `app.py`) |
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
- Fee facts were checked by hand against the official pages on 2026-10-20. Charges can change, so
  the explainer shows its "Last checked" date.

## Privacy

Only public review text is kept. Reviewer names and photos are dropped, and anything that looks like an email,
phone number, PAN, Aadhaar or account number inside a review is replaced with `[redacted]`. Quotes that name a
person are skipped.

## Disclaimer

Facts-only. This tool summarises public reviews and official fee information. It does not give investment advice.
