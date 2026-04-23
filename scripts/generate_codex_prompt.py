#!/usr/bin/env python3
"""Generate a Codex-ready prompt for a page or cluster and stage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from refinement_lib import (
    RefinementError,
    atomic_write_text,
    load_stage_config,
    load_state,
    render_stage_prompt,
    stage_applies,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True, help="Page or cluster id from refinement-state.yaml.")
    parser.add_argument("--stage", required=True, help="Stage to generate a prompt for.")
    parser.add_argument(
        "--output",
        choices=("stdout", "file"),
        default="file",
        help="Write the prompt to stdout or a file.",
    )
    parser.add_argument(
        "--write",
        default="prompts/current-task.md",
        help="Output path when --output file is used.",
    )
    return parser


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        stage_config = load_stage_config()
        state = load_state()
        if args.page not in state["pages"]:
            raise RefinementError(f"Unknown page or cluster id: {args.page}")
        if args.stage not in stage_config["ordered_stages"]:
            raise RefinementError(f"Unknown stage: {args.stage}")
        item = state["pages"][args.page]
        if not stage_applies(item["type"], args.stage, stage_config):
            raise RefinementError(f"Stage {args.stage} does not apply to {item['type']} items.")
        prompt = render_stage_prompt(args.page, item, args.stage)
        if args.output == "stdout":
            print(prompt)
        else:
            output_path = Path(args.write)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_text(output_path, prompt + "\n")
            print(output_path)
        return 0
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
