#!/usr/bin/env python3
"""Main CLI entry point for the FS3 refinement workflow."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from refinement_lib import (
    PRIORITIES_PATH,
    STATE_PATH,
    STAGES_PATH,
    RefinementError,
    item_summary,
    list_candidates,
    load_priority_config,
    load_stage_config,
    load_state,
    next_stage_for_item,
    save_state,
    seed_state_from_repo,
    select_next_item,
    update_item_stage,
    validate_state,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--next", action="store_true", help="Select the next recommended work item.")
    parser.add_argument("--page", help="Inspect or operate on a specific page or cluster id.")
    parser.add_argument("--stage", help="Filter to or advance toward a specific stage.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned changes without saving.")
    parser.add_argument("--advance", action="store_true", help="Advance a specific item to the next legal stage or to --stage.")
    parser.add_argument("--report", action="store_true", help="Print a short state summary.")
    parser.add_argument("--list", action="store_true", help="List recommended work items.")
    parser.add_argument("--flagship-only", action="store_true", help="Limit selection to flagship items.")
    parser.add_argument("--beta-visible-only", action="store_true", help="Limit selection to public-beta-visible items.")
    parser.add_argument("--validate", action="store_true", help="Validate the workflow configuration and state.")
    parser.add_argument("--bootstrap", action="store_true", help="Regenerate seed state from the current repo content.")
    parser.add_argument("--limit", type=int, default=None, help="Optional list/report limit override.")
    return parser


def print_report(state: dict, priority_config: dict, *, limit: int | None) -> None:
    """Print a small terminal report."""

    candidates = list_candidates(state, priority_config, limit=limit)
    print(f"State file: {STATE_PATH.relative_to(Path.cwd()) if STATE_PATH.is_relative_to(Path.cwd()) else STATE_PATH}")
    print(f"Stage config: {STAGES_PATH.relative_to(Path.cwd()) if STAGES_PATH.is_relative_to(Path.cwd()) else STAGES_PATH}")
    print(f"Priority config: {PRIORITIES_PATH.relative_to(Path.cwd()) if PRIORITIES_PATH.is_relative_to(Path.cwd()) else PRIORITIES_PATH}")
    print(f"Tracked items: {len(state['pages'])}")
    print(f"Recommended queue length shown: {len(candidates)}")
    if candidates:
        top = candidates[0]
        print(
            f"Top item: {top.item_id} (stage={top.item['stage']}, next={next_stage_for_item(top.item, load_stage_config())}, score={top.score})"
        )


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        stage_config = load_stage_config()
        priority_config = load_priority_config()
        if args.bootstrap:
            state = seed_state_from_repo()
            validate_state(state, stage_config)
            if args.dry_run:
                print("Bootstrap preview complete. No files written.")
                print(f"Would write {len(state['pages'])} items to {STATE_PATH}")
            else:
                save_state(state)
                print(f"Seeded {len(state['pages'])} items into {STATE_PATH}")
            return 0

        state = load_state()
        validate_state(state, stage_config)

        if args.validate:
            print("Workflow state and configuration are valid.")
            return 0

        if args.report:
            print_report(state, priority_config, limit=args.limit)
            return 0

        if args.list:
            candidates = list_candidates(
                state,
                priority_config,
                stage_filter=args.stage,
                flagship_only=args.flagship_only,
                beta_visible_only=args.beta_visible_only,
                limit=args.limit,
            )
            if not candidates:
                print("No matching work items found.")
                return 0
            for candidate in candidates:
                reasons = ", ".join(candidate.reasons)
                print(
                    f"{candidate.item_id}\tscore={candidate.score}\tstage={candidate.item['stage']}\tnext={next_stage_for_item(candidate.item, stage_config)}\t{reasons}"
                )
            return 0

        if args.next:
            candidate = select_next_item(
                state,
                priority_config,
                stage_filter=args.stage,
                flagship_only=args.flagship_only,
                beta_visible_only=args.beta_visible_only,
            )
            if candidate is None:
                print("No eligible next item found.")
                return 0
            print(f"Next target: {candidate.item_id}")
            print(item_summary(candidate.item_id, candidate.item))
            print(f"Recommended current stage: {candidate.item['stage']}")
            print(f"Recommended next stage after success: {next_stage_for_item(candidate.item, stage_config)}")
            print(f"Selection score: {candidate.score}")
            print("Reasons:")
            for reason in candidate.reasons:
                print(f"- {reason}")
            return 0

        if args.page and not args.advance:
            if args.page not in state["pages"]:
                raise RefinementError(f"Unknown page or cluster id: {args.page}")
            item = state["pages"][args.page]
            print(item_summary(args.page, item))
            print(f"Recommended next stage after success: {next_stage_for_item(item, stage_config)}")
            if args.stage:
                print(f"Stage filter requested: {args.stage}")
            return 0

        if args.advance:
            if not args.page:
                raise RefinementError("--advance requires --page.")
            if args.page not in state["pages"]:
                raise RefinementError(f"Unknown page or cluster id: {args.page}")
            item = state["pages"][args.page]
            target_stage = args.stage or next_stage_for_item(item, stage_config)
            original_stage = item["stage"]
            update_item_stage(state, args.page, target_stage, stage_config)
            if args.dry_run:
                print(f"Would advance {args.page} from {original_stage} to {target_stage}")
            else:
                save_state(state)
                print(f"Advanced {args.page} from {original_stage} to {target_stage}")
            return 0

        parser.print_help()
        return 0
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
