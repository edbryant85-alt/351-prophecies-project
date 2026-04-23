"""Shared helpers for the FS3 refinement workflow."""

from __future__ import annotations

import json
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from string import Template
from typing import Any

try:
    import yaml
except ImportError as exc:  # pragma: no cover - handled for runtime clarity
    raise RuntimeError(
        "PyYAML is required for the refinement workflow. Install or enable PyYAML "
        "before running these scripts."
    ) from exc


ROOT = Path(__file__).resolve().parent.parent
STATE_PATH = ROOT / "data" / "refinement-state.yaml"
STAGES_PATH = ROOT / "config" / "refinement-stages.yaml"
PRIORITIES_PATH = ROOT / "config" / "refinement-priorities.yaml"
STYLE_GUIDE_PATH = ROOT / "docs" / "style-guide.md"
CONTENT_DIR = ROOT / "content" / "prophecies"
PREVIEW_DIR = ROOT / "preview"
SHAREABLE_PREVIEW_DIR = ROOT / "shareable-preview"

VALID_TYPES = {"cluster", "overview", "claim"}
VALID_STATUSES = {"Flagship Analysis", "Reviewed Analysis", "Draft Analysis"}
VALID_CONFIDENCE = {"High", "Moderate", "Low"}
PLACEHOLDER_PHRASES = [
    "AI-generated placeholder",
    "subject to review",
    "prototype",
    "Display scope: Full verse",
    "Text Details (Expandable)",
]
TITLE_METADATA_LINES = ("**Page Status:**", "**Confidence Level:**", "**Last Updated:**")
STYLE_CONSTRAINTS = [
    "Preserve the existing page type and required section order from docs/style-guide.md.",
    "Keep overview pages broad and orienting; keep claim pages narrow and verse-specific.",
    "Follow the repo scripture limits: minimal quotation, inline attribution, and Bible Gateway links.",
    "Write in a fair, analytical, non-polemical tone.",
    "Use the six project criteria selectively, focusing on the ones that materially matter.",
    "Keep conclusions brief, balanced, and explicit about predictive strength and limitations.",
]
TYPE_SORT_RANK = {
    "cluster": 0,
    "overview": 1,
    "claim": 2,
}


class RefinementError(Exception):
    """Raised for invalid workflow state or configuration."""


@dataclass(frozen=True)
class Candidate:
    """A sortable work item candidate."""

    item_id: str
    item: dict[str, Any]
    score: int
    reasons: list[str]


def today_iso() -> str:
    """Return today's date in ISO format."""

    return date.today().isoformat()


def parse_iso_date(value: str | None) -> date | None:
    """Parse an ISO date string, returning None for empty values."""

    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise RefinementError(f"Invalid ISO date: {value}") from exc


def load_yaml(path: Path) -> Any:
    """Load YAML using the safe loader."""

    if not path.exists():
        raise RefinementError(f"YAML file not found: {path}")
    try:
        with path.open("r", encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise RefinementError(f"Failed to parse YAML: {path}") from exc
    return data


def save_yaml(path: Path, payload: Any) -> None:
    """Write YAML atomically using safe dumping."""

    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    )
    atomic_write_text(path, serialized)


def atomic_write_text(path: Path, content: str) -> None:
    """Write text atomically."""

    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
    ) as handle:
        handle.write(content)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def load_stage_config(path: Path = STAGES_PATH) -> dict[str, Any]:
    """Load and validate the stage configuration."""

    config = load_yaml(path)
    if not isinstance(config, dict):
        raise RefinementError("Stage config must be a mapping.")
    ordered_stages = config.get("ordered_stages")
    stages = config.get("stages")
    allowed_results = config.get("allowed_results")
    if not isinstance(ordered_stages, list) or not ordered_stages:
        raise RefinementError("config/refinement-stages.yaml is missing ordered_stages.")
    if not isinstance(stages, dict):
        raise RefinementError("config/refinement-stages.yaml is missing stages.")
    if ordered_stages[-1] != "complete":
        raise RefinementError("The final ordered stage must be complete.")
    if not isinstance(allowed_results, list) or not allowed_results:
        raise RefinementError("config/refinement-stages.yaml is missing allowed_results.")
    missing = [stage_name for stage_name in ordered_stages if stage_name not in stages]
    if missing:
        raise RefinementError(f"Missing stage definitions: {', '.join(missing)}")
    for stage_name, stage_data in stages.items():
        if not isinstance(stage_data, dict):
            raise RefinementError(f"Stage definition must be a mapping: {stage_name}")
        if "description" not in stage_data or "surface" not in stage_data:
            raise RefinementError(f"Stage definition is incomplete: {stage_name}")
        if not isinstance(stage_data.get("applicable_types"), list):
            raise RefinementError(f"Stage {stage_name} must define applicable_types.")
    return config


