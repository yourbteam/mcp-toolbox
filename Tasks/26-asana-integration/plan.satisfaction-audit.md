# Satisfaction Audit — plan.md (Asana integration)

**Document under audit:** `Tasks/26-asana-integration/plan.md`
**Evidence sources beyond the doc:** real Asana REST API (developers.asana.com), installed runtime (`mcp 1.26.0`, `httpx 0.28.1`, `respx`), sibling tool modules + `server.py` hub, an empirical `uv run pytest tests/test_notion_tool.py` run.

This is the **depth** check: of the requirements the plan addresses (coverage converged), does each actually HOLD end-to-end?

---

## Cycle 1 Assessment

### Requirement Inventory (addressed set; depth-relevant)

| req_id | requirement | type | source (quoted) |
| --- | --- | --- | --- |
| R-REG | asana tools register at startup without collision | invariant | plan §2; repo `server.py` |
| R-HARNESS | test helpers `_r`/`_body` match installed MCP `call_tool` shape | invariant | plan §4 |
| R-SINGLETON | `_client` singleton + respx interception, no cross-test leak | invariant | plan §3/§4 |
| R-LISTRULE | `list_tasks` scope-filter contract matches real `GET /tasks` | stated | plan §3 `asana_list_tasks`; analysis Tier 5 |
| R-NULLPATH | setParent / set_custom_field send explicit `null` to detach/clear | implied-essential | plan §3 + §6 risk notes |
| R-ERRENV | `_req` `errors[0].message` extraction matches Asana error bodies | invariant | plan §3 |
| R-WSGUARD | workspace-requiring tools fail loud when no workspace resolves | invariant | plan §3 `_workspace` |
| R-ARITY | every `_req` call site handles the `(payload, next_page)` tuple | invariant | plan §3 |

### End-to-End Trace Table

| req_id | trace | runtime/data evidence | holds? |
| --- | --- | --- | --- |
| R-REG | startup → `server.py` imports → `register_all_tools(mcp)` → `asana_tool.register_tools` → 67 `@mcp.tool()` | `server.py:10` invokes hub; grep `asana_` in tools/ (excl. new file) = 0 collisions; mcp 1.26.0 `ToolManager.add_tool` is first-wins+warn (no fatal) | yes |
| R-HARNESS | `await mcp.call_tool` → `Tool.run` → `convert_result` → `(content_list, structured)` → `[0][0].text` | `uv run pytest tests/test_notion_tool.py -q` → **34 passed**; identical `_r` shape | yes |
| R-SINGLETON | fixture patches `_client=None` → tool builds client w/ base_url → respx transport-mock intercepts | notion uses same pattern, 34 green; `patch` restores attr despite mid-test reassignment | yes |
| R-LISTRULE | `list_tasks(project, assignee, …)` → forwards all → `GET /tasks?project=..&assignee=..` | **Asana getTasks requires EXACTLY ONE of {project,section,tag} or {assignee+workspace}; combining → 400** (getTasks ref + n8n 400 report) | **NO** |
| R-NULLPATH | `set_task_parent(parent=None)` → `{"data":{"parent":null}}` | `_clean` applied to `params` only, never `data` (plan 121-128); setParter ref accepts null | yes |
| R-ERRENV | 4xx → `_req` reads `errors[0].message` | Asana Errors doc: all errors return top-level `errors[]` with `message` | yes |
| R-WSGUARD | list_tags/users/teams/webhooks/custom_fields/search/create_* → `_workspace()` before HTTP → raise if unset | spot-checked 8 sites all call `_workspace()` first | yes |
| R-ARITY | 67 sites: `payload,_=` / `payload,nxt=` / bare `await` (DELETE) | grep finds no `payload = await _req(` single-capture; 8 DELETE discard tuple (valid) | yes |

### Lens Coverage Matrix (condensed; only non-trivial cells shown)

