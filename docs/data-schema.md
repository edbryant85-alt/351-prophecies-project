# Prophecy Master Data Schema

This file explains the fields used in [prophecies-master.yaml](/workspaces/351-prophecies-project/data/prophecies-master.yaml).

## Fields

### `number`
The prophecy number from the original 351-entry list.

Use an integer when a page maps cleanly to a single numbered claim.
Use `null` when the mapping is not decided yet or when one page may eventually represent multiple numbered claims.

### `title`
A human-readable title for the prophecy entry.

Examples:
- `Isaiah 7:14`
- `Psalm 22`
- `2 Samuel 7`

### `slug`
The filename-safe identifier for the page.

Rules:
- lowercase
- hyphen-separated
- matches the markdown filename without `.md`

Example:
- page file: `content/prophecies/isaiah-7-14.md`
- slug: `isaiah-7-14`

### `ot_reference`
The Old Testament reference used for the page.

This can be a verse, passage, or chapter reference depending on how the page is scoped.

### `claim_summary`
A short summary of the prophecy claim being evaluated.

Keep this brief and descriptive so it can be reused in indexes, trackers, and future generation scripts.

### `nt_fulfillment`
The claimed New Testament fulfillment passage or passages.

Use a short semicolon-separated string for now.
Leave blank when the fulfillment reference has not been entered yet.

### `skeptic_failed_criteria`
The skeptic criteria numbers the claim is said to fail.

For now, store this as a short comma-separated string such as `2,4,5,6`.
Leave blank when not yet evaluated.

### `status`
The current workflow state of the entry.

Allowed values:
- `not started`
- `in progress`
- `completed`

Use `not started` for generic placeholders, `in progress` for entries with meaningful custom scaffolding or active writing, and `completed` only when the page is substantially finished.
