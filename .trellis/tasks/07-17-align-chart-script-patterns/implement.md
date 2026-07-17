# Implementation Plan

## 1. Add The Evidence-Backed Archetype

- Add `references/visual-archetypes.md` with the role-based match signature, disqualifiers,
  `group-risk-threshold-bubble` panel contract, generic code blueprint, and script-review checklist.
- Update `SKILL.md` so Agent planning selects an archetype before analysis code and render code must
  implement the declared plan.
- Keep a reasoned free-form fallback and avoid keyword, field-name, category-count, or threshold
  literals in reusable guidance.
- Regenerate `agents/openai.yaml` through the repository's Skill workflow if its prompt changes.

## 2. Make The Three Templates Support Auditable Planning

- Keep `inspect_csv.py` generic; refine notes only if needed to capture the semantic roles required
  for archetype matching.
- Expand `analyze_csv.py`'s generic `chart_intent` example with archetype, role map, panel plan,
  ordering, and annotation strategy without turning it into a risk-specific default.
- Refine `render_chart.py` comments/metadata so task code consumes `chart_intent` and reviews its
  source structure before running; unchanged behavior must remain a simple category comparison.
- Update `adaptive-task-contract.md` to document the advisory plan and analysis/render consistency.

## 3. Strengthen Script-Level Regression

- Update SY135 fixtures to declare and implement `group-risk-threshold-bubble` using dynamic group
  and threshold inputs.
- Update the anonymous changed-schema 20%/40% fixtures to use the same archetype with different
  field names and thresholds.
- Add focused assertions for archetype declaration, panel roles, group-risk aggregation, stacked
  composition, aggregate bubbles, and baseline/threshold references.
- Retain the unchanged-template test as the non-match/generic fallback control.
- Extend release checks so `visual-archetypes.md` exists in both packaged Skill copies.

## 4. Documentation And Specs

- Update README/Chinese workflow documentation and Skill development documentation where the
  Agent's chart-selection/review contract is described.
- Update the Trellis backend runtime/quality spec with the role-based archetype rule, source-level
  acceptance, generic fallback, and release inventory.
- Do not change dependency locks or runtime manifests unless implementation proves a missing
  package; none is expected.

## 5. Verification

- Run Python compile and focused Agent unit/regression tests.
- Run the unchanged templates and anonymous changed-schema/threshold regression.
- Run the external SY135 regression and assert exact counts plus script/chart-plan structure.
- Run Skill validation, removed-tool audits, `scripts/runtime/test-runtime.ps1`, and
  `scripts/agent/test-agent.ps1`.
- Stage the revised Skill into portable Goose, start a fresh task with the original prompt/CSV,
  and review `analysis_result.json`, `generated_chart.py`, execution records, and `chart.png`.
- The real script passes only when its primary code path implements stacked group/risk composition
  and aggregate group/risk bubbles with peer baseline/threshold references; a visually readable but
  structurally different script is a failed forward test.
- Do not run the excluded release-ZIP relocation test under Chinese/space paths.

## 6. Final Gate

- Load `trellis-check`; review cross-layer Skill source/staged/release copies and test evidence.
- Run `git diff --check` and ensure no runtime/workspace/external user data is tracked.
- Load `trellis-update-spec` for any durable chart-selection contract learned during implementation.
- Present work commits for approval; do not push implicitly.

## Risky Files And Rollback Points

- `skills/chartpilot-run-python/SKILL.md`: over-strong wording can force the archetype onto unrelated
  requests; preserve explicit match conditions and disqualifiers.
- `skills/chartpilot-run-python/references/visual-archetypes.md`: examples can accidentally hardcode
  business names/thresholds; use role placeholders throughout.
- `analyze_csv.py` / `render_chart.py`: unchanged templates must stay runnable and generic.
- Fixture/source assertions: avoid tests that pass from metadata alone while the plotting code no
  longer implements the declared marks.
- Real Goose provider behavior is nondeterministic; preserve the complete task directory and report
  source-level residuals rather than weakening acceptance.
