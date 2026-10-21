"""MCP server exposing the two internal-tool actions of the workflow.

Started by the app (or run_pipeline.py) over stdio. Tools:
- append_to_notes:     appends one entry to the team notes document
- create_email_draft:  saves an email DRAFT (there is no send tool at all)
- read_notes:          returns the latest notes entries, to show what was appended

Approval gate: the two write tools refuse to run unless they get an
approval_token that was created when a human clicked Approve, and the token
must match a hash of the exact payload. So a model or script cannot call them
on its own, and an approved payload cannot be swapped for another one.

Backends are local files: a Markdown notes document, and .eml drafts that
Apple Mail, Outlook or Thunderbird open as editable drafts.
"""
import datetime as dt
import json
import re
import sys
from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp.server.fastmcp import FastMCP  # noqa: E402

from pulse.approval import RUNTIME, consume_approval  # noqa: E402

NOTES_DOC = RUNTIME / "Groww_Product_Notes.md"
NOTES_LOG = RUNTIME / "notes_log.jsonl"
DRAFTS = RUNTIME / "drafts"

mcp = FastMCP("groww-pulse-tools")


def _demote_headings(md: str) -> str:
    """Nest the pulse's headings under the entry heading (# -> ###)."""
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", md, flags=re.M)


@mcp.tool()
def append_to_notes(date: str, top_themes: list[str], weekly_pulse: str, identified_fee_issue: str,
                    explanation_bullets: list[str], source_links: list[str], approval_token: str) -> dict:
    """Append this week's pulse entry to the team notes document. Needs a human approval_token."""
    args = {"date": date, "top_themes": top_themes, "weekly_pulse": weekly_pulse,
            "identified_fee_issue": identified_fee_issue, "explanation_bullets": explanation_bullets,
            "source_links": source_links}
    err = consume_approval("append_to_notes", args, approval_token)
    if err:
        return {"ok": False, "error": err}
    RUNTIME.mkdir(parents=True, exist_ok=True)
    if not NOTES_DOC.exists():
        NOTES_DOC.write_text("# Groww Product Notes\n\nWeekly entries appended by the review-pulse workflow.\n",
                             encoding="utf-8")
    entry = [
        "", "---", "", f"## Entry: {date}", "",
        f"**Top themes:** {', '.join(top_themes)}", "",
        f"**Identified fee issue:** {identified_fee_issue}", "",
        "**Weekly pulse:**", "", _demote_headings(weekly_pulse.strip()), "",
        "**Fee explanation (support snippet):**", "",
        *[f"- {b}" for b in explanation_bullets], "",
        "**Sources:** " + " | ".join(source_links), "",
    ]
    with NOTES_DOC.open("a", encoding="utf-8") as f:
        f.write("\n".join(entry))
    with NOTES_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**args, "appended_at": dt.datetime.now().isoformat(timespec="seconds")},
                           ensure_ascii=False) + "\n")
    total = sum(1 for _ in NOTES_LOG.open(encoding="utf-8"))
    return {"ok": True, "document": NOTES_DOC.name, "entry_heading": f"Entry: {date}", "entries_in_doc": total}


@mcp.tool()
def create_email_draft(subject: str, body: str, approval_token: str, to: str = "") -> dict:
    """Save an email draft for a human to review and send. This tool never sends email."""
    args = {"subject": subject, "body": body, "to": to}
    err = consume_approval("create_email_draft", args, approval_token)
    if err:
        return {"ok": False, "error": err}
    DRAFTS.mkdir(parents=True, exist_ok=True)
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["To"] = to
    msg["Date"] = formatdate(localtime=True)
    msg["X-Unsent"] = "1"  # mail apps open this as an editable draft
    msg.set_content(body)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    eml = DRAFTS / f"draft-{stamp}.eml"
    eml.write_bytes(bytes(msg))
    (DRAFTS / f"draft-{stamp}.txt").write_text(f"To: {to}\nSubject: {subject}\n\n{body}", encoding="utf-8")
    return {"ok": True, "draft_file": eml.name, "status": "DRAFT (not sent)", "subject": subject}


@mcp.tool()
def read_notes(last_n: int = 1) -> dict:
    """Return the last N entries appended to the notes document (read only)."""
    if not NOTES_LOG.exists():
        return {"entries": [], "total": 0}
    rows = [json.loads(line) for line in NOTES_LOG.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {"entries": rows[-last_n:], "total": len(rows)}


if __name__ == "__main__":
    mcp.run()  # stdio transport
