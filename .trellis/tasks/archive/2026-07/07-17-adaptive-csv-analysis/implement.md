# Adaptive-Only CSV Analysis Implementation Plan

## 1. Remove Deterministic Routes

- Remove the three deterministic MCP registrations and their bridge entry paths.
- Remove the profile/analyze/render Skill directories, runners, contracts, tests, and routing
  documentation after migrating any neutral helper that the adaptive bridge genuinely needs.
- Update Skill staging, MCP enumeration, release inventory, and smoke tests to expect one product
  Skill and two adaptive tools.

## 2. Capture Reference Expectations

- Add aggregate-only SY135 expectations and an opt-in runner accepting the external case root.
- Add an anonymized fixture with different columns and thresholds.
- Define PNG checks for signature, dimensions, foreground ratio, two populated regions, CJK font,
  and semantic labels.

## 3. Add Compact Task Templates

- Add inspect, analysis, and render templates under
  `skills/chartpilot-run-python/assets/templates/`.
- Make them import-safe, `--context` driven, editable, and free of case-specific logic.
- Add template contract tests using bundled WinPython.

## 4. Implement The Adaptive MCP Surface

- Add prompt-aware preparation with bounded request decoding, atomic request/context writes,
  source hash/metadata, runtime inventory, and template return values.
- Add task-source execution with direct bundled interpreter invocation, timeouts, bounded output,
  and append-only attempt records.
- Add stage validators and builders for inspection, adaptive analysis/result manifests, adaptive
  rendering/chart manifests, and nonblank PNGs.
- Keep environment sanitization and portable interpreter resolution; remove business-operation
  allowlists and deterministic tool dispatch.

## 5. Refocus The Remaining Skill

- Rewrite `chartpilot-run-python` as the sole adaptive prompt-plus-CSV workflow Skill.
- Add `references/adaptive-task-contract.md`; retain only applicable portable runtime guidance.
- Regenerate `agents/openai.yaml` from the revised Skill.
- Validate the Skill with `quick_validate.py`.

## 6. Packaging And Documentation

- Package the single adaptive Skill, templates, bridge, runtime, and required licenses.
- Remove deterministic tool/Skill claims from README files, product requirements, Skill
  development notes, deployment documentation, and release checks.
- Update Trellis runtime guidelines to document adaptive-only execution and the lack of sandbox.

## 7. Validation

Run in this order:

1. Python compile and unit tests for task preparation, execution records, and artifact validators.
2. MCP initialize and exact enumeration of the two adaptive tools.
3. Assert removed tool names and removed Skill directories are absent from source staging and ZIP.
4. Execute unchanged templates with bundled WinPython on the anonymized fixture.
5. Customize templates for the synthetic prompt and produce a nonblank multi-panel PNG.
6. Run the original SY135 case from its external root; assert 6,523 machines, exact gear totals,
   96 above 25%, zero above 50%, and semantic two-panel chart structure.
7. Run `pip check`, required imports, runtime lock/wheelhouse/license checks, Skill validation,
   PowerShell parsing/ASCII checks, and release packaging audit.
8. Do not run the previously excluded release relocation test under Chinese/space paths.

## Risk And Rollback Points

- Do not mutate the runtime unless a missing reusable dependency is proven and fully locked.
- Write completion manifests last so failed generated code cannot appear successful.
- Do not stage external case data, manual artifacts, Downloads paths, generated runtime, or
  workspace outputs.
- Verify there are no stale deterministic names in Skills, MCP tool lists, docs, tests, release
  ZIP, or staged Goose config before completion.
- Roll back through the task's commits if adaptive-only routing fails; do not retain hidden legacy
  routes.
