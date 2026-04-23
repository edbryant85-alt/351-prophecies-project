#!/usr/bin/env python3
"""Sync page status metadata from refinement-state.yaml into markdown files."""

from __future__ import annotations

import argparse
import sys

from refinement_lib import (
    ROOT,
    RefinementError,
    atomic_write_text,
    cluster_overview_file,
    extract_status_block,
    load_all_configs,
    read_text,
    sync_page_metadata,
)


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--page", help="Optional single page or cluster id to sync.")
    parser.add_argument("--dry-run", action="store_true", help="Show planned changes without writing.")
    return parser


def main() -> int:
    """Run the CLI."""

    parser = build_parser()
    args = parser.parse_args()
    try:
        state, _, _ = load_all_configs()
        page_ids = [args.page] if args.page else sorted(state["pages"])
        changed = 0
        for page_id in page_ids:
            if page_id not in state["pages"]:
                raise RefinementError(f"Unknown page or cluster id: {page_id}")
            item = state["pages"][page_id]
            file_names = item["files"]
            if item["type"] == "cluster":
                overview_file = cluster_overview_file(page_id, item)
                file_names = [overview_file] if overview_file else []
            for file_name in file_names:
                path = ROOT / file_name
                original = read_text(path)
                existing = extract_status_block(original)
                last_updated = item["last_run"] or existing.get("last_updated", "2026-04-22")
                updated = sync_page_metadata(
                    original,
                    status=item["status"],
                    confidence=item["confidence"],
                    last_updated=last_updated,
                )
                if updated == original:
                    continue
                changed += 1
                if args.dry_run:
                    print(f"Would update {file_name}")
                else:
                    atomic_write_text(path, updated)
                    print(f"Updated {file_name}")
        if changed == 0:
            print("No metadata changes were needed.")
        return 0
    except RefinementError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
