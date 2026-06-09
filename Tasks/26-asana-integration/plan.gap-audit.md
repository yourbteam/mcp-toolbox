# Doc Gap Audit — plan.md (Asana integration)

**Document under audit:** `Tasks/26-asana-integration/plan.md` (2444 lines)
**Scope:** internal document readiness only (self-sufficiency, decision-completeness, internal consistency, grounding of *cited* claims). Interop/runtime/data-reality already covered by `plan.satisfaction-audit.md`.

---

## Cycle 1 Assessment

### Section Inventory

| unit_id | section/title | unit type | implementation relevance |
| --- | --- | --- | --- |
| U0 | Intro ("Implements the 67 tools…") | intro | scope statement |
| U1 | §1 config.py changes | code delta | exact env vars + insertion site |
| U2 | §2 tools/__init__.py changes | code delta | import + registration wiring |
| U3 | §3 asana_tool.py (full code) | code block | the implementation (helpers + 67 tools) |
| U4 | §4 tests/test_asana_tool.py (full code) | code block | 84 test functions |
| U5 | §5 CLAUDE.md changes | doc delta | source-layout + integration section |
| U6 | §6 Verification steps | commands | pytest/ruff/pyright |
| U7 | Risk notes / decisions | locked-decision list | null-path, multipart, pyright, bool params |

### Coverage Matrix

| unit_id | lens | status | evidence |
| --- | --- | --- | --- |
| U0 | decision-completeness | checked | "67 tools … singleton, `_success`, ToolError, direct HTTP" — matches U3 |
| U1 | schema/grounding | checked | adds `ASANA_ACCESS_TOKEN`/`ASANA_DEFAULT_WORKSPACE_ID` "after the Stripe block"; config.py:107-108 is last block (verify-plan) |
| U2 | grounding/data-flow | checked | alphabetical-first import + `register_tools` call; tools/__init__.py:6 first = aws_ssm; asana<aws (verify-plan) |
| U3 | decision-completeness | checked | all helpers defined; 67 `@mcp.tool()` (grep=67); `_req` tuple contract; `_clean` params-only |
| U3 | edge/failure behavior | checked | 429/≥400 raise; 204/empty→`({},None)`; `_workspace` raises; exactly-one list_tasks guard |
| U3 | contradictions | checked | list_tasks 0-scope msg "Specify exactly one…", >1 msg "only one task scope…" |
| U4 | test/acceptance | **gap found** | GAP-001 — `test_list_tasks_requires_scope` (line 1969) asserted `match="at least one"` vs code msg "exactly one" |
| U4 | decision-completeness | checked | 84 test fns; every tool invoked (verify-plan); body-envelope asserts; error 400/402/404/429; multipart; custom-field 3 value types |
| U5 | decision-completeness | checked | "67 Asana tools" + config + auth + envelope note — consistent with U3 |
| U6 | validation commands | checked | exact `uv run pytest/ruff/pyright` commands |
| U7 | locked decisions | checked | bool-query rendering, null-detach, custom-field None-clear, multipart, pyright-not-excluded — all consistent with U3 |
| all | vague wording | checked | rg for TBD/TODO/maybe/combinable/XOR/such-as/or-equivalent → only legitimate "at least one mutable field" in update tools |
| all | repo grounding | checked | config/init/server claims grounded by verify-plan + satisfaction-audit |
| all | approval/out-of-scope | checked | out-of-scope (`.not` filters, user_task_list, webhook update) inherited from analysis; no unapproved commitment |

### Blocker Gap Ledger

| gap_id | severity | unit_id | lens | evidence | why blocker | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| GAP-001 | blocker | U4 | contradiction/test | `test_list_tasks_requires_scope` line 1969 `match="at least one"`; U3 0-scope branch raises "Specify **exactly one** of project_gid, section_gid, tag_gid, or assignee." — "at least one" absent from the message | the test would FAIL at runtime (regex no match) — a follow-up implementer copying the plan verbatim gets a red test; internal code/test contradiction | change the test `match` to "exactly one" | line 1969 now `match="exactly one"`; U3 0-scope msg contains "Specify exactly one of" | closed |

### Cleanup List
_(none actionable; "at least one mutable field required" in update_project/update_task/update_tag is correct domain wording, not a list_tasks reference.)_

