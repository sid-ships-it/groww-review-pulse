"""Download recent public Google Play reviews for Groww into data/reviews.csv.

Usage:  python fetch_reviews.py --weeks 10

Only public review fields are kept. Reviewer names and profile images are
dropped, and anything that looks like personal data inside the review text
(emails, phone numbers, PAN, Aadhaar, account numbers) is replaced with
[redacted] before the file is written.
"""
import argparse
import csv
import datetime as dt
import hashlib
import re
import time
from pathlib import Path

from google_play_scraper import Sort, reviews

APP_ID = "com.nextbillion.groww"
OUT = Path(__file__).parent / "data" / "reviews.csv"

PII_PATTERNS = [
    re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+"),                 # email
    re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I),            # PAN
    re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"),               # Aadhaar-like
    re.compile(r"(?:\+?91[\s-]?)?\b[6-9]\d{9}\b"),          # Indian mobile
    re.compile(r"\b\d{9,18}\b"),                            # account-number-like
]


def scrub(text: str) -> str:
    for pat in PII_PATTERNS:
        text = pat.sub("[redacted]", text)
    return " ".join(text.split())


def main(weeks: int, end: dt.date | None = None) -> None:
    end = end or (dt.date.today() - dt.timedelta(days=1))
    start = end - dt.timedelta(weeks=weeks) + dt.timedelta(days=1)  # whole Mon-Sun weeks
    start_dt = dt.datetime.combine(start, dt.time.min)
    end_dt = dt.datetime.combine(end, dt.time.max)

    rows, token = [], None
    for _ in range(200):
        batch, token = reviews(APP_ID, lang="en", country="in", sort=Sort.NEWEST,
                               count=200, continuation_token=token)
        rows += batch
        if not batch or token is None or batch[-1]["at"] < start_dt:
            break
        time.sleep(0.3)

    kept = [r for r in rows if start_dt <= r["at"] <= end_dt]
    OUT.parent.mkdir(exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["review_id", "date", "rating", "text", "app_version", "thumbs_up", "source"])
        for r in kept:
            rid = hashlib.sha1(r["reviewId"].encode()).hexdigest()[:12]
            w.writerow([rid, r["at"].strftime("%Y-%m-%d"), r["score"], scrub(r["content"] or ""),
                        r.get("reviewCreatedVersion") or "", r.get("thumbsUpCount") or 0,
                        "Google Play (India, English)"])
    print(f"Saved {len(kept)} reviews from {start} to {end} -> {OUT}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--weeks", type=int, default=10)
    ap.add_argument("--end", type=lambda s: dt.date.fromisoformat(s), default=None,
                    help="last day to include (YYYY-MM-DD); default is yesterday")
    a = ap.parse_args()
    main(a.weeks, a.end)
