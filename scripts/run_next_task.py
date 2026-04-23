#!/usr/bin/env python3
"""Operator-facing CLI for running the FS3 refinement workflow with one command."""

from __future__ import annotations

import argparse
from copy import deepcopy
import sys
from pathlib import Path
from typing import Any

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
    save_yaml,
    select_next_item,
    validate_state,
)


PROMPT_OUTPUT = ROOT / "prompts" / "current-task.md"
PROMPT_HISTORY_DIR = ROOT / "prompts" / "history"
BATCH_DIR = ROOT / "prompts" / "batch"
BATCH_RUN_ALL = BATCH_DIR / "run-all.md"
BATCH_MANIFEST = BATCH_DIR / "manifest.yaml"
VALID_RESULTS = ("success", "partial", "blocked", "failed")


def queue_size(value: str) -> int:
    """Validate queue size arguments."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Queue size must be an integer.") from exc
    if parsed < 1 or parsed > 10:
        raise argparse.ArgumentTypeError("Queue size must be between 1 and 10.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_mutually_exclusive_group()
    actions.add_argument("--next", action="store_true", help="Select the next recommended target and generate its prompt.")
    actions.add_argument("--queue", type=queue_size, help="Queue 1-10 tasks and generate prompt files in prompts/batch/.")
    actions.add_argument("--complete", metavar="PAGE_OR_CLUSTER_ID", help="Mark the current stage complete for the given target.")
    actions.add_argument("--complete-batch", action="store_true", help="Mark all queued batch items as success and rebuild the dashboard.")
    actions.add_argument("--report", action="store_true", help="Rebuild and print the dashboard summary.")
    actions.add_argument("--validate", action="store_true", help="Run validation plus link and placeholder checks.")
    actions.add_argument("--history", action="store_true", help="List recently updated workflow items.")
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument("--cluster", help="Generate a prompt for a specific cluster id.")
    selectors.add_argument("--page", help="Generate a prompt for a specific page id.")
    parser.add_argument("--flagship-only", action="store_true", help="Limit automatic selection to flagship items.")
    parser.add_argument("--beta-visible-only", action="store_true", help="Limit automatic selection to public-beta-visible items.")
    parser.add_argument("--result", choices=VALID_RESULTS, help="Completion result for --complete.")
    parser.add_argument("--notes", default="", help="Optional note for --complete.")
    parser.add_argument("--stdout", action="store_true", help="Print the generated prompt instead of writing it to files.")
    parser.add_argument("--open", action="store_true", help="Print a shell command you can use to open the prompt file.")
    parser.add_argument("--open-batch", action="store_true", help="Print a shell command you can use to open the batch prompt directory.")
    parser.add_argument("--dry-run", action="store_true", help="Simulate queue or batch completion actions without writing changes.")
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


def manual_target_from_args(args: argparse.Namespace, state: dict[str, Any]) -> tuple[str, dict[str, Any], str] | None:
    """Return a manually selected target when present."""

    if args.cluster:
        return resolve_manual_target(state, target_id=args.cluster, expected_mode="cluster")
    if args.page:
        return resolve_manual_target(state, target_id=args.page, expected_mode="page")
    return None


def write_prompt_files(target_id: str, stage_name: str, prompt: str) -> tuple[Path, Path]:
    """Write current and history prompt files."""

    PROMPT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PROMPT_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    history_path = PROMPT_HISTORY_DIR / f"{target_id}-{stage_name}.md"
    atomic_write_text(PROMPT_OUTPUT, prompt + "\n")
    atomic_write_text(history_path, prompt + "\n")
    return PROMPT_OUTPUT, history_path


def build_queue_entry(
    *,
    position: int,
    target_id: str,
    item: dict[str, Any],
    reason: str,
    prompt: str,
    next_stage: str,
) -> dict[str, Any]:
    """Build a serializable queue entry."""

    return {
        "position": position,
        "target_id": target_id,
        "type": item["type"],
        "status": item["status"],
        "confidence": item["confidence"],
        "current_stage": item["stage"],
        "next_stage": next_stage,
        "reason": reason,
        "files": list(item["files"]),
        "prompt": prompt,
    }


def build_batch_run_all(tasks: list[dict[str, Any]]) -> str:
    """Render the batch helper markdown file."""

    lines = [
        "# FS3 Batch Prompt Run",
        "",
        "Process these prompts in order. After each task finishes, run the listed completion command or wait and use `--complete-batch` at the end.",
        "",
        "## Queue",
    ]
    for task in tasks:
        lines.append(
            f"{task['position']}. `{task['target_id']}` -> `{task['current_stage']}` "
            f"(next: `{task['next_stage']}`)"
        )
    lines.extend(["", "## Completion Commands"])
    for task in tasks:
        lines.append(
            "```bash\n"
            f"python scripts/run_next_task.py --complete {task['target_id']} --result success "
            f'--notes "{task["current_stage"].title()} pass completed and pushed"\n'
            "```"
        )
    lines.extend(
        [
            "",
            "## Batch Completion",
            "```bash",
            "python scripts/run_next_task.py --complete-batch",
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def write_batch_files(tasks: list[dict[str, Any]], *, dry_run: bool) -> list[Path]:
    """Write batch prompt files, run-all helper, and manifest."""

    written_paths: list[Path] = []
    if dry_run:
        for task in tasks:
            filename = BATCH_DIR / f"{task['position']:02d}-{task['target_id']}-{task['current_stage']}.md"
            written_paths.append(filename)
        written_paths.extend([BATCH_RUN_ALL, BATCH_MANIFEST])
        return written_paths

    BATCH_DIR.mkdir(parents=True, exist_ok=True)
    for task in tasks:
        filename = BATCH_DIR / f"{task['position']:02d}-{task['target_id']}-{task['current_stage']}.md"
        atomic_write_text(filename, task["prompt"] + "\n")
        written_paths.append(filename)
    atomic_write_text(BATCH_RUN_ALL, build_batch_run_all(tasks) + "\n")
    written_paths.append(BATCH_RUN_ALL)
    manifest = {
        "generated_on": __import__("datetime").date.today().isoformat(),
        "queue_size": len(tasks),
        "tasks": [
            {
                key: value
                for key, value in task.items()
                if key != "prompt"
            }
            for task in tasks
        ],
    }
    save_yaml(BATCH_MANIFEST, manifest)
    written_paths.append(BATCH_MANIFEST)
    return written_paths


def print_batch_summary(tasks: list[dict[str, Any]], *, dry_run: bool, open_batch: bool) -> None:
    """Print operator-friendly batch output."""

    print(f"Queued {len(tasks)} tasks:\n")
    for task in tasks:
        print(f"{task['position']}. {task['target_id']} -> {task['current_stage']}")
    if dry_run:
        print("\nDry run only. No prompt files were written and refinement-state.yaml was not changed.")
    else:
        print("\nPrompts written to:")
        print(BATCH_DIR.relative_to(ROOT))
        if open_batch:
            print("\nOpen command:")
            print(f"code {BATCH_DIR.relative_to(ROOT)}")
    print("\nSuggested workflow:")
    print("- Open prompts in order")
    print("- Run each in Codex")
    print("- Mark completion after each or at end")


def load_batch_manifest() -> dict[str, Any]:
    """Load the current batch manifest."""

    if not BATCH_MANIFEST.exists():
        raise RefinementError(
            f"Batch manifest not found: {BATCH_MANIFEST}. Generate a batch first with --queue."
        )
    return load_state(BATCH_MANIFEST)


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
    manual_target = manual_target_from_args(args, state)
    if manual_target is not None:
        return manual_target
    raise RefinementError("No target selection mode was provided.")


def build_batch_queue(args: argparse.Namespace) -> list[dict[str, Any]]:
    """Build a deterministic in-memory queue without mutating refinement-state.yaml."""

    state, stage_config, priority_config = load_all_configs()
    manual_target = manual_target_from_args(args, state)
    requested = args.queue or 1
    if manual_target is not None:
        if requested > 1:
            raise RefinementError("--queue with --page or --cluster can only queue one explicit target.")
        target_id, item, reason = manual_target
        prompt = render_stage_prompt(target_id, item, item["stage"])
        return [
            build_queue_entry(
                position=1,
                target_id=target_id,
                item=item,
                reason=reason,
                prompt=prompt,
                next_stage=next_stage_for_item(item, stage_config),
            )
        ]

    simulated_state = deepcopy(state)
    tasks: list[dict[str, Any]] = []
    for position in range(1, requested + 1):
        candidate = select_next_item(
            simulated_state,
            priority_config,
            flagship_only=args.flagship_only,
            beta_visible_only=args.beta_visible_only,
        )
        if candidate is None:
            break
        selected_item = deepcopy(candidate.item)
        prompt = render_stage_prompt(candidate.item_id, selected_item, selected_item["stage"])
        tasks.append(
            build_queue_entry(
                position=position,
                target_id=candidate.item_id,
                item=selected_item,
                reason=reason_text(candidate.reasons),
                prompt=prompt,
                next_stage=next_stage_for_item(selected_item, stage_config),
            )
        )
        complete_current_stage(simulated_state, candidate.item_id, "success", "", stage_config)
    if not tasks:
        raise RefinementError("No eligible tasks found for batch generation.")
    return tasks


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


def handle_batch_generation(args: argparse.Namespace) -> int:
    """Queue multiple tasks and generate batch prompt files."""

    tasks = build_batch_queue(args)
    write_batch_files(tasks, dry_run=args.dry_run)
    print_batch_summary(tasks, dry_run=args.dry_run, open_batch=args.open_batch)
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


def handle_complete_batch(args: argparse.Namespace) -> int:
    """Mark all queued manifest items as success and rebuild the dashboard."""

    manifest = load_batch_manifest()
    tasks = manifest.get("tasks", [])
    if not tasks:
        raise RefinementError("Batch manifest does not contain any queued tasks.")
    state, stage_config, _ = load_all_configs()
    summary_lines: list[str] = []
    for task in tasks:
        target_id = task["target_id"]
        if target_id not in state["pages"]:
            raise RefinementError(f"Batch item is missing from state: {target_id}")
        item = state["pages"][target_id]
        previous_stage = item["stage"]
        complete_current_stage(
            state,
            target_id,
            "success",
            f"{task['current_stage'].title()} pass completed via --complete-batch",
            stage_config,
        )
        summary_lines.append(f"- {target_id}: {previous_stage} -> {state['pages'][target_id]['stage']}")
    if args.dry_run:
        print("Would complete batch items:\n")
        print("\n".join(summary_lines))
        print(f"\nWould rebuild dashboard: {MARKDOWN_OUTPUT.relative_to(ROOT)}")
        return 0
    save_state(state)
    payload = build_dashboard_payload()
    write_dashboard_outputs(payload)
    print("Completed batch items:\n")
    print("\n".join(summary_lines))
    print(f"\nDashboard rebuilt: {MARKDOWN_OUTPUT.relative_to(ROOT)}")
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
        if args.queue:
            return handle_batch_generation(args)
        if args.complete:
            return handle_completion(args)
        if args.complete_batch:
            return handle_complete_batch(args)
        if args.report:
            return handle_report()
        if args.validate:
            return handle_validation()
        if args.history:
            return handle_history(args.limit)
        if args.next or args.page or args.cluster:
            return handle_prompt_generation(args)
        raise RefinementError("Choose one workflow mode such as --next, --queue, --page, --cluster, --complete, --complete-batch, --report, --validate, or --history.")
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