---

## Cycle 1 Plan

### Gap-To-Fix Map

| gap_id | target unit | exact decision to lock | edit summary | validation check |
| --- | --- | --- | --- | --- |
| GAP-001 | U4 line 1969 | the 0-scope error test must assert the actual message token "exactly one" | replace `match="at least one"` → `match="exactly one"` | grep the test asserts "exactly one"; confirm U3 message contains it |

## Cycle 1 Edits
- U4 line 1969: `match="at least one"` → `match="exactly one"`. Closes GAP-001.

## Cycle 1 Validation
- `rg -n 'match="at least one"' plan.md` → only update-tool tests remain (lines 1816 = update_project, 1198-adjacent) which correctly pair with "Provide at least one field to update." messages in U3. The list_tasks 0-scope test no longer mismatches.
- `rg -n 'exactly one|only one task scope' plan.md`: U3 messages ("Specify exactly one of…", "only one task scope…") and U4 tests (`match="exactly one"`, `match="only one task scope"`) now align with the two distinct guard branches.
- Post-edit new-gap pass: the edit touches only the regex literal; no new contradiction, no scope drift. `test_list_tasks_rejects_multiple_scopes` (line 1984) still pairs with the `chosen > 1` branch ("only one task scope"). `test_list_tasks_assignee_adds_workspace` (single scope) still valid under exactly-one. No new gap.
- Counts unchanged: 67 tools / 84 tests.

---

## Cycle 2 Assessment

Fresh full-document pass over the edited plan.

- **U0–U2 (scope/config/wiring):** decision-complete; insertion sites grounded; no contradiction.
- **U3 (code):** all 67 tools present; helper contracts consistent; list_tasks guard messages match their tests; null-path/multipart/error handling complete; no vague wording.
- **U4 (tests):** every tool invoked; all `match=` strings now correspond to a real raised message (`exactly one`, `only one task scope`, `at least one` only on update-field tests, `text`, `File not found`, `workspace`, `ASANA_ACCESS_TOKEN`, `Not a valid task`, `upgrade required`, `Not Found`, `rate limit`); body-envelope and param assertions concrete.
- **U5–U7:** CLAUDE.md delta, verification commands, and locked decisions all consistent with U3; no unresolved choice.
- **Cross-section:** the three audits (gap/coverage/satisfaction) and the two source docs (analysis/plan) now agree on the exactly-one list_tasks contract.

**Open blocker gaps: 0.** No edits this cycle.

## Final Convergence Check

### Final Readiness Proof

| category | status | evidence |
| --- | --- | --- |
| runtime entry points & data flow | ready | U2 registration wiring → `register_all_tools` (server.py:10, satisfaction-audit) |
| schema/fields/interfaces/helpers/artifacts | ready | U3 `_get_client`/`_success`/`_req`/`_clean`/`_workspace`/`_single`/`_list` + 67 typed tools |
| edge cases & failure behavior | ready | U3 429/≥400/204 branches; exactly-one + workspace guards; U4 error/edge tests (400/402/404/429, missing token/workspace, requires-field/scope/text, missing-file) |
| resume/idempotency | ready (n/a) | stateless REST tool wrappers; no resumable state — async duplicate returns Job polled via `asana_get_job` (U3) |
| validation commands / test scenarios / acceptance | ready | U6 exact commands; U4 84 tests; every tool + value-type + error-code asserted |
| repo grounding | ready | config/init/server/MCP-shape claims grounded (verify-plan + satisfaction-audit empirical pytest) |
| approval boundaries | ready | no approval-sensitive persona/contract text; doc-only edits |
| out-of-scope boundaries | ready | `.not` filters, user_task_list endpoint, attachment parent=project/brief, webhook update explicitly scoped out (analysis) |

**Ledger status:** GAP-001 closed. Zero open blockers.

**CONVERGED — internal document readiness.** plan.md is self-sufficient, decision-complete, and internally consistent; all cited config/wiring/runtime claims are grounded. This establishes internal readiness only — interop and runtime/data-reality were established separately in `plan.satisfaction-audit.md`. Validation: `grep -c '@mcp.tool()'`=67, `grep -c 'async def test_'`=84, stale/contradiction scans clean.