def load_priority_config(path: Path = PRIORITIES_PATH) -> dict[str, Any]:
    """Load and lightly validate the priority configuration."""

    config = load_yaml(path)
    if not isinstance(config, dict):
        raise RefinementError("Priority config must be a mapping.")
    if "weights" not in config or "selection" not in config:
        raise RefinementError("config/refinement-priorities.yaml is incomplete.")
    return config


def load_state(path: Path = STATE_PATH) -> dict[str, Any]:
    """Load workflow state."""

    payload = load_yaml(path)
    if not isinstance(payload, dict):
        raise RefinementError("refinement-state.yaml must be a mapping.")
    return payload


def save_state(state: dict[str, Any], path: Path = STATE_PATH) -> None:
    """Persist workflow state."""

    save_yaml(path, state)


def stage_order(stage_config: dict[str, Any]) -> list[str]:
    """Return the configured stage order."""

    return list(stage_config["ordered_stages"])


def ordered_stage_map(stage_config: dict[str, Any]) -> dict[str, int]:
    """Build a stage-to-index lookup."""

    return {stage_name: index for index, stage_name in enumerate(stage_order(stage_config))}


def stage_details(stage_config: dict[str, Any], stage_name: str) -> dict[str, Any]:
    """Return a stage definition."""

    return dict(stage_config["stages"][stage_name])


def stage_applies(item_type: str, stage_name: str, stage_config: dict[str, Any]) -> bool:
    """Return whether a stage applies to a given item type."""

    details = stage_details(stage_config, stage_name)
    return item_type in details["applicable_types"]


def next_stage_for_item(item: dict[str, Any], stage_config: dict[str, Any]) -> str:
    """Return the next applicable stage for an item."""

    order = stage_order(stage_config)
    current_index = ordered_stage_map(stage_config)[item["stage"]]
    for stage_name in order[current_index + 1 :]:
        if stage_applies(item["type"], stage_name, stage_config):
            return stage_name
    return "complete"


def can_transition(
    item: dict[str, Any],
    target_stage: str,
    stage_config: dict[str, Any],
) -> tuple[bool, str]:
    """Return whether the target stage is a legal transition for the item."""

    order_lookup = ordered_stage_map(stage_config)
    if target_stage not in order_lookup:
        return False, f"Unknown stage: {target_stage}"
    if not stage_applies(item["type"], target_stage, stage_config):
        return False, f"Stage {target_stage} does not apply to {item['type']} items."
    current_index = order_lookup[item["stage"]]
    target_index = order_lookup[target_stage]
    if target_index < current_index:
        return False, "Backward stage transitions are not allowed."
    if target_index == current_index:
        return True, "No-op transition."
    order = stage_order(stage_config)
    for skipped_name in order[current_index + 1 : target_index]:
        if not stage_applies(item["type"], skipped_name, stage_config):
            continue
        skipped_details = stage_details(stage_config, skipped_name)
        if not skipped_details.get("skippable", False):
            return False, f"Cannot skip non-skippable stage: {skipped_name}"
    return True, "Transition allowed."