| req_id | lens | status | evidence |
| --- | --- | --- | --- |
| R-LISTRULE | 1 cross-feature contract | **gap found** | tool advertises (docstring) combinable scopes; real API rejects combo with 400 |
| R-LISTRULE | 2 data-reality vs requirement | **gap found** | `test_list_tasks_combined_scopes` mocks 200, asserts project+assignee both sent — greens on a combination the live API 400s |
| R-LISTRULE | 6 silent-wrong detection | **gap found** | misleading green test = false confidence that combined scopes are supported |
| R-REG | 1 / 5 | checked | no collision; fail-mode is overwrite (informational only) |
| R-HARNESS, R-SINGLETON | 4 | checked | empirical pytest green |
| R-NULLPATH | 5 producer/consumer symmetry | checked | `_clean` never touches `data`; null preserved |
| R-ERRENV | 1 | checked | uniform Asana error envelope |
| R-WSGUARD | 6/7 config dependence | checked | fail-loud via `_workspace()` |
| R-ARITY | 5 | checked | no arity mismatch |
| all others | 2,3,8 | checked | no gap |

### Blocker Gap Ledger

| gap_id | severity | req_id | lens | evidence (both sides) | why it breaks the requirement | planned fix | closure evidence | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| SGAP-001 | blocker | R-LISTRULE | 1/2/6 | **Producer (Asana):** `GET /tasks` requires exactly one of {project,section,tag} or {assignee+workspace}; combining → 400 (getTasks ref; n8n forum 400). **Consumer (plan):** `asana_list_tasks` docstring says "Scopes may be combined; this does NOT enforce a single choice"; `test_list_tasks_combined_scopes` mocks 200 and asserts project+assignee both sent. | The plan encodes a factually-false API contract (introduced when verify-analysis changed the original XOR to "combinable"). The combined-scope test greens on behavior the live API rejects → false confidence; the tool advertises an unsupported capability. | (a) analysis.md: correct the container rule to **mutually exclusive** (exactly one of project/section/tag, or assignee+workspace). (b) plan `asana_list_tasks`: enforce exactly-one (raise ToolError on 0 or >1 scope selector); assignee still requires workspace. (c) plan tests: replace `test_list_tasks_combined_scopes` with `test_list_tasks_rejects_multiple_scopes` asserting ToolError; keep single-scope + assignee+workspace tests. | — | open |

### Cleanup / Known-Limitation List
- K-1 (informational): mcp 1.26.0 `ToolManager.add_tool` silently overwrites on duplicate tool names (warn-only, not fatal). No collision exists today (all 67 names unique, `asana_`-prefixed). No action.

---

## Cycle 1 Plan

Map SGAP-001 → exact edits:
1. **analysis.md** Tier 5 `asana_list_tasks` "Container rule" → rewrite to mutually-exclusive (exactly one scope; assignee requires workspace; combining returns 400). Also fix the "not XOR" wording in Testing scenario 2.
2. **plan.md** `asana_list_tasks` implementation → add exactly-one-scope validation: count specified selectors among {project_gid, section_gid, tag_gid, assignee}; raise ToolError if 0 or >1. Update docstring to state mutual exclusivity. (assignee→workspace requirement retained.)
3. **plan.md** tests → replace `test_list_tasks_combined_scopes` with `test_list_tasks_rejects_multiple_scopes` (asserts ToolError, no HTTP). Keep `test_list_tasks_requires_scope` and `test_list_tasks_assignee_adds_workspace`.
4. **plan.coverage-audit.md** R-LISTRULE acceptance criterion note stays valid (single-scope + rejects-multiple).

Document edits only; no runtime code touched outside the plan's own code block.

## Cycle 1 Edits

- **plan.md `asana_list_tasks`:** added exactly-one-scope guard — `chosen = sum([bool(project), bool(section), bool(tag), bool(assignee)])`; raise on `chosen == 0` ("exactly one …") and on `chosen > 1` ("only one task scope …"). Docstring rewritten to state mutual exclusivity + the 400-on-combine reality.
- **plan.md tests:** replaced `test_list_tasks_combined_scopes` (mocked-200, asserted combined params) with `test_list_tasks_rejects_multiple_scopes` (`pytest.raises(match="only one task scope")`, no HTTP). Retained `test_list_tasks_requires_scope` and `test_list_tasks_assignee_adds_workspace`.
- **analysis.md:** Tier 5 container rule → mutually-exclusive (exactly one; combine→400); Testing scenario 2 reworded to "exactly one scope, raises on 0 and >1".
- **plan.coverage-audit.md:** updated R-LISTRULE / R-TEST.8 evidence to the renamed test.

## Cycle 1 Validation

