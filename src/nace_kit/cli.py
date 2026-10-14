"""Command-line smoke test: classify a piece of text from argv.

Examples:
    nace-kit "Help! My payouts have been failing for 3 days."
    nace-kit "..." --ask "How angry is the user?" --kind score --levels calm annoyed angry furious
    nace-kit "..." --ask "What is this about?" --kind choice --options billing:"payment issues" technical:"bugs"
    nace-kit --models
    nace-kit --install-skill [--claude]
"""

from __future__ import annotations

import argparse
import json
import sys
from importlib import resources
from pathlib import Path

from .client import NaceClient, NaceError
from . import presets

#: Agent-skill frontmatter requires these fields; a quick check catches broken packaging.
_SKILL_MIN_BYTES = 200


def install_skill(target_dir: Path) -> Path:
    """Copy the bundled Agent Skill (SKILL.md) into ``target_dir/nace-kit/``."""
    src = resources.files("nace_kit") / "skills" / "nace-kit" / "SKILL.md"
    text = src.read_text(encoding="utf-8")
    if len(text) < _SKILL_MIN_BYTES or not text.startswith("---"):
        raise NaceError("bundled SKILL.md looks broken; reinstall nace-kit")
    dest_dir = target_dir / "nace-kit"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "SKILL.md"
    dest.write_text(text, encoding="utf-8")
    return dest


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
    p.add_argument(
        "--install-skill",
        action="store_true",
        help="install the Agent Skill (SKILL.md) for agent use and exit",
    )
    p.add_argument(
        "--claude",
        action="store_true",
        help="with --install-skill: target ~/.claude/skills instead of ~/.agents/skills",
    )
    p.add_argument(
        "--skill-dir",
        default=None,
        metavar="DIR",
        help="with --install-skill: explicit target directory",
    )
    args = p.parse_args(argv)

    if args.install_skill:
        if args.skill_dir:
            target = Path(args.skill_dir)
        elif args.claude:
            target = Path.home() / ".claude" / "skills"
        else:
            target = Path.home() / ".agents" / "skills"
        try:
            dest = install_skill(target)
        except NaceError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        print(f"skill installed: {dest}")
        return 0

    try:
        client = NaceClient(
            model=args.model or "drex-latest",
            cache_size=0 if args.no_cache else 256,
        )

        if args.models:
            print(json.dumps(client.models().model_dump(mode="json"), indent=2, ensure_ascii=False))
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
    print(json.dumps(result.model_dump(mode="json"), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
