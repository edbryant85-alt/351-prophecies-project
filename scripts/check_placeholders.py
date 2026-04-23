#!/usr/bin/env python3
"""Scan for residual placeholder language in project documents."""

from __future__ import annotations

import argparse
from pathlib import Path

from refinement_lib import PLACEHOLDER_PHRASES, ROOT, read_text


SCAN_DIRS = [ROOT / "content", ROOT / "docs", ROOT / "notes"]


def main() -> int:
    """Run the CLI."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=100, help="Maximum matches to print.")
    args = parser.parse_args()
    hits: list[str] = []
    for scan_dir in SCAN_DIRS:
        for path in sorted(scan_dir.rglob("*.md")):
            text = read_text(path)
            for phrase in PLACEHOLDER_PHRASES:
                if phrase in text:
                    hits.append(f"{path.relative_to(ROOT)}: {phrase}")
                    break
    if not hits:
        print("No placeholder phrases detected.")
        return 0
    for line in hits[: args.limit]:
        print(line)
    if len(hits) > args.limit:
        print(f"... {len(hits) - args.limit} more")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
