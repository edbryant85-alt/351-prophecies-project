#!/usr/bin/env python3
"""Generate human-readable and JSON refinement dashboards."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from refinement_lib import (
    ROOT,
    atomic_write_text,
    beta_progress,
    blocked_items,
    counts_by_field,
    flagship_progress,
    json_dump,
    list_candidates,
    load_all_configs,
    markdown_table,
    recent_items,
    today_iso,
)


MARKDOWN_OUTPUT = ROOT / "docs" / "refinement-dashboard.md"
JSON_OUTPUT = ROOT / "docs" / "refinement-dashboard.json"


def build_dashboard_payload() -> dict:
    """Assemble dashboard data."""

    state, _, priority_config = load_all_configs()
    reporting = priority_config.get("reporting", {})
    recent_days = int(reporting.get("recent_days", 14))
    recommended_limit = int(reporting.get("recommended_items", 10))
    recommended = list_candidates(state, priority_config, limit=recommended_limit)
    recent = recent_items(state, days=recent_days)
    blocked = blocked_items(state)
    flagship_done, flagship_total = flagship_progress(state)
    beta_done, beta_total = beta_progress(state)
    return {
        "generated_on": today_iso(),
        "counts_by_stage": counts_by_field(state, "stage"),
        "counts_by_status": counts_by_field(state, "status"),
        "counts_by_confidence": counts_by_field(state, "confidence"),
        "flagship_progress": {
            "complete": flagship_done,
            "total": flagship_total,
        },
        "beta_progress": {
            "complete": beta_done,
            "total": beta_total,
        },
        "recently_updated_items": [
            {
                "id": item_id,
                "stage": item["stage"],
                "status": item["status"],
                "last_run": item["last_run"],
                "notes": item.get("notes", ""),
            }
            for item_id, item in recent[:10]
        ],
        "blocked_items": [
            {
                "id": item_id,
                "stage": item["stage"],
                "status": item["status"],
                "notes": item.get("notes", ""),
            }
            for item_id, item in blocked[:10]
        ],
        "next_recommended_items": [
            {
                "id": candidate.item_id,
                "stage": candidate.item["stage"],
                "status": candidate.item["status"],
                "confidence": candidate.item["confidence"],
                "score": candidate.score,
                "reasons": candidate.reasons,
            }
            for candidate in recommended
        ],
        "total_items": len(state["pages"]),
    }


def render_dashboard_markdown(payload: dict) -> str:
    """Render the dashboard markdown document."""

    stage_rows = [["Stage", "Count"]] + [
        [stage_name, str(count)] for stage_name, count in payload["counts_by_stage"].items()
    ]
    status_rows = [["Status", "Count"]] + [
        [status_name, str(count)] for status_name, count in payload["counts_by_status"].items()
    ]
    confidence_rows = [["Confidence", "Count"]] + [
        [confidence_name, str(count)] for confidence_name, count in payload["counts_by_confidence"].items()
    ]
    recent_lines = [
        f"- `{item['id']}`: stage `{item['stage']}`, status `{item['status']}`, last run `{item['last_run']}`"
        for item in payload["recently_updated_items"]
    ] or ["- None"]
    blocked_lines = [
        f"- `{item['id']}`: stage `{item['stage']}`, status `{item['status']}`"
        for item in payload["blocked_items"]
    ] or ["- None"]
    recommended_lines = [
        f"- `{item['id']}`: stage `{item['stage']}`, status `{item['status']}`, confidence `{item['confidence']}`, score `{item['score']}`"
        for item in payload["next_recommended_items"]
    ] or ["- None"]
    return "\n".join(
        [
            "# Refinement Dashboard",
            "",
            f"- Generated on: {payload['generated_on']}",
            f"- Total tracked items: {payload['total_items']}",
            (
                f"- Flagship progress: {payload['flagship_progress']['complete']}/"
                f"{payload['flagship_progress']['total']} complete"
            ),
            (
                f"- Beta-visible progress: {payload['beta_progress']['complete']}/"
                f"{payload['beta_progress']['total']} complete"
            ),
            "",
            "## Counts by Stage",
            markdown_table(stage_rows),
            "",
            "## Counts by Status",
            markdown_table(status_rows),
            "",
            "## Counts by Confidence",
            markdown_table(confidence_rows),
            "",
            "## Recently Updated Items",
            *recent_lines,
            "",
            "## Blocked Items",
            *blocked_lines,
            "",
            "## Next Recommended Work Items",
            *recommended_lines,
            "",
        ]
    )


def write_dashboard_outputs(payload: dict) -> tuple[Path, Path]:
    """Write dashboard markdown and JSON outputs."""

    markdown = render_dashboard_markdown(payload)
    MARKDOWN_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(MARKDOWN_OUTPUT, markdown + "\n")
    json_dump(JSON_OUTPUT, payload)
    return MARKDOWN_OUTPUT, JSON_OUTPUT


def main() -> int:
    """Run the CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    try:
        payload = build_dashboard_payload()
        markdown_path, json_path = write_dashboard_outputs(payload)
        print(markdown_path)
        print(json_path)
        return 0
    except Exception as exc:  # pragma: no cover - CLI safety
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
