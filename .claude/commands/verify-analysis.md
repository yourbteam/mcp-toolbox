Verify and harden an analysis produced in this conversation through an iterative verify-critic-fix loop until no actionable findings remain.

## WHAT THIS COMMAND DOES

You will run up to 10 iterations of: verify the analysis for accuracy and missed gaps, pass findings through a critic for relevance filtering, then update the analysis to address all actionable findings. Each iteration works on the updated analysis from the prior cycle, so verification depth compounds.

**Convergence target:** The loop ends when the critic classifies ALL findings as DISMISS or ACKNOWLEDGE — zero FIX NOW, zero IMPLEMENT LATER.

## PREREQUISITES

This command operates on an analysis that exists in the current conversation context. An analysis is any structured evaluation that makes claims about code, personas, configurations, architecture, or processes — for example:
- A KPI gap analysis of agent personas
- A security audit of a module
- A dependency analysis
- A comparison of approaches or trade-offs
- A codebase health assessment

The key distinction from `/verify-plan`: a plan describes *what to build*; an analysis describes *what is*. Verification of an analysis checks whether its observations and conclusions are factually correct and complete — not whether it would produce working code.

If no analysis is visible in the conversation context, ask the user to identify which analysis to verify before proceeding.

## ITERATION PROTOCOL

For each iteration (starting at 1):

### Step 1: Analysis Verification (delegate to a verifier subagent)

Spawn a verifier subagent with the current analysis. The verifier's job is to find factual errors, missed gaps, and unsupported conclusions — it does NOT fix anything and does NOT judge severity.

The verifier MUST check:

1. **Factual Accuracy** — Every claim the analysis makes about code, files, or behavior:
   - Does the referenced file/function/section actually exist?
   - Does the code actually behave as the analysis claims?
   - Are line numbers, method signatures, and config values correct?
   - Are quotes from source files accurate?
   - Flag any claim that cannot be verified by reading the codebase

2. **Completeness** — Did the analysis miss anything within its stated scope?
   - Are there relevant code paths, files, or configurations not examined?
   - Are there edge cases or failure modes not considered?
   - Does the analysis cover the full scope it claims to cover, or does it silently skip areas?
   - Are there downstream effects or cross-file dependencies the analysis overlooked?

3. **Conclusion Validity** — Do the analysis's conclusions follow from its evidence?
   - Is a gap called "no gap" actually covered, or did the analysis miss it?
   - Is a gap called "real gap" actually a gap, or is it already handled elsewhere?
   - Are severity assessments (high/medium/low) supported by concrete impact evidence?
   - Are "adequate" ratings genuinely adequate, or did the analysis give a pass too easily?

4. **Scope Consistency** — Does the analysis stay true to its own scope?
   - Does it apply criteria consistently across all items it evaluates?
   - Did it evaluate every item at the same depth, or rush through some?
   - Are comparisons between items fair (same criteria applied to each)?

**Verifier output format:** A structured findings list where each finding has:
- What is wrong or missing (specific claim vs reality)
- Where in the analysis (which section, which item being evaluated)
- Evidence (what the verifier found when checking — file contents, actual behavior, etc.)

**Critical verifier rule:** Report everything found. Do not self-filter. Do not judge whether a finding is "minor" or "blocking" — that is the critic's job.

### Step 2: Critic Evaluation (delegate to a critic subagent)

Pass the verifier's findings to a critic subagent for relevance filtering. The critic applies 4 checks to each finding:

1. **Relevance** — Is this finding about something the analysis actually needs to address?
2. **Evidence** — Did the verifier provide concrete proof, or is the finding speculative?
3. **Impact** — Would ignoring this leave a factual error, missed gap, or wrong conclusion in the analysis?
4. **Actionability** — Can the analysis be concretely updated to address this?

The critic categorizes each finding into one of four buckets:

