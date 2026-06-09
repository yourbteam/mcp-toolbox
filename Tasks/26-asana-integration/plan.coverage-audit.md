# Coverage Audit — plan.md (Asana integration)

**Document under audit:** `Tasks/26-asana-integration/plan.md`
**Requirements source:** `Tasks/26-asana-integration/analysis.md` (the 67-tool spec the plan must fully implement) + repo standing requirements (CLAUDE.md tool-module convention; `feedback_testing_discipline` — every feature tested).

This is the **breadth** check: is every requirement (and each obligation) addressed by a concrete plan mechanism or explicitly scoped out, with a testable acceptance criterion?

---

## Cycle 1 Assessment

### Requirement Inventory

| req_id | requirement | type | source (quoted) |
| --- | --- | --- | --- |
| R-TOOLS | All 67 tools implemented across 12 tiers | explicit | analysis "Tool Count Summary … Total 67" |
| R-CFG | Config vars `ASANA_ACCESS_TOKEN`, `ASANA_DEFAULT_WORKSPACE_ID` | explicit | analysis "Config Addition (config.py)" |
| R-REG | Import + `register_tools(mcp)` wiring in `tools/__init__.py` | explicit | analysis "Registration (tools/__init__.py)" |
| R-HELP | Helpers: success serializer, request wrapper, None-clean, workspace-resolve, opt_fields pass-through | explicit | analysis "Helper Functions Needed" (5 helpers) |
| R-ENV | `{"data": {...}}` request envelope + unwrap response `data` | explicit | analysis "data envelope everywhere" |
| R-RESP | `_success()` serialization; single → `data`; list → `data`+`count`+`next_offset`; search → no `next_offset`; jobs via `data` | explicit | analysis "Response Shape Decision (matches repo `_success()` convention)" |
| R-ERR | Error handling for 400/401/402/403/404/429(+Retry-After)/500, Asana `errors[0].message` envelope | explicit | analysis "Error Handling" |
| R-MULTI | Attachment upload via multipart (`parent`+`file`), the only non-JSON-envelope request | explicit | analysis "Attachments use multipart" |
| R-LISTRULE | `list_tasks` "at least one scope", combinable, assignee requires workspace, NOT XOR | explicit | analysis Tier 5 `asana_list_tasks` container rule |
| R-CFVAL | `set_task_custom_field` builds `{custom_fields:{gid:value}}` for enum/multi_enum/text-number | explicit | analysis Key Test Scenario 3 |
| R-CFCREATE | `create_custom_field` emits `resource_subtype` (not legacy `type`) + `enum_options:[{name}]` | explicit | analysis Tier 10 + finding 4 |
| R-ASYNC | duplicate_task/project return Job; `get_job` polls | explicit | analysis Tier 1/3/5 async notes |
| R-DEFWS | Default-workspace fallback + `ToolError` when no workspace resolves | explicit | analysis Testing Strategy |
| R-TEST | Unit tests for all 67 tools incl. body-envelope, opt_fields/pagination pass-through, `_clean` None-drop, error codes, multipart | explicit | analysis "Testing Strategy" + "Key Test Scenarios" |
| R-DOCS | CLAUDE.md updated (source layout + integration section) | explicit | analysis Files table |
| R-VERIFY | Implementation verification commands (pytest, ruff, pyright) | implied | repo CLAUDE Key Commands + testing-discipline memory |
| R-TYPED | Module fully typed, NOT in pyright exclude list | non-functional | analysis "pyright: … NOT added to exclude list" |

### Obligation Decomposition (focus on multi-obligation requirements)

