#!/usr/bin/env python3
"""Operator-facing CLI for running the FS3 refinement workflow with one command."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from build_dashboard import MARKDOWN_OUTPUT, build_dashboard_payload, render_dashboard_markdown, write_dashboard_outputs
from check_links import find_broken_links
from check_placeholders import scan_placeholder_hits
from refinement_lib import (
    ROOT,
    STATE_PATH,
    RefinementError,
    atomic_write_text,
    complete_current_stage,
    load_all_configs,
    load_stage_config,
    load_state,
    next_stage_for_item,
    recent_items,
    render_stage_prompt,
    save_state,
    select_next_item,
    validate_state,
)


PROMPT_OUTPUT = ROOT / "prompts" / "current-task.md"
PROMPT_HISTORY_DIR = ROOT / "prompts" / "history"
VALID_RESULTS = ("success", "partial", "blocked", "failed")


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group(required=True)
    actions.add_argument("--next", action="store_true", help="Select the next recommended target and generate its prompt.")
    actions.add_argument("--cluster", help="Generate a prompt for a specific cluster id.")
    actions.add_argument("--page", help="Generate a prompt for a specific page id.")
    actions.add_argument("--complete", metavar="PAGE_OR_CLUSTER_ID", help="Mark the current stage complete for the given target.")
    actions.add_argument("--report", action="store_true", help="Rebuild and print the dashboard summary.")
    actions.add_argument("--validate", action="store_true", help="Run validation plus link and placeholder checks.")
    actions.add_argument("--history", action="store_true", help="List recently updated workflow items.")
    parser.add_argument("--flagship-only", action="store_true", help="Limit automatic selection to flagship items.")
    parser.add_argument("--beta-visible-only", action="store_true", help="Limit automatic selection to public-beta-visible items.")
    parser.add_argument("--result", choices=VALID_RESULTS, help="Completion result for --complete.")
    parser.add_argument("--notes", default="", help="Optional note for --complete.")
    parser.add_argument("--stdout", action="store_true", help="Print the generated prompt instead of writing it to files.")
    parser.add_argument("--open", action="store_true", help="Print a shell command you can use to open the prompt file.")
    parser.add_argument("--limit", type=int, default=10, help="Maximum items to print for --history.")
    return parser


def require_state_file() -> None:
    """Fail clearly if the state file is missing."""

    if not STATE_PATH.exists():
        raise RefinementError(
            f"Workflow state file is missing: {STATE_PATH}. "
            "Run `python scripts/refinement_runner.py --bootstrap` first."
        )


def reason_text(reasons: list[str]) -> str:
    """Render concise human-readable candidate reasons."""

    return " + ".join(reasons) if reasons else "manual selection"


def resolve_manual_target(
    state: dict,
    *,
    target_id: str,
    expected_mode: str | None,
) -> tuple[str, dict, str]:
    """Resolve a manually specified page or cluster."""

    if target_id not in state["pages"]:
        raise RefinementError(f"Unknown page or cluster id: {target_id}")
    item = state["pages"][target_id]
    if expected_mode == "cluster" and item["type"] != "cluster":
        raise RefinementError(f"{target_id} is a {item['type']}, not a cluster.")
    if expected_mode == "page" and item["type"] == "cluster":
        raise RefinementError(f"{target_id} is a cluster. Use --cluster for cluster targets.")
    if item["stage"] == "complete":
        raise RefinementError(f"{target_id} is already at the complete stage. Nothing to generate.")
    return target_id, item, "manual selection"


def write_prompt_files(target_id: str, stage_name: str, prompt: str) -> tuple[Path, Path]:
    """Write current and history prompt files."""

    PROMPT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = PROMPT_HISTORY_DIR / f"{target_id}-{stage_name}.md"
    atomic_write_text(PROMPT_OUTPUT, prompt + "\n")
    atomic_write_text(history_path, prompt + "\n")
    return PROMPT_OUTPUT, history_path


def print_selection_summary(
    *,
    target_id: str,
    item: dict,
    next_stage: str,
    reason: str,
    prompt_path: Path | None,
    history_path: Path | None,
    stdout_prompt: bool,
    open_prompt: bool,
) -> None:
    """Print concise operator-facing task output."""

    print(f"Next target: {target_id}")
    print(f"Type: {item['type']}")
    print(f"Status: {item['status']}")
    print(f"Confidence: {item['confidence']}")
    print(f"Current stage: {item['stage']}")
    print(f"Recommended next stage: {next_stage}")
    print(f"Reason: {reason}")
    if stdout_prompt:
        print("\nPrompt written to: stdout")
    elif prompt_path is not None:
        print("\nPrompt written to:")
        print(prompt_path.relative_to(ROOT))
        if history_path is not None:
            print(history_path.relative_to(ROOT))
        if open_prompt:
            print("\nOpen command:")
            print(f"code {prompt_path.relative_to(ROOT)}")
    print("\nAfter Codex finishes, run:")
    print(
        "python scripts/run_next_task.py "
        f"--complete {target_id} --result success --notes \"{item['stage'].title()} pass completed and pushed\""
    )


def select_target_from_args(args: argparse.Namespace) -> tuple[str, dict, str]:
    """Resolve the item targeted by operator selection flags."""

    state, stage_config, priority_config = load_all_configs()
    if args.next:
        candidate = select_next_item(
            state,
            priority_config,
            flagship_only=args.flagship_only,
            beta_visible_only=args.beta_visible_only,
        )
        if candidate is None:
            raise RefinementError("No eligible next item found.")
        return candidate.item_id, candidate.item, reason_text(candidate.reasons)
    if args.cluster:
        return resolve_manual_target(state, target_id=args.cluster, expected_mode="cluster")
    if args.page:
        return resolve_manual_target(state, target_id=args.page, expected_mode="page")
    raise RefinementError("No target selection mode was provided.")


def handle_prompt_generation(args: argparse.Namespace) -> int:
    """Select or resolve a target and generate its prompt."""

    target_id, item, reason = select_target_from_args(args)
    stage_config = load_stage_config()
    current_stage = item["stage"]
    if current_stage == "complete":
        raise RefinementError(f"{target_id} is already complete.")
    prompt = render_stage_prompt(target_id, item, current_stage)
    next_stage = next_stage_for_item(item, stage_config)
    prompt_path: Path | None = None
    history_path: Path | None = None
    if args.stdout:
        print(prompt)
    else:
        prompt_path, history_path = write_prompt_files(target_id, current_stage, prompt)
    print_selection_summary(
        target_id=target_id,
        item=item,
        next_stage=next_stage,
        reason=reason,
        prompt_path=prompt_path,
        history_path=history_path,
        stdout_prompt=args.stdout,
        open_prompt=args.open,
    )
    return 0


def handle_completion(args: argparse.Namespace) -> int:
    """Complete the current stage for a target and rebuild the dashboard."""

    if not args.result:
        raise RefinementError("--complete requires --result success|partial|blocked|failed.")
    state, stage_config, _ = load_all_configs()
    target_id = args.complete
    if target_id not in state["pages"]:
        raise RefinementError(f"Unknown page or cluster id: {target_id}")
    item = state["pages"][target_id]
    previous_stage = item["stage"]
    complete_current_stage(state, target_id, args.result, args.notes, stage_config)
    save_state(state)
    payload = build_dashboard_payload()
    write_dashboard_outputs(payload)
    updated = state["pages"][target_id]
    print(f"Completed target: {target_id}")
    print(f"Result: {args.result}")
    print(f"Stage: {previous_stage} -> {updated['stage']}")
    print(f"Last run: {updated['last_run']}")
    print(f"Dashboard rebuilt: {MARKDOWN_OUTPUT.relative_to(ROOT)}")
    return 0


def handle_report() -> int:
    """Rebuild the dashboard and print its markdown summary."""

    payload = build_dashboard_payload()
    write_dashboard_outputs(payload)
    print(render_dashboard_markdown(payload))
    return 0


def handle_validation() -> int:
    """Run validation and optional checks."""

    require_state_file()
    state = load_state()
    stage_config = load_stage_config()
    validate_state(state, stage_config)
    failures: list[str] = []
    link_issues = find_broken_links()
    placeholder_hits = scan_placeholder_hits()
    if link_issues:
        failures.append("Broken links:\n" + "\n".join(link_issues))
    if placeholder_hits:
        preview = "\n".join(placeholder_hits[:20])
        extra = "" if len(placeholder_hits) <= 20 else f"\n... {len(placeholder_hits) - 20} more"
        failures.append("Placeholder language detected:\n" + preview + extra)
    if failures:
        print("Validation failed:", file=sys.stderr)
        for block in failures:
            print(block, file=sys.stderr)
            print("", file=sys.stderr)
        return 1
    print("Validation passed.")
    print("No broken links or placeholder language detected.")
    return 0


def handle_history(limit: int) -> int:
    """Print recently updated workflow items."""

    state, _, _ = load_all_configs()
    rows = recent_items(state, days=3650)[:limit]
    if not rows:
        print("No workflow history recorded yet.")
        return 0
    print("Recent workflow items:")
    for item_id, item in rows:
        print(
            f"- {item_id}: last_run={item['last_run']}, last_result={item['last_result']}, "
            f"stage={item['stage']}, status={item['status']}"
        )
    return 0


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        require_state_file()
        if args.complete:
            return handle_completion(args)
        if args.report:
            return handle_report()
        if args.validate:
            return handle_validation()
        if args.history:
            return handle_history(args.limit)
        return handle_prompt_generation(args)
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
