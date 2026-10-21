"""Human approval records shared by the MCP client (writes them) and server (checks them).

An approval is tied to one tool and a SHA-256 hash of the exact arguments,
and can be used once.
"""
import datetime as dt
import hashlib
import json
import os
import secrets
from pathlib import Path

RUNTIME = Path(os.environ.get("PULSE_RUNTIME_DIR",
                              Path(__file__).resolve().parent.parent / "outputs" / "runtime"))
APPROVALS = RUNTIME / "approvals.json"


def payload_hash(tool: str, args: dict) -> str:
    return hashlib.sha256(json.dumps([tool, args], sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _load() -> dict:
    return json.loads(APPROVALS.read_text()) if APPROVALS.exists() else {}


def record_approval(tool: str, args: dict, approver: str = "user") -> str:
    """Called only from the UI's Approve button (or the CLI's y/N prompt)."""
    RUNTIME.mkdir(parents=True, exist_ok=True)
    book = _load()
    token = secrets.token_urlsafe(16)
    book[token] = {"tool": tool, "hash": payload_hash(tool, args), "approver": approver,
                   "approved_at": dt.datetime.now().isoformat(timespec="seconds"), "used": False}
    APPROVALS.write_text(json.dumps(book, indent=2))
    return token


def record_rejection(tool: str, args: dict, approver: str = "user") -> None:
    RUNTIME.mkdir(parents=True, exist_ok=True)
    book = _load()
    book[f"rejected-{secrets.token_hex(4)}"] = {"tool": tool, "hash": payload_hash(tool, args),
                                                "approver": approver, "rejected": True, "used": True,
                                                "approved_at": None,
                                                "rejected_at": dt.datetime.now().isoformat(timespec="seconds")}
    APPROVALS.write_text(json.dumps(book, indent=2))


def consume_approval(tool: str, args: dict, token: str) -> str | None:
    """Return an error message, or None if the approval is valid (it is then used up)."""
    book = _load()
    rec = book.get(token)
    if not rec or rec.get("rejected"):
        return "No valid human approval for this action. Approve it in the app first."
    if rec.get("used"):
        return "This approval was already used. Each approval runs one action once."
    if rec.get("tool") != tool or rec.get("hash") != payload_hash(tool, args):
        return "The payload does not match what was approved. Ask for approval again."
    rec["used"] = True
    rec["used_at"] = dt.datetime.now().isoformat(timespec="seconds")
    APPROVALS.write_text(json.dumps(book, indent=2))
    return None


def audit_log() -> list[dict]:
    return [{"token": k[:6] + "...", **v} for k, v in _load().items()]