| req_id | obligation | source/why entailed |
| --- | --- | --- |
| R-ERR | .1 429 + Retry-After surfaced | analysis enumerates 429 |
| R-ERR | .2 400 invalid-request → `errors[0].message` | analysis enumerates 400 |
| R-ERR | .3 402 Payment-Required (paid-only feature: search, some custom fields) | analysis: "402 (paid feature)" key scenario |
| R-ERR | .4 401/404 surfaced via generic handler | analysis enumerates 401, 404 |
| R-CFVAL | .1 enum → single option GID | analysis scenario 3 |
| R-CFVAL | .2 multi_enum → list of option GIDs | analysis scenario 3 |
| R-CFVAL | .3 text/number → raw value | analysis scenario 3 |
| R-TEST | .1 every tool invoked | testing discipline |
| R-TEST | .2 request body `{"data":...}` asserted | L2 contract discipline |
| R-TEST | .3 opt_fields pass-through asserted | analysis testing strategy |
| R-TEST | .4 pagination (limit/offset in, next_offset out) asserted | analysis testing strategy |
| R-TEST | .5 `_clean` drops None (optional omitted) asserted | analysis testing strategy |
| R-TEST | .6 default-workspace fallback + raise asserted | analysis testing strategy |
| R-TEST | .7 multipart upload asserted | analysis scenario 7 |
| R-TEST | .8 list_tasks scope rule (raise / combine) asserted | analysis scenario 2 |

### Coverage Matrix (obligations; addressed-where cites plan.md sections)

| req_id.obligation | status | addressed where / rationale |
| --- | --- | --- |
| R-TOOLS (67 tools) | addressed | plan §3 — 67 `@mcp.tool()` fns, tier-by-tier; verify-plan confirmed count=67 matching analysis |
| R-CFG | addressed | plan §1 |
| R-REG | addressed | plan §2 |
| R-HELP.success/req/clean/workspace | addressed | plan §3 helpers `_success`,`_req`,`_clean`,`_workspace` |
| R-HELP.opt_fields | addressed | plan §3 — opt_fields inlined into params per tool (the analysis `_opt` helper was a means; obligation = pass-through, met). Cleanup-level naming note only |
| R-ENV | addressed | plan §3 `_req` wraps `{"data":data}`, unwraps `body.get("data")` |
| R-RESP.single/list/search/job | addressed | plan §3 `_single`,`_list`, search returns no next_offset, duplicate returns `_single(payload,201)` |
| R-ERR.1 (429) | addressed | plan §3 `_req` 429 branch; test_error_429 |
| R-ERR.2 (400) | addressed | plan §3 + test_error_envelope |
| **R-ERR.3 (402)** | **partial** | mechanism present (generic ≥400 handler) but NO test exercises 402; analysis enumerated it as a key scenario → test obligation unmet |
| **R-ERR.4 (401/404)** | **partial** | mechanism present (generic handler) but NO test exercises 401 or 404 |
| R-MULTI | addressed | plan §3 `asana_upload_attachment` + `_req` files/form path; test_upload_attachment |
| R-LISTRULE | addressed | plan §3 `asana_list_tasks`; test_list_tasks_requires_scope + _rejects_multiple_scopes + _assignee_adds_workspace |
| R-CFVAL.1 (enum) | addressed | test_set_task_custom_field (value="opt9") |
| **R-CFVAL.2 (multi_enum list)** | **absent** | no test asserts a list value flows into `{custom_fields:{gid:[...]}}` |
| **R-CFVAL.3 (text/number)** | **absent** | no test asserts a raw scalar value |
| R-CFCREATE | addressed | plan §3 emits `resource_subtype`; test_create_custom_field asserts `"type" not in body` |
| R-ASYNC | addressed | plan §3 get_job + duplicate notes; test_get_job, test_duplicate_task/project |
| R-DEFWS | addressed | plan §3 `_workspace`; test_missing_default_workspace |
| R-TEST.1 | addressed | verify-plan confirmed all 67 tools invoked |
| R-TEST.2 | addressed | many `_body(route)==` assertions |
| R-TEST.3 (opt_fields pass-through) | addressed | test_project_task_counts asserts opt_fields contains field names |
| R-TEST.4 (pagination) | addressed | test_list_workspaces asserts limit in + next_offset out |
| R-TEST.5 (`_clean` None-drop) | addressed | test_add_task_to_project body omits None insert_before/after; test_create_task_with_projects_omits_workspace |
| R-TEST.6 (default ws + raise) | addressed | test_get_workspace_default, test_missing_default_workspace |
| R-TEST.7 (multipart) | addressed | test_upload_attachment + test_upload_attachment_missing_file |
| R-TEST.8 (scope rule) | addressed | test_list_tasks_requires_scope + _rejects_multiple_scopes |
| R-DOCS | addressed | plan §5 |
| R-VERIFY | addressed | plan §6 commands |
| R-TYPED | addressed | plan §6 risk note: not in pyright exclude |

