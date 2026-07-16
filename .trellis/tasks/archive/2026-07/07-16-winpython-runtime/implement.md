# WinPython Runtime Implementation Plan

## Preconditions

- User-selected dependency scope: current CSV MVP only.
- Selected base: `WinPython64-3.13.13.0dot.zip` from release
  `17.4.20260511final`.
- Run implementation in Trellis Phase 2 only after this PRD/design/plan review is approved and
  `task.py start` changes the task status to `in_progress`.
- Before editing project files, load `trellis-before-dev`; before creating the new Skill, follow
  `skill-creator` including `init_skill.py`, `openai.yaml` generation and `quick_validate.py`.

## Implementation Checklist

- [x] 1. Add source-controlled runtime acquisition and dependency contracts.
  - Add `runtime.lock.json` with upstream URL, bytes, SHA-256, Python/architecture expectations,
    canonical interpreter path and environment defaults.
  - Keep `requirements.txt` as direct pins.
  - Add the generated Windows x64 CPython 3.13 `requirements.runtime.lock.txt` with hashes for
    all direct and transitive wheels.

- [x] 2. Extend generated-output exclusions without disturbing existing user ignores.
  - Ignore `runtime/`, WinPython archives and runtime staging/cache files.
  - Preserve existing `wheelhouse/`, `build/` and `dist/` exclusions.

- [x] 3. Implement the runtime lock-refresh workflow.
  - Create `scripts/runtime/update-lock.ps1`.
  - Download the fixed WinPython ZIP when absent and verify size/SHA-256.
  - Extract a temporary WinPython tree and use only its Python/pip.
  - Resolve only binary Windows x64 CPython 3.13 wheels from `requirements.txt`.
  - Compute every wheel SHA-256 and write a deterministic pip-compatible lock.
  - Fail on source distributions, wrong ABI/architecture or a direct dependency not represented
    in the generated lock.

- [x] 4. Implement transactional runtime assembly.
  - Create `scripts/runtime/build-runtime.ps1`.
  - Consume the committed lock, populate/verify `wheelhouse/`, extract into staging and install
    with `--no-index --find-links --require-hashes`.
  - Normalize the final interpreter to `runtime/winpython/python/python.exe`.
  - Generate metadata and license inventory with the staged interpreter.
  - Run staged health checks before replacing an existing runtime.
  - Restore the previous runtime if final placement fails.

- [x] 5. Implement metadata and verification helpers.
  - Create `scripts/runtime/write-runtime-metadata.py` for installed distributions, wheel hashes,
    interpreter facts and third-party license metadata.
  - Create `scripts/runtime/test-runtime.ps1` for manifest validation, `pip check`, imports,
    CLI `--help`, unit tests and an end-to-end CSV-to-PNG smoke test.
  - Ensure helpers produce structural errors without leaking local data or environment secrets.

- [x] 6. Implement release packaging.
  - Create `scripts/runtime/package-release.ps1` with an explicit include/exclude manifest.
  - Produce a ZIP under `dist/` only after runtime tests pass.

- [x] 7. Create the `chartpilot-run-python` Skill.
  - Initialize it under `skills/` with `SKILL.md`, `agents/openai.yaml` and
    `references/runtime-contract.md`.
  - Define triggers for Python authoring, runtime resolution and local execution.
  - Document direct process-array invocation, environment sanitization, task-local code/output,
    audit capture and the no-system-Python rule.
  - Distinguish deterministic business skills from general generated-code execution and state
    that the Agent base owns hard sandboxing.
  - Validate the skill with `quick_validate.py` and realistic local invocation examples.

- [x] 8. Update the three existing Skill contracts.
  - Replace bare `python` examples in all three `SKILL.md` files and relevant references with the
    bundled-runtime invocation contract.
  - Link to `chartpilot-run-python` only where runtime details are needed.
  - Preserve all current input/output, hash, path, atomicity and no-arbitrary-code constraints.

- [x] 9. Update product and deployment documentation.
  - Update README and README.zh-CN for CPython 3.13, build/use commands and no-system-Python rule.
  - Rewrite the relevant Windows offline deployment sections around the selected WinPython asset,
    dependency lock/wheelhouse flow, release packaging and clean-host acceptance.
  - Reconcile the product specification's generated-code requirement with the fixed business
    runners and new runtime Skill boundary.

- [x] 10. Download, assemble and verify the real runtime.
  - Fetch the official ZIP and wheels through the implemented scripts.
  - Review the generated dependency-lock diff before treating it as final.
  - Build `runtime/`, generate supply-chain records and run the full verification suite.
  - Build the distribution ZIP and verify its expected file inventory.

- [x] 11. Run the Trellis quality and finish gates.
  - Load and run `trellis-check` after implementation.
  - Review `git diff` for accidental binary/cache additions and unrelated changes.
  - Update Trellis specs only if the implementation establishes reusable project conventions.
  - Present verification evidence and remaining clean-VM/manual acceptance work before commit.

## Validation Commands

Planned commands, subject to final script parameter names:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

Direct bundled-interpreter checks:

```powershell
.\runtime\winpython\python\python.exe -I -c "import sys; print(sys.version); print(sys.executable)"
.\runtime\winpython\python\python.exe -I -m pip check
.\runtime\winpython\python\python.exe -I -c "import pandas, matplotlib, PIL"
.\runtime\winpython\python\python.exe -I -m unittest discover -s .\skills\chartpilot-analyze-data\tests -v
```

The runtime test script must additionally execute all three CLI `--help` paths and a real
profile -> analysis -> render fixture inside an authorized workspace root.

## Risk And Rollback Points

- Upstream asset mismatch: stop before extraction; do not replace cached verified assets.
- Resolver drift: only `update-lock.ps1` may change the dependency lock; review the exact wheel
  list and hashes before building a release.
- WinPython layout drift: validate the extracted single-root layout and exact interpreter path;
  fail rather than guessing across multiple candidates.
- Runtime replacement: build and test in staging, back up the prior generated runtime, restore on
  placement failure.
- Skill regression: compare changed contracts against the current stage ownership and structured
  error rules before accepting documentation updates.
- Packaging omission: inspect the ZIP inventory against the explicit release file list.

## Review Gate

Before `task.py start`, confirm that the PRD, technical design and this execution plan correctly
represent the desired deliverable. Implementation must not begin while the task remains in
`planning`.
