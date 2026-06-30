#!/usr/bin/env python3
"""CLI chat loop for the EquiTie Investor Assistant.

Usage:
    python cli.py --investor INV001
    python cli.py --investor INV001 --ask "How is my portfolio doing?"
    python cli.py --list            # list investors

The investor is "logged in" -- the assistant only ever sees their data.
"""

from __future__ import annotations

import argparse
import sys

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

from equitie.data import DataStore
from equitie.assistant import Assistant


def main():
    ap = argparse.ArgumentParser(description="EquiTie Investor Assistant (CLI)")
    ap.add_argument("--investor", "-i", default="INV001", help="logged-in investor_id")
    ap.add_argument("--ask", "-a", help="ask a single question and exit")
    ap.add_argument("--list", action="store_true", help="list investors and exit")
    ap.add_argument("--data-dir", help="override dataset directory")
    args = ap.parse_args()

    store = DataStore(args.data_dir)

    if args.list:
        for r in store.list_investors().itertuples(index=False):
            print(f"{r.investor_id}  {r.investor_name:<28} {r.reporting_currency}")
        return

    try:
        assistant = Assistant(store, args.investor)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    inv = store.investor_by_id[args.investor]
    mode = "Claude" if assistant.online else "OFFLINE (deterministic)"
    print(f"EquiTie Investor Assistant  |  logged in as {args.investor} "
          f"({inv['investor_name']}, {inv['reporting_currency']})  |  mode: {mode}")

    def handle(q):
        out = assistant.ask(q)
        print("\n" + out["text"])
        if out["sources"]:
            print("\n  [sources: " + ", ".join(out["sources"][:12]) +
                  (" ...]" if len(out["sources"]) > 12 else "]"))
        print()

    if args.ask:
        handle(args.ask)
        return

    print("Type your question (or 'quit').\n")
    while True:
        try:
            q = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in {"quit", "exit", "q"}:
            break
        if q:
            handle(q)


if __name__ == "__main__":
    main()