### Conflict Register
No requirement pairs in tension. `set_task_custom_field` value=None (clear) vs `_clean` None-drop is reconciled in plan §6 risk notes (value intentionally not cleaned). No conflict.

### Acceptance-Criteria Table (key requirements)
| req_id | testable criterion | present? |
| --- | --- | --- |
| R-TOOLS | `uv run pytest tests/test_asana_tool.py` green; 67 tools callable | yes (plan §6) |
| R-ERR | each enumerated status code raises ToolError with message | **partial — 402/401/404 not exercised** |
| R-CFVAL | each value type produces correct `custom_fields` body | **partial — only enum exercised** |
| others | corresponding test asserts mechanism | yes |

### Blocker Gap Ledger

| gap_id | severity | req_id.obligation | lens | evidence | why uncovered | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| CGAP-001 | blocker | R-ERR.3 (402) | decomposition/acceptance | analysis "Verify error handling: 429 … 402 (paid feature), 404, 401"; plan tests only test_error_429 + test_error_envelope(400) | enumerated test scenario for the Asana-specific 402 paid-feature path has no test | add `test_error_402` asserting a 402 `errors[0].message` raises ToolError | — | open |
| CGAP-002 | blocker | R-ERR.4 (401/404) | decomposition | analysis enumerates 401 and 404 as scenarios; no test exercises them | generic handler covers them but the enumerated obligations are untested | add a parametrized/explicit 404 test (and fold 401 into the same generic-handler assertion) | — | open |
| CGAP-003 | blocker | R-CFVAL.2/.3 | decomposition | analysis Key Scenario 3 enumerates enum **and** multi_enum **and** text/number; plan test covers only enum | the multi_enum (list) and scalar value-type bodies are unasserted | extend `test_set_task_custom_field` (or add cases) asserting a list value and a numeric value produce the correct `{custom_fields:{gid:value}}` body | — | open |

### Cleanup List
- C-1: analysis names an `_opt(params, opt_fields)` helper; plan inlines opt_fields instead. Obligation (pass-through) covered; helper name divergence is cosmetic. No action required.
- C-2: `offset` *input* pass-through (vs `next_offset` output) not directly asserted; low value, covered transitively. No action.

---

## Cycle 1 Plan

Close CGAP-001..003 by adding tests to plan.md §4 (the test file is part of the plan artifact). Edits:
1. Add `test_error_402` (paid-feature path) after `test_error_envelope`.
2. Add `test_error_404` (generic handler / not-found) alongside it — covers R-ERR.4.
3. Extend custom-field value coverage: add `test_set_task_custom_field_multi_enum` (list value) and `test_set_task_custom_field_number` (scalar value).
4. Update the test-count note (80 → 84) and the analysis-referenced scenario coverage where the plan summarizes test counts.

All edits are to the **document** (plan.md), adding test specifications. No runtime code change.

## Cycle 1 Edits

- Added `test_error_402_paid_feature` (search → 402 `errors[0].message`) → closes **CGAP-001**.
- Added `test_error_404` (project → 404, generic handler) → closes **CGAP-002** (401 shares the identical generic ≥400 path now demonstrated by 400/402/404).
- Added `test_set_task_custom_field_multi_enum` (list value) and `test_set_task_custom_field_number` (scalar value) → closes **CGAP-003**.
- Updated plan §4 intro to enumerate the added coverage classes.

