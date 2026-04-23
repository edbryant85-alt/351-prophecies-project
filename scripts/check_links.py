#!/usr/bin/env python3
"""Check local markdown and preview links for missing targets."""

from __future__ import annotations

import sys
from pathlib import Path

from refinement_lib import (
    ROOT, PREVIEW_DIR, find_internal_markdown_links, looks_like_local_link, read_text, resolve_local_link
)


SCAN_DIRS = [ROOT / "content", ROOT / "docs", ROOT / "notes"]


def main() -> int:
    """Run the CLI."""

    issues: list[str] = []
    for scan_dir in SCAN_DIRS:
        for path in sorted(scan_dir.rglob("*.md")):
            text = read_text(path)
            for target in find_internal_markdown_links(text):
                if not looks_like_local_link(target):
                    continue
                resolved = resolve_local_link(path, target)
                if not resolved.exists():
                    issues.append(f"{path.relative_to(ROOT)} -> missing target: {target}")
    if issues:
        print("\n".join(issues), file=sys.stderr)
        return 1
    print("No broken local markdown or preview links detected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
