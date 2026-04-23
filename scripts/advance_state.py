#!/usr/bin/env python3
"""Mark a workflow stage run complete and update refinement state."""

from __future__ import annotations

import argparse
import sys

from refinement_lib import (
    RefinementError,
    complete_current_stage,
    load_stage_config,
    load_state,
    save_state,
    validate_state,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", required=True, help="Page or cluster id to update.")
    parser.add_argument(
        "--result",
        required=True,
        choices=("success", "partial", "blocked", "failed"),
        help="Result of the completed pass.",
    )
    parser.add_argument("--notes", default="", help="Optional notes to append to the state record.")
    return parser


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        stage_config = load_stage_config()
        state = load_state()
        validate_state(state, stage_config)
        if args.page not in state["pages"]:
            raise RefinementError(f"Unknown page or cluster id: {args.page}")
        item = state["pages"][args.page]
        original_stage = item["stage"]
        complete_current_stage(state, args.page, args.result, args.notes, stage_config)
        save_state(state)
        updated = state["pages"][args.page]
        print(
            f"Updated {args.page}: stage {original_stage} -> {updated['stage']}, "
            f"last_result={updated['last_result']}, last_run={updated['last_run']}"
        )
        return 0
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