def validate_state(
    state: dict[str, Any],
    stage_config: dict[str, Any],
    *,
    check_files: bool = True,
) -> None:
    """Validate the workflow state payload."""

    if "pages" not in state or not isinstance(state["pages"], dict):
        raise RefinementError("Workflow state must contain a pages mapping.")
    allowed_results = set(stage_config["allowed_results"])
    pages = state["pages"]
    for item_id, item in pages.items():
        if not isinstance(item, dict):
            raise RefinementError(f"State entry must be a mapping: {item_id}")
        item_type = item.get("type")
        if item_type not in VALID_TYPES:
            raise RefinementError(f"Invalid item type for {item_id}: {item_type}")
        files = item.get("files")
        if not isinstance(files, list) or not files:
            raise RefinementError(f"{item_id} must define at least one file.")
        if check_files:
            for file_name in files:
                if not (ROOT / file_name).exists():
                    raise RefinementError(f"{item_id} references a missing file: {file_name}")
        stage_name = item.get("stage")
        if stage_name not in stage_config["ordered_stages"]:
            raise RefinementError(f"Unknown stage for {item_id}: {stage_name}")
        if not stage_applies(item_type, stage_name, stage_config):
            raise RefinementError(f"Stage {stage_name} does not apply to {item_id}.")
        status = item.get("status")
        if status not in VALID_STATUSES:
            raise RefinementError(f"Invalid status for {item_id}: {status}")
        confidence = item.get("confidence")
        if confidence not in VALID_CONFIDENCE:
            raise RefinementError(f"Invalid confidence for {item_id}: {confidence}")
        priority = item.get("priority")
        if not isinstance(priority, int):
            raise RefinementError(f"Priority must be an integer for {item_id}.")
        dependencies = item.get("dependencies")
        if not isinstance(dependencies, list):
            raise RefinementError(f"Dependencies must be a list for {item_id}.")
        missing_dependencies = [dependency for dependency in dependencies if dependency not in pages]
        if missing_dependencies:
            raise RefinementError(
                f"{item_id} depends on unknown items: {', '.join(missing_dependencies)}"
            )
        if not isinstance(item.get("public_beta_visible"), bool):
            raise RefinementError(f"public_beta_visible must be true/false for {item_id}.")
        parse_iso_date(item.get("last_run"))
        last_result = item.get("last_result")
        if last_result not in allowed_results:
            raise RefinementError(f"Invalid last_result for {item_id}: {last_result}")
        notes = item.get("notes", "")
        if not isinstance(notes, str):
            raise RefinementError(f"Notes must be a string for {item_id}.")


def item_summary(item_id: str, item: dict[str, Any]) -> str:
    """Return a short human-readable summary for an item."""

    files = ", ".join(item["files"])
    return (
        f"{item_id} [{item['type']}] stage={item['stage']} status={item['status']} "
        f"confidence={item['confidence']} priority={item['priority']} files={files}"
    )


def dependency_is_blocking(
    item: dict[str, Any],
    state: dict[str, Any],
    priority_config: dict[str, Any],
) -> bool:
    """Return whether any dependency should block automatic selection."""

    if not item["dependencies"]:
        return False
    skip_blocked_dependencies = priority_config["selection"].get("skip_blocked_dependencies", True)
    for dependency_id in item["dependencies"]:
        dependency = state["pages"][dependency_id]
        if dependency["stage"] != "complete":
            return True
        if skip_blocked_dependencies and dependency.get("last_result") == "blocked":
            return True
    return False


def candidate_score(
    item_id: str,
    item: dict[str, Any],
    state: dict[str, Any],
    priority_config: dict[str, Any],
) -> Candidate | None:
    """Compute a candidate score for automatic selection."""

    weights = priority_config["weights"]
    reasons: list[str] = [f"base priority {item['priority']}"]
    if item["stage"] == "complete" and not priority_config["selection"].get("include_complete", False):
        return None
    if item["last_result"] == "blocked" and priority_config["selection"].get("skip_blocked", True):
        return None
    if dependency_is_blocking(item, state, priority_config):
        return None
    score = item["priority"]
    score += weights["status"].get(item["status"], 0)
    reasons.append(f"status {item['status']}")
    score += weights["type"].get(item["type"], 0)
    reasons.append(f"type {item['type']}")
    score += weights["stage"].get(item["stage"], 0)
    reasons.append(f"stage {item['stage']}")
    if item["public_beta_visible"]:
        score += weights.get("public_beta_visible", 0)
        reasons.append("public beta visible")
    last_run = parse_iso_date(item.get("last_run"))
    if last_run is None:
        score += weights.get("missing_last_run", 0)
        reasons.append("never run")
    else:
        stale_config = priority_config.get("stale_boost", {})
        threshold_days = int(stale_config.get("threshold_days", 0))
        age = (date.today() - last_run).days
        if age > threshold_days:
            points = min(
                (age - threshold_days) * int(stale_config.get("points_per_day", 0)),
                int(stale_config.get("max_points", 0)),
            )
            if points:
                score += points
                reasons.append(f"stale for {age} days")
    return Candidate(item_id=item_id, item=item, score=score, reasons=reasons)


