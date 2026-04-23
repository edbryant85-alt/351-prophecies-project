# FS3 Refinement Workflow

The FS3 refinement workflow gives the project a reproducible, stateful editorial loop for prophecy pages and passage clusters. It is file-based, Python-driven, YAML-backed, and safe to run locally in Codespaces without any external service.

## What FS3 Means

FS3 is the ordered editorial loop used by the workflow state:

1. `focus`
2. `steelman`
3. `structure`
4. `sync`
5. `overview`
6. `status`
7. `validate`
8. `complete`

Stage definitions:

- `focus`: tighten the claim, reduce redundancy, and clarify scope.
- `steelman`: strengthen Christian, skeptical, and Jewish interpretations fairly.
- `structure`: prune, merge, or consolidate over-fragmented claims.
- `sync`: update overview pages, indexes, tracker notes, preview links, and metadata.
- `overview`: reconcile overview pages with surviving claim pages after structural changes.
- `status`: refresh status and confidence labels.
- `validate`: final sanity pass for placeholders, stale links, and stale references.
- `complete`: finished for the current editorial standard.

## Core Files

- `data/refinement-state.yaml`: single source of truth for tracked workflow items.
- `config/refinement-stages.yaml`: legal stage order plus per-stage behavior.
- `config/refinement-priorities.yaml`: queue selection and scoring rules.
- `scripts/refinement_runner.py`: selection, reporting, validation, and bootstrap entry point.
- `scripts/generate_codex_prompt.py`: stage-specific Codex prompt generator.
- `scripts/advance_state.py`: records a pass result and advances to the next legal stage on success.
- `scripts/build_dashboard.py`: regenerates `docs/refinement-dashboard.md` and `.json`.
- `scripts/sync_status_metadata.py`: syncs status/confidence/last-updated metadata into page headers.
- `scripts/check_links.py`: checks local markdown and preview links.
- `scripts/check_placeholders.py`: reports residual placeholder language.

## How Queue Selection Works

Selection is deterministic and score-based. The default queue prefers:

1. incomplete flagship items
2. reviewed or near-finished work ahead of raw drafts
3. clusters before isolated claim pages
4. public-beta-visible items
5. stale items that have not been touched recently

Blocked items are skipped automatically when `last_result: blocked`. Claims can also be held back by dependencies, which lets overview work lead the queue when a supporting claim depends on that overview.

## End-to-End Workflow

1. Validate or bootstrap the state:

```bash
python scripts/refinement_runner.py --validate
python scripts/refinement_runner.py --bootstrap
```

2. Ask for the next recommended target:

```bash
python scripts/refinement_runner.py --next
python scripts/refinement_runner.py --list --limit 10
python scripts/refinement_runner.py --next --flagship-only
```

3. Generate a Codex-ready prompt for the current stage:

```bash
python scripts/generate_codex_prompt.py --page isaiah-53 --stage steelman
python scripts/generate_codex_prompt.py --page isaiah-53 --stage steelman --output stdout
```

4. After the editorial pass is finished, advance the state:

```bash
python scripts/advance_state.py --page isaiah-53 --result success --notes "Steelman pass completed and pushed"
python scripts/advance_state.py --page micah-5-2-313 --result blocked --notes "Needs a human decision on merge vs standalone handling"
```

5. Sync metadata and rebuild dashboards:

```bash
python scripts/sync_status_metadata.py
python scripts/build_dashboard.py
python scripts/check_links.py
python scripts/check_placeholders.py
```

## Example Cluster Flow

One cluster example using `isaiah-53`:

```bash
python scripts/refinement_runner.py --page isaiah-53
python scripts/generate_codex_prompt.py --page isaiah-53 --stage focus
python scripts/advance_state.py --page isaiah-53 --result success --notes "Focus pass completed and pushed"
python scripts/generate_codex_prompt.py --page isaiah-53 --stage steelman
python scripts/advance_state.py --page isaiah-53 --result success --notes "Steelman pass completed and pushed"
python scripts/build_dashboard.py
```

## Recovery and Bad State Handling

If state becomes inconsistent:

1. Run `python scripts/refinement_runner.py --validate`.
2. Fix the flagged YAML entry manually in `data/refinement-state.yaml`.
3. Re-run validation.
4. If the seed data needs to be rebuilt from current repo metadata, run `python scripts/refinement_runner.py --bootstrap`.

The validation checks catch:

- unknown stage names
- illegal stage applicability
- missing referenced files
- invalid statuses or confidence labels
- unknown dependencies
- invalid `last_run` dates
- invalid `last_result` values

## Adding a New Page or Cluster

To add a new page manually:

1. Add a new entry under `pages:` in `data/refinement-state.yaml`.
2. Set `type` to `claim`, `overview`, or `cluster`.
3. List repo-relative file paths under `files`.
4. Set the current `stage`, `status`, `confidence`, `priority`, and `public_beta_visible`.
5. Add any dependencies on overview or cluster items.

To add a cluster:

1. Use the overview slug as the cluster id when practical.
2. Include the overview page plus all in-scope claim pages under `files`.
3. Mark the cluster `type: cluster`.
4. Keep member files in the cluster list synchronized with actual surviving pages.

## Marking Something Blocked

Use `advance_state.py` with `--result blocked`:

```bash
python scripts/advance_state.py --page zechariah-11 --result blocked --notes "Needs source review before status can be raised"
```

Blocked items stay on their current stage and are skipped by automatic queue selection until the result is changed later.

## Beta-Visible Priorities

`public_beta_visible: true` boosts queue selection and gets separate progress reporting in the dashboard. In the current seed data, the shareable-preview flagship clusters are marked beta-visible. Use `--beta-visible-only` to work just that slice of the queue:

```bash
python scripts/refinement_runner.py --list --beta-visible-only
python scripts/refinement_runner.py --next --beta-visible-only
```

## Notes on Metadata Sync

`scripts/sync_status_metadata.py` only updates the top metadata block:

- `Page Status`
- `Confidence Level`
- `Last Updated`

For `cluster` items, metadata sync only updates the overview page file for that cluster rather than rewriting every supporting claim page.

It does not rewrite the body analysis. This makes it safe to use after status review or dashboard refreshes.