- Re-traced R-LISTRULE against the corrected contract:
  - Single scope (`project_gid="p1"`) → `chosen == 1` → params built → `GET /tasks?project=p1` → valid per Asana. ✓
  - `assignee="me"` → `chosen == 1` → `workspace` added via `_workspace()` → `GET /tasks?assignee=me&workspace=111` → valid. ✓
  - `assignee="me", project_gid="p1"` → `chosen == 2` → raises ToolError BEFORE any HTTP → matches the real-API rejection, fail-fast not 400-round-trip. ✓ (`test_list_tasks_rejects_multiple_scopes` asserts this with no respx route.)
  - No scope → `chosen == 0` → raises. ✓ (`test_list_tasks_requires_scope`.)
- Post-edit new-gap pass:
  - The guard uses only the four scope selectors; `completed_since`/`modified_since`/`limit`/`offset` remain free modifiers — no new over-restriction. ✓
  - No new interop asymmetry: the consumer (tool) now matches the producer (Asana) contract exactly (one scope).
  - `test_list_tasks_rejects_multiple_scopes` no longer needs a respx mock; it relies on the guard raising — consistent with other validation tests (`test_create_story_requires_text`, `test_update_project_requires_field`) that also raise pre-HTTP. ✓
  - Test count unaffected (1 replaced 1).
- All other requirement traces (R-REG, R-HARNESS, R-SINGLETON, R-NULLPATH, R-ERRENV, R-WSGUARD, R-ARITY) re-confirmed unchanged and holding.

---

## Cycle 2 Assessment

Fresh full pass over the addressed requirement set against the edited plan.

- **Lens 1 cross-feature contract:** R-LISTRULE consumer now enforces exactly-one, matching Asana's producer constraint. No remaining producer/consumer contract mismatch across the 67 tools (envelope, GIDs, `resource_subtype`, multipart parent/file, null-detach all symmetric).
- **Lens 2 data-reality:** no requirement depends on a stored field that is constant/defaulted; `task_counts` opt_fields defaults are valid field names; error bodies uniformly carry `errors[].message`.
- **Lens 3 intent vs mechanism:** `list_tasks` mechanism now serves the intent (scope a task list) AND the real API rule. `set_*` null paths serve "clear/detach" intent.
- **Lens 4 e2e trace:** every trace row holds (table above; R-LISTRULE row updated to NO→YES).
- **Lens 5 producer/consumer symmetry:** `_clean` never touches `data` (nulls preserved); `_req` tuple consumed correctly at all 67 sites.
- **Lens 6 silent-inert/wrong:** the one silent-wrong vector (misleading green combined-scope test) is removed; all ≥400 paths raise; no swallowed errors.
- **Lens 7 config dependence:** workspace-requiring tools fail loud via `_workspace()`.
- **Lens 8 scope-vs-usage:** tools hook the actual Asana endpoints exercised by callers; no dead path.

**Open blockers: 0.** No edits this cycle.

## Final Convergence Check

### Final Readiness Proof

| req_id | satisfied end-to-end? | evidence |
| --- | --- | --- |
| R-REG | yes | `server.py:10` runs hub; 0 name collisions; registration line added |
| R-HARNESS | yes | `uv run pytest tests/test_notion_tool.py` → 34 passed; identical helper shape |
| R-SINGLETON | yes | respx transport-mock intercepts base_url client; `patch` restores `_client`; notion precedent green |
| R-LISTRULE | yes | exactly-one guard matches Asana getTasks; `test_list_tasks_rejects_multiple_scopes` + single-scope + assignee+workspace tests |
| R-NULLPATH | yes | `_clean` excludes `data`; `{"data":{"parent":null}}` sent; setParent accepts null |
| R-ERRENV | yes | uniform Asana `errors[].message` envelope; 400/402/404 tests assert messages |
| R-WSGUARD | yes | all workspace tools call `_workspace()` pre-HTTP; `test_missing_default_workspace` |
| R-ARITY | yes | no `payload = await _req(` single-capture; DELETEs discard tuple validly |

**Ledger status:** SGAP-001 closed. Zero open blockers. K-1 recorded as informational known-limitation (no collision today).

**CONVERGED (depth).** Every addressed requirement is traced to confirming evidence that it holds end-to-end against the real Asana API, the installed MCP/httpx/respx runtime, and the sibling tool-module hub. The one real interop defect (a false "combinable scopes" contract that greened on API-rejected behavior) is corrected to the real exactly-one rule with a fail-fast guard and an honest test.

