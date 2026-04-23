#!/usr/bin/env python3
"""Simple one-command session wrapper for the FS3 workflow."""

from __future__ import annotations

import argparse
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from refinement_lib import ROOT, RefinementError, atomic_write_text
from run_next_task import build_batch_queue


SESSION_PROMPT = ROOT / "prompts" / "session-task.md"


def session_limit(value: str) -> int:
    """Validate the requested session size."""

    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("Session limit must be an integer.") from exc
    if parsed < 1 or parsed > 10:
        raise argparse.ArgumentTypeError("Session limit must be between 1 and 10.")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=session_limit, default=3, help="Number of tasks to include in the session prompt.")
    parser.add_argument("--flagship-only", action="store_true", help="Only queue flagship items.")
    parser.add_argument("--beta-visible-only", action="store_true", help="Only queue beta-visible items.")
    return parser


def make_queue_args(*, limit: int, flagship_only: bool, beta_visible_only: bool) -> SimpleNamespace:
    """Build a namespace compatible with run_next_task.build_batch_queue."""

    return SimpleNamespace(
        queue=limit,
        cluster=None,
        page=None,
        next=False,
        flagship_only=flagship_only,
        beta_visible_only=beta_visible_only,
        dry_run=True,
        open_batch=False,
        complete=None,
        complete_batch=False,
        report=False,
        validate=False,
        history=False,
        result=None,
        notes="",
        stdout=False,
        open=False,
        limit_history=10,
    )


def select_session_tasks(limit: int, *, flagship_only: bool, beta_visible_only: bool) -> list[dict]:
    """Select up to limit tasks without mutating workflow state."""

    if beta_visible_only or flagship_only:
        return build_batch_queue(
            make_queue_args(
                limit=limit,
                flagship_only=flagship_only,
                beta_visible_only=beta_visible_only,
            )
        )

    try:
        beta_tasks = build_batch_queue(
            make_queue_args(limit=limit, flagship_only=False, beta_visible_only=True)
        )
    except RefinementError:
        beta_tasks = []
    if len(beta_tasks) >= limit:
        return beta_tasks[:limit]

    chosen_ids = {task["target_id"] for task in beta_tasks}
    fallback_args = make_queue_args(limit=10, flagship_only=False, beta_visible_only=False)
    fallback_tasks = build_batch_queue(fallback_args)
    for task in fallback_tasks:
        if task["target_id"] in chosen_ids:
            continue
        beta_tasks.append(task)
        chosen_ids.add(task["target_id"])
        if len(beta_tasks) >= limit:
            break

    if not beta_tasks:
        raise RefinementError("No eligible tasks found for this session.")
    return beta_tasks


def render_session_prompt(tasks: list[dict]) -> str:
    """Render a combined session prompt for Codex."""

    lines = [
        "# FS3 Session Task",
        "",
        "Complete the following FS3 tasks in order.",
        "",
        "Session rules:",
        "- Work through the listed tasks one at a time in the order given.",
        "- After each successful task, run the git steps for that task: `git add -A`, `git commit -m \"...\"`, and `git push`.",
        "- If any task is blocked, stop immediately and report the blocker instead of guessing.",
        "- At the very end, summarize all completed work and note any unfinished or blocked items.",
        "",
        "Queued tasks:",
    ]
    for task in tasks:
        lines.append(f"{task['position']}. `{task['target_id']}` -> `{task['current_stage']}`")
    for task in tasks:
        lines.extend(
            [
                "",
                f"---",
                "",
                f"## Task {task['position']}: {task['target_id']}",
                "",
                task["prompt"].rstrip(),
            ]
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        tasks = select_session_tasks(
            args.limit,
            flagship_only=args.flagship_only,
            beta_visible_only=args.beta_visible_only,
        )
        SESSION_PROMPT.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(SESSION_PROMPT, render_session_prompt(tasks))
        passages = ", ".join(task["target_id"] for task in tasks)
        print(f"Queued {len(tasks)} tasks.")
        print(f"Passages: {passages}")
        print(f"Session prompt: {SESSION_PROMPT.relative_to(ROOT)}")
        return 0
    except RefinementError as exc:
        print(f"ERROR: {exc}")
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
