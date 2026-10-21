"""Run the whole workflow from the terminal, with a y/N approval prompt before any MCP action.

    python run_pipeline.py                 # use saved analysis and outputs
    python run_pipeline.py --regenerate    # re-write the pulse and explainer (Steps 2-3)
    python run_pipeline.py --reanalyse     # redo Step 1 too (themes + labels for every review)
    python run_pipeline.py --fetch         # download fresh reviews first
"""
import argparse
import json
import logging

from pulse import analysis, approval, mcp_client, writer


def ask(question: str) -> bool:
    return input(f"{question} [y/N] ").strip().lower() in {"y", "yes"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--reanalyse", action="store_true")
    ap.add_argument("--regenerate", action="store_true")
    ap.add_argument("--to", default="", help="recipient to put on the email draft")
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING)

    if args.fetch:
        import fetch_reviews
        fetch_reviews.main(weeks=10)
    a = analysis.run(force=args.reanalyse, progress=lambda f, m: print(f"  {m}"))
    out = writer.build_all(a, force=args.reanalyse or args.regenerate)

    print("\n=== STEP 1: top themes ===")
    for t in a["top_themes"]:
        print(f"- {t['name']}: {t['reviews']} reviews ({t['share'] * 100:.0f}%)")
    print(f"Fee issue: {a['fee_issue']['name']}")
    print("\n=== STEP 2: weekly pulse ===\n" + out["pulse"]["markdown"])
    print("=== STEP 3: fee explainer ===\n" + out["explainer"]["markdown"])

    tools = [t["name"] for t in mcp_client.list_tools()]
    print(f"=== STEP 4: MCP server tools: {', '.join(tools)} ===")
    plan = [("append_to_notes", out["notes_payload"]),
            ("create_email_draft", {**out["email_payload"], "to": args.to})]
    for tool, payload in plan:
        print(f"\nProposed action: {tool}")
        print(json.dumps({k: (v[:300] + "..." if isinstance(v, str) and len(v) > 300 else v)
                          for k, v in payload.items()}, indent=2, ensure_ascii=False))
        if ask(f"Approve {tool}?"):
            token = approval.record_approval(tool, payload, approver="cli-user")
            print("Result:", mcp_client.call_tool(tool, {**payload, "approval_token": token}))
        else:
            approval.record_rejection(tool, payload, approver="cli-user")
            print("Rejected. Nothing was written.")


if __name__ == "__main__":
    main()