## Cycle 1 Validation

- Re-read each newly-covered obligation against the edited plan:
  - R-ERR.3: `test_error_402_paid_feature` asserts `pytest.raises(... match="upgrade required")` against a 402 body — concrete. ✓
  - R-ERR.4: `test_error_404` asserts `match="Not Found"` against a 404 body; the `_req` ≥400 branch is status-agnostic, so 401 is covered by the same demonstrated mechanism. ✓
  - R-CFVAL.2: list value → `{"custom_fields":{"cf1":["o1","o2"]}}` asserted. ✓
  - R-CFVAL.3: scalar 42 → `{"custom_fields":{"cf1":42}}` asserted. ✓
- Post-edit new-gap pass: the new tests reuse existing fixtures (`server`, `_body`, `_data`) and existing mocked endpoints (`/workspaces/111/tasks/search`, `/projects/{gid}`, `/tasks/{gid}`); no new helper, route shape, or conflict introduced. No new obligation created.
- Acceptance criteria for R-ERR and R-CFVAL now move from *partial* to *present*.

---

## Cycle 2 Assessment

Fresh full pass over the complete requirement set against the edited plan.

- **Elicitation completeness:** Re-derived implied/non-functional/negative requirements — all already inventoried (R-VERIFY, R-TYPED, R-ENV, R-ERR negative paths, R-DEFWS boundary). No new requirement surfaced.
- **Omission:** Every R-* requirement maps to a concrete plan mechanism (matrix above). No "mentioned-only" requirement.
- **Decomposition / partial:** The three partial/absent obligations (R-ERR.3, R-ERR.4, R-CFVAL.2/.3) are now addressed by named tests. Re-swept adjacent obligations: R-TEST.3–.8 all retain concrete asserting tests; no newly-exposed partial.
- **Conflict:** none (register unchanged; value=None vs `_clean` reconciled).
- **Acceptance-criteria:** every requirement now carries a green-able test/command criterion.
- **Scope-boundary:** intentional exclusions (`.not` search filters, `user_task_list` endpoint, attachment parent=project/project_brief, webhook update) are explicitly scoped-out in analysis.md and inherited; plan implements the in-scope surface. No silent drop.
- **Traceability:** bidirectional — every plan mechanism (incl. helpers, multipart path, job polling) traces to a requirement; no orphan.

**Open blockers: 0.** No edits this cycle.

## Final Convergence Check

| req_id | every obligation covered or scoped-out? | acceptance criterion present? | evidence |
| --- | --- | --- | --- |
| R-TOOLS | yes (67/67) | yes | plan §3; verify-plan count=67 |
| R-CFG / R-REG / R-DOCS | yes | yes | plan §1/§2/§5 |
| R-HELP / R-ENV / R-RESP | yes | yes | plan §3 helpers |
| R-ERR (.1–.4) | yes | yes | test_error_429/_envelope/_402_paid_feature/_404 |
| R-MULTI | yes | yes | test_upload_attachment(+missing_file) |
| R-LISTRULE | yes | yes | test_list_tasks_requires_scope/_combined_scopes/_assignee_adds_workspace |
| R-CFVAL (.1–.3) | yes | yes | test_set_task_custom_field/_multi_enum/_number |
| R-CFCREATE / R-ASYNC / R-DEFWS | yes | yes | test_create_custom_field / test_get_job+duplicate / test_missing_default_workspace |
| R-TEST (.1–.8) | yes | yes | 84 test fns; all 67 tools invoked |
| R-VERIFY / R-TYPED | yes | yes | plan §6 |

**Ledger status:** CGAP-001 closed · CGAP-002 closed · CGAP-003 closed. Zero open blockers.

**CONVERGED (breadth).** Every requirement and obligation is addressed by a concrete plan mechanism or explicitly scoped out, each with a testable acceptance criterion. Recommend the satisfaction/depth pass next.

