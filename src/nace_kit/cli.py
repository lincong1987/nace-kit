"""Command-line smoke test: classify a piece of text from argv.

Examples:
    nace-kit "Help! My payouts have been failing for 3 days."
    nace-kit "..." --ask "How angry is the user?" --kind score --levels calm annoyed angry furious
    nace-kit "..." --ask "What is this about?" --kind choice --options billing:"payment issues" technical:"bugs and outages"
    nace-kit --models
"""

from __future__ import annotations

import argparse
import json
import sys

from .client import NaceClient, NaceError
from . import presets


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="nace-kit", description="Classify text via the nace.ai Drex API."
    )
    p.add_argument("state", nargs="?", help="text (or JSON) to classify")
    p.add_argument("--ask", default=None, help="question text (default: urgency preset)")
    p.add_argument("--kind", choices=["noul", "score", "choice"], default="noul")
    p.add_argument("--levels", nargs="+", default=None, help="level labels for --kind score")
    p.add_argument(
        "--options",
        nargs="+",
        default=None,
        metavar="LABEL[:DESC]",
        help="labels for --kind choice, e.g. billing:'payment issues' technical",
    )
    p.add_argument("--model", default=None, help="model name (default: drex-latest)")
    p.add_argument("--models", action="store_true", help="list available models and exit")
    p.add_argument("--no-cache", action="store_true")
    args = p.parse_args(argv)

    try:
        client = NaceClient(
            model=args.model or "drex-latest",
            cache_size=0 if args.no_cache else 256,
        )

        if args.models:
            print(json.dumps(client.models(), indent=2, ensure_ascii=False))
            return 0

        if args.state is None:
            p.error("a state argument is required unless --models is given")

        if args.ask is None:
            question = presets.urgency()
        elif args.kind == "score":
            question = presets.score(args.ask, args.levels or ["low", "medium", "high"])
        elif args.kind == "choice":
            options: dict[str, str | None] = {}
            for item in args.options or []:
                label, sep, desc = item.partition(":")
                options[label] = desc if sep else None
            question = presets.choice(args.ask, options or {"yes": None, "no": None})
        else:
            question = presets.noul(args.ask)

        result = client.classify(args.state, question)
    except NaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
