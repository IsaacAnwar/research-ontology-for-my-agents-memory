import argparse
import json
import os
import re
import sys
from pathlib import Path

from kg.vault import Vault

WHITESPACE = re.compile(r"\s*")


def records(files):
    decoder = json.JSONDecoder()
    sources = [Path(f).read_text() for f in files] if files else [sys.stdin.read()]
    for text in sources:
        pos = WHITESPACE.match(text).end()
        while pos < len(text):
            data, pos = decoder.raw_decode(text, pos)
            yield from data if isinstance(data, list) else [data]
            pos = WHITESPACE.match(text, pos).end()


def log_runs(vault, files):
    logged, skipped = [], []
    for record in records(files):
        try:
            logged.append(vault.log_run(record))
        except FileExistsError as e:
            skipped.append(str(e))
    return {"logged": logged, "skipped": skipped, "check": vault.check()}


def main():
    parser = argparse.ArgumentParser(prog="kg")
    parser.add_argument("--vault", default=os.environ.get("KG_VAULT", "."))
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init").add_argument("path", nargs="?")
    sub.add_parser("log-run").add_argument("files", nargs="*")
    sub.add_parser("propose")
    sub.add_parser("check")
    search = sub.add_parser("search")
    search.add_argument("text")
    search.add_argument("--kind", choices=["run", "claim", "question"])
    search.add_argument("--limit", type=int, default=10)
    sub.add_parser("why").add_argument("id")
    sub.add_parser("impact").add_argument("id")
    invalidate = sub.add_parser("invalidate")
    invalidate.add_argument("id")
    invalidate.add_argument("--reason", required=True)
    args = parser.parse_args()

    vault = Vault(getattr(args, "path", None) or args.vault)
    commands = {
        "init": lambda: vault.init(),
        "log-run": lambda: log_runs(vault, args.files),
        "propose": lambda: vault.propose(**json.load(sys.stdin)),
        "check": lambda: vault.check(),
        "search": lambda: vault.search(args.text, args.kind, args.limit),
        "why": lambda: vault.why(args.id),
        "impact": lambda: vault.impact(args.id),
        "invalidate": lambda: vault.invalidate(args.id, args.reason),
    }
    try:
        result = commands[args.command]()
    except (ValueError, FileNotFoundError, TypeError) as e:
        sys.exit(f"kg: {e}")
    print(json.dumps(result, indent=2, default=str))
