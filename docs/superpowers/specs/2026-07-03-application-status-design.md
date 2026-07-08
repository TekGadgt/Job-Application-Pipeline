# Application Status Field — Design Spec

**Date:** 2026-07-03
**Status:** Approved for planning
**Scope:** Tiny. One new user-owned frontmatter field tracking where an application actually stands. The pipeline writes the default and never advances it — **this tool does not submit anything**; every value past the default is a human action recorded by a human.

## Goal

Published notes carry `application_status: Unsubmitted` in frontmatter. The user advances it by hand as the application progresses; Dataview can then board/filter the vault by pipeline stage of the *application*, not just of the *note*.

## Field Semantics (binding)

```yaml
application_status: Unsubmitted
```

- Written by publish with the literal default `Unsubmitted` for every new note.
- **Free text, never validated by the pipeline.** The suggested vocabulary is documentation, not schema: `Unsubmitted`, `Submitted`, `In Talks`, `Denied`, `Offered`, `Accepted`. Users add their own (`Ghosted`, `Withdrawn`) without touching code.
- Placement: immediately after `result_of_contact` in the frontmatter mapping (order is stable, `sort_keys=False`).

### Relationship to the two existing lifecycle fields (README table)

The note now has three distinct lifecycles — this must be documented or it will confuse users:

| Field | Owner | Meaning |
|---|---|---|
| `status` | pipeline ↔ user | note lifecycle: `to_review` until you triage it; advancing it arms skip-on-edit |
| `result_of_contact` | user (VEC) | VEC contact-record language: `found` → `applied` → `interview` → … |
| `application_status` | user | application lifecycle: `Unsubmitted` → `Submitted` → `In Talks` → `Denied`/`Offered`/`Accepted` |

They overlap deliberately rather than being merged: `status` drives pipeline behavior, `result_of_contact` must stay in VEC-compliant wording, `application_status` is the human-friendly board column.

## Skip-on-edit extension (the one real code change beyond the key)

Today `is_user_touched` (store/obsidian.py) checks only `status != "to_review"`. A user who sets `application_status: Submitted` but never advances `status` would have that edit **clobbered** by a `--reprocess`/`--force`-adjacent republish. Fix: a note is user-touched when

```
status != "to_review"  OR  application_status != "Unsubmitted"
```

(Missing `application_status` — notes published before this feature — counts as `Unsubmitted`, preserving current behavior for old notes.) `--force` still overrides, as everywhere.

## Compatibility

- New key on new notes only; previously published notes are never rewritten to add it (same policy as comp-in-notes).
- Combined frontmatter order across pending note-touching specs: `..., result_of_contact, application_status, score, comp_min, comp_max, comp_currency, comp_period, status, job_id` (+ resume keys when present). Whichever spec lands later rebases golden tests mechanically.
- No changes to Job, config, stages, seen index, or run history.

## Testing (no network, no tokens)

- Publish: new note contains `application_status: Unsubmitted` in the bound position.
- `is_user_touched`: false for fresh note; true when `status` advanced; true when only `application_status` advanced; false when `application_status` key absent and `status: to_review` (legacy note); malformed frontmatter still treated as user-owned.
- Existing publish/e2e golden assertions updated once.

## Acceptance

- README: the three-lifecycle table above, plus the suggested vocabulary with a note that it's free text.

## Non-Goals

- No status validation/enum enforcement, no configurable status list, no pipeline transitions of the field (ever — no-auto-apply is a project invariant), no migration pass over existing notes, no syncing between the three lifecycle fields.
