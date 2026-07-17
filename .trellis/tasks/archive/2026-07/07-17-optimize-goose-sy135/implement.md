# Implementation Plan

## 1. Capture Regression Evidence

- Add a concise task-local failure analysis with the observed Goose stage attempts, image comparison, missing files, and font warnings.
- Preserve external Downloads data and workspace run outputs as test inputs only; do not track them.

## 2. Improve MCP Feedback And Artifact Contracts

- Add bounded process diagnostics and recoverable error propagation in `agent/mcp/chartpilot_mcp.py`.
- Return diagnostics on failed and successful stage calls.
- Reject render commits when stderr reports missing glyphs or textual artifacts contain replacement characters.
- Add optional declared analysis artifacts with path/name/size validation, atomic commit, and manifest entries.
- Extend `agent/tests/test_adaptive_bridge.py` for each new contract and regression.

## 3. Improve Agent Guidance And Templates

- Update `skills/chartpilot-run-python/SKILL.md` with inline path invariants, visual-grain reasoning, actual-image review, and artifact reconciliation.
- Update `references/adaptive-task-contract.md` for diagnostics and optional artifacts.
- Refine `inspect_csv.py` and `analyze_csv.py` comments/metadata so prompt semantics and visual grain are explicit without hard-coded fields.
- Refine `render_chart.py` to configure system CJK fonts globally and mark `output_dir` as write-only.
- Regenerate or update `agents/openai.yaml` only if the repository's Skill workflow requires it.

## 4. Automated Verification

- Run Python compile and all Agent unit/regression tests.
- Run unchanged templates and the synthetic changed-schema/threshold regression.
- Run MCP stdio enumeration and assert exactly two tools.
- Run Skill validation and removed deterministic-name checks.
- Run the bundled runtime checks; do not alter dependencies unless a missing package is proven.

## 5. SY135 Acceptance

- Run the external prompt and raw CSV through the updated adaptive path using a fresh task ID.
- Assert 59,278 source rows, 6,523 machines, exact per-gear totals, 96 above 25%, and 0 above 50%.
- Confirm declared auxiliary CSVs exist and match the summary/manifest.
- Inspect the generated PNG directly for Chinese readability, meaningful aggregated visual grain, threshold semantics, overlap, and nonblank coordinated regions.
- Prefer an actual Goose rerun. If provider/network state prevents it, run the equivalent Agent-authored scripts through the same two MCP tools and report the residual Goose-level gap explicitly.

## 6. Final Quality Gate

- Load `trellis-check` and execute project quality guidance.
- Review `git diff` for accidental workspace/runtime/external data inclusion.
- Update Trellis specs if the new diagnostics/artifact/readability contracts are project-wide conventions.
- Present the final evidence and obtain normal commit/push instructions; do not push implicitly.

## Risky Files And Rollback Points

- `agent/mcp/chartpilot_mcp.py`: shared execution boundary; keep schema additions optional and test atomic commit behavior.
- `skills/chartpilot-run-python/SKILL.md`: avoid turning visualization advice into a fixed chart recipe.
- `skills/chartpilot-run-python/assets/templates/render_chart.py`: verify global font configuration across all text elements.
- No runtime mutation is planned; stop and revisit design before adding packages.
