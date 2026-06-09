Verify and harden the plan produced in this conversation through an iterative verify-critic-fix loop until no actionable findings remain.

## WHAT THIS COMMAND DOES

You will run up to 10 iterations of: verify the plan for gaps and accuracy issues, pass findings through a critic for relevance filtering, then update the plan to address all actionable findings. Each iteration works on the updated plan from the prior cycle, so verification depth compounds — early iterations catch structural gaps, later iterations catch subtler issues exposed by the fixes.

**Convergence target:** The loop ends when the critic classifies ALL findings as DISMISS or ACKNOWLEDGE — zero FIX NOW, zero IMPLEMENT LATER.

## PREREQUISITES

This command operates on a plan that exists in the current conversation context. The plan may be:
- A plan produced in Plan mode (the most common case)
- An implementation plan, architecture plan, migration plan, or any structured plan artifact
- A plan written to a file (e.g., `implementation_plan.md`, `code_plan.md`)

If no plan is visible in the conversation context, ask the user to identify which plan to verify before proceeding.

## ITERATION PROTOCOL

For each iteration (starting at 1):

### Step 1: Plan Verification (delegate to a verifier subagent)

Spawn a verifier subagent with the current plan. The verifier's job is to find problems with evidence — it does NOT fix anything and does NOT judge severity.

The verifier MUST check:

1. **Reference Accuracy** — Every file path, method signature, entity property, or service reference mentioned in the plan:
   - Does the referenced file exist on disk?
   - Does the method/function exist with the claimed signature?
   - Do entity properties match actual model definitions?
   - Are line numbers within range?
   - Flag any assumption language ("should exist", "likely at", "probably")

2. **Completeness & Gaps** — Is anything missing from the plan?
   - Are all requirements from the task decomposed into plan sections?
   - Is error handling addressed (not just the happy path)?
   - Are there missing registrations, imports, migrations, or config entries?
   - Are there placeholder entries (TBD, TODO, "to be determined")?

3. **Internal Consistency** — Does the plan contradict itself?
   - Does a file listed as "New" already exist? Does a "Modified" file actually exist?
   - Do cross-references between plan sections align?
   - Are patterns/approaches consistent throughout?

4. **Hallucination Detection** — Are claims in the plan actually true?
   - Do referenced patterns actually exist in the codebase?
   - Are technology claims accurate (API signatures, framework conventions)?
   - Are architecture decisions grounded in actual code, not invented abstractions?

**Verifier output format:** A structured findings list where each finding has:
- What is wrong (specific claim vs reality)
- Where in the plan (section/line reference)
- Evidence (what the verifier found when checking — file paths, actual signatures, etc.)

**Critical verifier rule:** Report everything found. Do not self-filter. Do not judge whether a finding is "minor" or "blocking" — that is the critic's job.

### Step 2: Critic Evaluation (delegate to a critic subagent)

Pass the verifier's findings to a critic subagent for relevance filtering. The critic applies 4 checks to each finding:

1. **Relevance** — Is this finding about something the plan actually needs to address?
2. **Evidence** — Did the verifier provide concrete proof, or is the finding speculative?
3. **Impact** — Would ignoring this cause the plan to produce incorrect, incomplete, or failing results?
4. **Actionability** — Can the plan be concretely updated to address this?

The critic categorizes each finding into one of four buckets:

| Bucket | Meaning | What happens |
|--------|---------|--------------|
| **FIX NOW** | Verified, impactful, actionable | Plan gets updated this iteration |
| **IMPLEMENT LATER** | Valid but lower priority | **Promoted to FIX NOW** — plan gets updated this iteration |
| **ACKNOWLEDGE** | True observation but acceptable | No plan change needed |
| **DISMISS** | False positive, speculative, or irrelevant | No plan change needed |

**IMPLEMENT LATER promotion rule:** Nothing gets deferred. IMPLEMENT LATER findings are treated identically to FIX NOW — the plan is updated to include them immediately. The distinction only exists so the critic can express confidence levels, but both result in plan updates.

### Step 3: Convergence Check

Count actionable findings: FIX NOW + IMPLEMENT LATER.

- If **zero actionable** → the plan has converged. Report the final summary and stop.
- If **actionable findings exist** → proceed to Step 4.

### Step 4: Update the Plan

For each FIX NOW and IMPLEMENT LATER finding from the critic:

1. Read the specific plan section that needs updating
2. Make the targeted correction:
   - **Wrong reference:** Replace with the verified correct reference (file path, method signature, etc.)
   - **Missing section:** Add the missing content (error handling, edge cases, registrations, etc.)
   - **Hallucination:** Remove or replace the hallucinated claim with verified facts
   - **Incomplete coverage:** Expand the plan section to fully address the requirement
   - **Internal inconsistency:** Resolve the contradiction with the correct information
3. Preserve all plan sections that passed verification — do not restructure what works

**Rules:**
- Fix only what the critic validated — do not speculatively improve unrelated sections
- When adding missing content, verify new claims against the codebase before including them
- Maintain the plan's existing structure and format
- After all updates, present the updated plan sections (or the full updated plan if changes are extensive)

### Step 5: Log and Continue

Log the iteration result:
```
--- Plan Verification Iteration N ---
Findings from verifier: X
FIX NOW: Y (plan updated)
IMPLEMENT LATER: Z (promoted to FIX NOW, plan updated)
ACKNOWLEDGE: A (no change)
DISMISS: B (no change)
```

Increment the iteration counter and return to Step 1. The verifier now checks the UPDATED plan — this is the compounding effect. Fixes from this iteration may expose new issues or resolve cascading problems.

## ITERATION CAP

- **Primary cap:** 10 iterations.
- If after 10 iterations there are still actionable findings, present them and ask: "There are still N actionable findings after 10 iterations. Should I continue for up to 10 more?"
- If the user approves, reset the counter and continue.

## FINAL REPORT

When the loop ends (convergence or user stop), produce:

```
## Plan Verification Summary

**Iterations completed:** N
**Total findings reviewed:** X
**Total plan updates applied:** Y
**Convergence:** YES/NO

### Iteration Log
| # | Verifier Findings | FIX NOW | IMPL LATER | ACK | DISMISS |
|---|-------------------|---------|------------|-----|---------|
| 1 | ...               | ...     | ...        | ... | ...     |
| 2 | ...               | ...     | ...        | ... | ...     |

### Key Changes Made to Plan
1. [What was changed and why]
2. [What was changed and why]

### Remaining (if not converged)
1. [Finding] — [why it wasn't resolved]
```

## CRITICAL RULES

1. **The verifier checks claims against the actual codebase.** It must read files, grep for signatures, and verify paths — not just reason about the plan text in isolation.
2. **The verifier does not self-filter.** Every issue found gets reported, no matter how minor it seems. The critic decides what matters.
3. **The critic is the authority on actionability.** Do not override DISMISS/ACKNOWLEDGE decisions. Do not skip FIX NOW/IMPLEMENT LATER decisions.
4. **IMPLEMENT LATER = FIX NOW.** Nothing gets deferred to "later" — if it's valid and actionable, update the plan now.
5. **Each iteration verifies the updated plan**, not the original. This catches regressions from prior fixes and validates that corrections are accurate.
6. **Do not gold-plate.** The goal is plan accuracy and completeness for the task at hand. Do not expand scope, add features, or optimize beyond what the task requires.
7. **Preserve working sections.** When updating the plan, only modify sections with findings. Do not restructure or rewrite sections that passed verification.