def list_candidates(
    state: dict[str, Any],
    priority_config: dict[str, Any],
    *,
    stage_filter: str | None = None,
    flagship_only: bool = False,
    beta_visible_only: bool = False,
    limit: int | None = None,
) -> list[Candidate]:
    """Return sorted work item candidates."""

    default_limit = int(priority_config["selection"].get("default_limit", 20))
    limit = limit or default_limit
    candidates: list[Candidate] = []
    for item_id, item in state["pages"].items():
        if stage_filter and item["stage"] != stage_filter:
            continue
        if flagship_only and item["status"] != "Flagship Analysis":
            continue
        if beta_visible_only and not item["public_beta_visible"]:
            continue
        candidate = candidate_score(item_id, item, state, priority_config)
        if candidate is None:
            continue
        candidates.append(candidate)
    candidates.sort(
        key=lambda candidate: (
            -candidate.score,
            candidate.item["priority"] * -1,
            parse_iso_date(candidate.item.get("last_run")) or date.min,
            TYPE_SORT_RANK.get(candidate.item["type"], 99),
            candidate.item_id,
        )
    )
    return candidates[:limit]


def select_next_item(
    state: dict[str, Any],
    priority_config: dict[str, Any],
    *,
    stage_filter: str | None = None,
    flagship_only: bool = False,
    beta_visible_only: bool = False,
) -> Candidate | None:
    """Return the top candidate, if any."""

    candidates = list_candidates(
        state,
        priority_config,
        stage_filter=stage_filter,
        flagship_only=flagship_only,
        beta_visible_only=beta_visible_only,
        limit=1,
    )
    return candidates[0] if candidates else None


def append_note(existing: str, note: str) -> str:
    """Append a timestamped note to the note field."""

    if not note.strip():
        return existing
    stamped = f"{today_iso()}: {note.strip()}"
    return stamped if not existing.strip() else f"{existing.rstrip()}\n{stamped}"


def update_item_stage(
    state: dict[str, Any],
    item_id: str,
    target_stage: str,
    stage_config: dict[str, Any],
) -> None:
    """Advance an item to a legal target stage."""

    item = state["pages"][item_id]
    allowed, reason = can_transition(item, target_stage, stage_config)
    if not allowed:
        raise RefinementError(reason)
    item["stage"] = target_stage


def complete_current_stage(
    state: dict[str, Any],
    item_id: str,
    result: str,
    note: str,
    stage_config: dict[str, Any],
) -> dict[str, Any]:
    """Update state after a stage run."""

    item = state["pages"][item_id]
    item["last_run"] = today_iso()
    item["last_result"] = result
    if note:
        item["notes"] = append_note(item.get("notes", ""), note)
    if result == "success":
        item["stage"] = next_stage_for_item(item, stage_config)
    return item


def counts_by_field(state: dict[str, Any], field_name: str) -> dict[str, int]:
    """Return counts for a specific field."""

    counts: dict[str, int] = {}
    for item in state["pages"].values():
        key = str(item[field_name])
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def recent_items(
    state: dict[str, Any],
    *,
    days: int,
) -> list[tuple[str, dict[str, Any]]]:
    """Return items updated within the last N days."""

    cutoff = date.today().toordinal() - days
    items: list[tuple[str, dict[str, Any]]] = []
    for item_id, item in state["pages"].items():
        last_run = parse_iso_date(item.get("last_run"))
        if last_run and last_run.toordinal() >= cutoff:
            items.append((item_id, item))
    items.sort(
        key=lambda pair: (
            parse_iso_date(pair[1].get("last_run")) or date.min,
            pair[0],
        ),
        reverse=True,
    )
    return items