| Bucket | Meaning | What happens |
|--------|---------|--------------|
| **FIX NOW** | Verified, impactful, actionable | Analysis gets updated this iteration |
| **IMPLEMENT LATER** | Valid but lower priority | **Promoted to FIX NOW** — analysis gets updated this iteration |
| **ACKNOWLEDGE** | True observation but acceptable | No analysis change needed |
| **DISMISS** | False positive, speculative, or irrelevant | No analysis change needed |

**IMPLEMENT LATER promotion rule:** Nothing gets deferred. Both FIX NOW and IMPLEMENT LATER result in analysis updates.

**Important:** The critic must independently verify claims by reading the actual files — not just trust the verifier's description.

### Step 3: Convergence Check

Count actionable findings: FIX NOW + IMPLEMENT LATER.

- If **zero actionable** → the analysis has converged. Report the final summary and stop.
- If **actionable findings exist** → proceed to Step 4.

### Step 4: Update the Analysis

For each FIX NOW and IMPLEMENT LATER finding from the critic:

1. Read the specific source files to get the current truth
2. Make the targeted correction to the analysis:
   - **Factual error:** Correct the claim to match reality
   - **Missed gap:** Add the gap with proper evidence and severity
   - **Wrong conclusion:** Revise the conclusion to match the evidence
   - **Inconsistent depth:** Expand the under-examined section to match the depth of others
   - **False "no gap":** Reclassify as a real gap with evidence
   - **False "real gap":** Reclassify as adequate with evidence for why it's covered
3. Preserve all analysis sections that passed verification

**Rules:**
- Fix only what the critic validated — do not speculatively expand the analysis scope
- When adding missed gaps, verify the gap claim against actual code before including it
- Maintain the analysis's existing structure and format
- After all updates, present the updated sections to the user

### Step 5: Log and Continue

Log the iteration result:
```
--- Analysis Verification Iteration N ---
Findings from verifier: X
FIX NOW: Y (analysis updated)
IMPLEMENT LATER: Z (promoted to FIX NOW, analysis updated)
ACKNOWLEDGE: A (no change)
DISMISS: B (no change)
```

Increment the iteration counter and return to Step 1.

## ITERATION CAP

- **Primary cap:** 10 iterations.
- If after 10 iterations there are still actionable findings, present them and ask: "There are still N actionable findings after 10 iterations. Should I continue for up to 10 more?"
- If the user approves, reset the counter and continue.

## FINAL REPORT

When the loop ends (convergence or user stop), produce:

```
## Analysis Verification Summary

**Iterations completed:** N
**Total findings reviewed:** X
**Total analysis updates applied:** Y
**Convergence:** YES/NO

### Iteration Log
| # | Verifier Findings | FIX NOW | IMPL LATER | ACK | DISMISS |
|---|-------------------|---------|------------|-----|---------|
| 1 | ...               | ...     | ...        | ... | ...     |
| 2 | ...               | ...     | ...        | ... | ...     |

### Key Changes Made to Analysis
1. [What was changed and why]
2. [What was changed and why]

### Remaining (if not converged)
1. [Finding] — [why it wasn't resolved]
```

## CRITICAL RULES

1. **The verifier checks claims against the actual codebase.** It must read files, grep for patterns, and verify references — not just reason about the analysis text in isolation.
2. **The verifier does not self-filter.** Every issue found gets reported. The critic decides what matters.
3. **The critic is the authority on actionability.** Do not override DISMISS/ACKNOWLEDGE decisions. Do not skip FIX NOW/IMPLEMENT LATER decisions.
4. **IMPLEMENT LATER = FIX NOW.** Nothing gets deferred.
5. **Each iteration verifies the updated analysis**, not the original. This catches regressions and validates corrections.
6. **Do not expand scope.** The goal is accuracy and completeness within the analysis's stated scope. Do not add new KPIs, new evaluation targets, or new criteria beyond what the analysis set out to examine.
7. **Preserve working sections.** Only modify sections with findings. Do not restructure or rewrite sections that passed verification.
8. **Reviewer and fixer must be separate.** Always delegate Step 1 to a verifier subagent. The main conversation context (which performs fixes in Step 4) must never also perform the verification, to avoid self-consistency bias.