def blocked_items(state: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return blocked items sorted by priority."""

    items = [(item_id, item) for item_id, item in state["pages"].items() if item["last_result"] == "blocked"]
    items.sort(key=lambda pair: (-pair[1]["priority"], pair[0]))
    return items


def flagship_progress(state: dict[str, Any]) -> tuple[int, int]:
    """Return completed vs total flagship items."""

    flagship_items = [
        item for item in state["pages"].values() if item["status"] == "Flagship Analysis"
    ]
    completed = sum(1 for item in flagship_items if item["stage"] == "complete")
    return completed, len(flagship_items)


def beta_progress(state: dict[str, Any]) -> tuple[int, int]:
    """Return completed vs total beta-visible items."""

    beta_items = [item for item in state["pages"].values() if item["public_beta_visible"]]
    completed = sum(1 for item in beta_items if item["stage"] == "complete")
    return completed, len(beta_items)


def markdown_table(rows: list[list[str]]) -> str:
    """Render a small markdown table."""

    if not rows:
        return ""
    widths = [max(len(row[index]) for row in rows) for index in range(len(rows[0]))]
    rendered: list[str] = []
    for row_index, row in enumerate(rows):
        rendered.append(
            "| "
            + " | ".join(cell.ljust(widths[index]) for index, cell in enumerate(row))
            + " |"
        )
        if row_index == 0:
            rendered.append("| " + " | ".join("-" * width for width in widths) + " |")
    return "\n".join(rendered)


def json_dump(path: Path, payload: Any) -> None:
    """Write JSON atomically."""

    content = json.dumps(payload, indent=2, sort_keys=False) + "\n"
    atomic_write_text(path, content)


def read_text(path: Path) -> str:
    """Read a UTF-8 text file."""

    return path.read_text(encoding="utf-8")


def render_template(path: Path, values: dict[str, str]) -> str:
    """Render a simple ${name} template."""

    return Template(read_text(path)).safe_substitute(values)


def format_file_list(files: list[str]) -> str:
    """Return a markdown bullet list of repo-relative files."""

    return "\n".join(f"- `{file_name}`" for file_name in files)


def style_constraints_block() -> str:
    """Return a reusable style constraints block for prompts."""

    return "\n".join(f"- {line}" for line in STYLE_CONSTRAINTS)


def preview_links_for_files(files: list[str]) -> list[str]:
    """Return relevant preview links for content files."""

    links: list[str] = []
    for file_name in files:
        stem = Path(file_name).stem
        preview_path = PREVIEW_DIR / f"{stem}.html"
        if preview_path.exists():
            links.append(str(preview_path.relative_to(ROOT)))
        shareable_path = SHAREABLE_PREVIEW_DIR / f"{stem}.html"
        if shareable_path.exists():
            links.append(str(shareable_path.relative_to(ROOT)))
    return links


def detect_known_weak_spots(files: list[str], notes: str) -> list[str]:
    """Collect prompt hints from existing notes and page content."""

    weak_spots: list[str] = []
    if notes.strip():
        weak_spots.append(notes.strip())
    for file_name in files:
        text = read_text(ROOT / file_name)
        for phrase in PLACEHOLDER_PHRASES:
            if phrase in text:
                weak_spots.append(f"{file_name}: contains placeholder language ({phrase})")
                break
        if "**Confidence Level:** Low" in text:
            weak_spots.append(f"{file_name}: currently marked Low confidence")
    return weak_spots or ["No explicit weak spots recorded yet."]


def build_prompt_context(
    item_id: str,
    item: dict[str, Any],
    stage_name: str,
) -> dict[str, str]:
    """Build placeholder values for prompt templates."""

    files = item["files"]
    preview_links = preview_links_for_files(files)
    weak_spots = detect_known_weak_spots(files, item.get("notes", ""))
    return {
        "page_id": item_id,
        "current_stage": stage_name,
        "current_status": item["status"],
        "current_confidence": item["confidence"],
        "page_type": item["type"],
        "file_list": format_file_list(files),
        "known_weak_spots": "\n".join(f"- {entry}" for entry in weak_spots),
        "dependencies": ", ".join(item["dependencies"]) if item["dependencies"] else "None",
        "public_beta_visible": "true" if item["public_beta_visible"] else "false",
        "style_constraints": style_constraints_block(),
        "style_guide_path": str(STYLE_GUIDE_PATH.relative_to(ROOT)),
        "preview_links": "\n".join(f"- `{entry}`" for entry in preview_links) if preview_links else "- None",
    }


def extract_status_block(text: str) -> dict[str, str]:
    """Extract existing page metadata block values."""

    patterns = {
        "status": r"\*\*Page Status:\*\*\s*([^<\n]+)",
        "confidence": r"\*\*Confidence Level:\*\*\s*([^<\n]+)",
        "last_updated": r"\*\*Last Updated:\*\*\s*([^<\n]+)",
    }
    values: dict[str, str] = {}
    for key, pattern in patterns.items():
        match = re.search(pattern, text)
        if match:
            values[key] = match.group(1).strip()
    return values


def sync_page_metadata(text: str, *, status: str, confidence: str, last_updated: str) -> str:
    """Update the status metadata block near the top of a page."""

    updated = text
    replacements = {
        r"(?m)^\*\*Page Status:\*\*.*$": f"**Page Status:** {status}<br>",
        r"(?m)^\*\*Confidence Level:\*\*.*$": f"**Confidence Level:** {confidence}<br>",
        r"(?m)^\*\*Last Updated:\*\*.*$": f"**Last Updated:** {last_updated}<br>",
    }
    for pattern, replacement in replacements.items():
        if re.search(pattern, updated):
            updated = re.sub(pattern, replacement, updated, count=1)
        else:
            lines = updated.splitlines()
            insert_index = 1 if lines and lines[0].startswith("# ") else 0
            lines.insert(insert_index + 1, replacement)
            updated = "\n".join(lines)
    return updated


def find_internal_markdown_links(text: str) -> list[str]:
    """Return local markdown links from a document."""

    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def looks_like_local_link(target: str) -> bool:
    """Return whether a markdown link target is local to the repo."""

    return not (
        target.startswith("http://")
        or target.startswith("https://")
        or target.startswith("mailto:")
        or target.startswith("#")
    )


def resolve_local_link(source_file: Path, target: str) -> Path:
    """Resolve a local markdown link to an absolute path."""

    clean_target = target.split("#", 1)[0]
    clean_target = clean_target.split("?", 1)[0]
    return (source_file.parent / clean_target).resolve()


def detect_overview_like_paths(paths: list[Path]) -> set[Path]:
    """Infer overview files from sibling claim filename prefixes."""

    stems = {path.stem for path in paths}
    overviews: set[Path] = set()
    for path in paths:
        if any(other != path.stem and other.startswith(path.stem + "-") for other in stems):
            overviews.add(path)
    return overviews


def shareable_cluster_ids() -> list[str]:
    """Return cluster ids that already ship in shareable preview."""

    ignored = {"index", "methodology"}
    return sorted(
        path.stem
        for path in SHAREABLE_PREVIEW_DIR.glob("*.html")
        if path.stem not in ignored
    )


def infer_frontmatter_value(text: str, label: str, fallback: str) -> str:
    """Extract an inline markdown metadata value."""

    pattern = rf"\*\*{re.escape(label)}:\*\*\s*([^<\n]+)"
    match = re.search(pattern, text)
    return match.group(1).strip() if match else fallback


def seed_state_from_repo() -> dict[str, Any]:
    """Create an initial state payload from current repo files and page metadata."""

    all_paths = sorted(
        path
        for path in CONTENT_DIR.glob("*.md")
        if path.name not in {"_template.md", "index.md"}
    )
    overview_like = detect_overview_like_paths(all_paths)
    flagship_ids = shareable_cluster_ids()
    cluster_member_paths: set[Path] = set()
    pages: dict[str, Any] = {}
    for rank, cluster_id in enumerate(flagship_ids, start=1):
        overview_path = CONTENT_DIR / f"{cluster_id}.md"
        cluster_paths = [
            path
            for path in all_paths
            if path.stem == cluster_id or path.stem.startswith(cluster_id + "-")
        ]
        cluster_paths.sort(
            key=lambda path: (
                0 if path.stem == cluster_id else 1,
                path.name,
            )
        )
        files = [str(path.relative_to(ROOT)) for path in cluster_paths]
        cluster_member_paths.update(ROOT / file_name for file_name in files)
        pages[cluster_id] = {
            "type": "cluster",
            "files": files,
            "stage": "complete",
            "status": "Flagship Analysis",
            "confidence": "High",
            "priority": 101 - rank,
            "dependencies": [],
            "last_run": infer_frontmatter_value(
                read_text(overview_path),
                "Last Updated",
                "2026-04-22",
            ),
            "last_result": "success",
            "notes": (
                "Seeded from the existing shareable-preview cluster and reviewed supporting pages."
            ),
            "public_beta_visible": True,
        }
        for member_path in cluster_paths:
            if member_path.stem == cluster_id:
                continue
            member_text = read_text(member_path)
            member_status = infer_frontmatter_value(member_text, "Page Status", "Draft Analysis")
            if member_status != "Reviewed Analysis":
                continue
            member_id = member_path.stem
            pages[member_id] = {
                "type": "claim",
                "files": [str(member_path.relative_to(ROOT))],
                "stage": "validate",
                "status": "Reviewed Analysis",
                "confidence": infer_frontmatter_value(member_text, "Confidence Level", "Moderate"),
                "priority": 80,
                "dependencies": [cluster_id],
                "last_run": infer_frontmatter_value(member_text, "Last Updated", "2026-04-22"),
                "last_result": "seeded",
                "notes": (
                    "Reviewed supporting claim page inside a flagship cluster; use validate/status "
                    "passes to remove placeholders and keep it aligned with the overview."
                ),
                "public_beta_visible": False,
            }
    for path in all_paths:
        if path in cluster_member_paths:
            continue
        text = read_text(path)
        item_id = path.stem
        item_type = "overview" if path in overview_like else "claim"
        dependencies: list[str] = []
        if item_type == "claim":
            for overview_path in overview_like:
                if item_id.startswith(overview_path.stem + "-"):
                    dependencies = [overview_path.stem]
                    break
        status = infer_frontmatter_value(text, "Page Status", "Draft Analysis")
        confidence = infer_frontmatter_value(text, "Confidence Level", "Low")
        notes = ""
        if any(phrase in text for phrase in PLACEHOLDER_PHRASES):
            notes = "Contains placeholder language and still needs a first editorial pass."
        priority = 60 if item_type == "overview" else 20
        if status == "Reviewed Analysis":
            priority += 20
        pages[item_id] = {
            "type": item_type,
            "files": [str(path.relative_to(ROOT))],
            "stage": "focus" if status != "Flagship Analysis" else "complete",
            "status": status,
            "confidence": confidence if confidence in VALID_CONFIDENCE else "Low",
            "priority": priority,
            "dependencies": dependencies,
            "last_run": None,
            "last_result": "pending",
            "notes": notes,
            "public_beta_visible": False,
        }
    return {
        "meta": {
            "workflow": "FS3",
            "generated_on": today_iso(),
            "stage_config": str(STAGES_PATH.relative_to(ROOT)),
            "priority_config": str(PRIORITIES_PATH.relative_to(ROOT)),
            "notes": "Seeded from current repository page metadata and preview coverage.",
        },
        "pages": dict(sorted(pages.items())),
    }


def load_all_configs() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Load state plus the stage and priority configs."""

    stage_config = load_stage_config()
    priority_config = load_priority_config()
    state = load_state()
    validate_state(state, stage_config)
    return state, stage_config, priority_config


def cluster_overview_file(item_id: str, item: dict[str, Any]) -> str | None:
    """Return the overview file for a cluster item when possible."""

    if item["type"] != "cluster":
        return None
    expected = f"content/prophecies/{item_id}.md"
    if expected in item["files"]:
        return expected
    return item["files"][0] if item["files"] else None


def stage_prompt_template_path(stage_name: str) -> Path:
    """Return the template path for a stage."""

    return ROOT / "prompts" / "templates" / f"{stage_name}.md"


def stage_prompt_available(stage_name: str) -> bool:
    """Return whether a stage should generate a prompt."""

    config = load_stage_config()
    return bool(config["stages"][stage_name]["generates_codex_prompt"])


def render_stage_prompt(item_id: str, item: dict[str, Any], stage_name: str) -> str:
    """Render a prompt for a specific item and stage."""

    template_path = stage_prompt_template_path(stage_name)
    if not template_path.exists():
        raise RefinementError(f"Prompt template not found for stage {stage_name}: {template_path}")
    values = build_prompt_context(item_id, item, stage_name)
    body = render_template(template_path, values).rstrip()
    commit_message = f'Refine {item_id} during {stage_name} stage'
    return (
        f"{body}\n\n"
        "Style guide reference:\n"
        f"- `{values['style_guide_path']}`\n\n"
        "Execution notes:\n"
        f"- Dependencies: {values['dependencies']}\n"
        f"- Public beta visible: {values['public_beta_visible']}\n"
        f"- Preview targets:\n{values['preview_links']}\n\n"
        "Finish by committing and pushing your work:\n"
        "```bash\n"
        "git add -A\n"
        f'git commit -m "{commit_message}"\n'
        "git push\n"
        "```"
    )
