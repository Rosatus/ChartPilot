# Integrate portable Goose agent base

## Goal

Ship ChartPilot with a pinned, no-install Goose Desktop agent base that can discover the
ChartPilot Skills and execute the deterministic CSV profile, analysis, and chart pipeline
through a constrained local MCP extension using the bundled WinPython runtime.

## Background

- The user selected goose as the Agent base and supplied a local
  `Goose-win32-x64.zip` archive.
- The archive is the Goose `v1.43.0` Windows x64 Desktop, non-CUDA asset. It is
  `250045188` bytes with SHA-256
  `9014edf214395370d3de5a3dd7acc90cb2eace2abc5ee398266f7809b7726956`.
- Goose `v1.43.0` supports `GOOSE_PATH_ROOT`, stdio MCP extensions, the Summon extension,
  and Agent Skills under `.agents/skills/`.
- ChartPilot already has a pinned WinPython runtime and four Skills. Its deterministic
  business CLIs must remain the source of factual CSV processing.
- Goose and WinPython are portable runtimes, not a Windows operating-system sandbox.

## Requirements

### R1. Pinned Goose distribution

- Add a machine-readable Goose lock recording repository, release, asset URL, byte size,
  SHA-256, Windows x64 architecture, non-CUDA variant, expected version, and entrypoints.
- Build from either the verified user-supplied archive or the locked upstream URL.
- Reject an archive with a wrong size, hash, unsafe ZIP path, unexpected root layout, or
  missing Desktop/CLI entrypoint.
- Keep downloaded archives and extracted Goose binaries generated and out of Git.

### R2. Portable launch contract

- Provide a root-level launcher suitable for normal Windows use without system Python,
  Node.js, Rust, CUDA, or administrator privileges.
- Resolve all bundled paths relative to the launcher, never through `PATH`.
- Set `GOOSE_PATH_ROOT` to a writable ChartPilot workspace location and set
  `CHARTPILOT_ROOT` to the trusted install root before starting Goose.
- Seed config without overwriting later user Provider settings or credentials.
- Default to `smart_approve`, disabled telemetry, Simplified Chinese locale, Summon, and the
  ChartPilot MCP extension. Do not enable the generic Developer extension by default.
- Detect missing or modified runtime files before launch and fail with an actionable error.

### R3. Constrained ChartPilot MCP extension

- Use the official Python MCP SDK with stdio transport and the bundled interpreter.
- Expose only deterministic CSV workflow tools: profile a CSV, execute a validated analysis
  plan, and render the frozen result.
- Tool inputs may identify a source CSV only during profiling. Analysis and rendering operate
  by validated task ID beneath `workspace/tasks/`.
- Invoke existing business CLIs with argument arrays, sanitized Python environment variables,
  timeouts, and trusted read/write roots. Never invoke a shell or system Python.
- Preserve existing structured error objects and return bounded, structured results without
  leaking credentials or unrestricted raw rows.
- Generated arbitrary Python remains unavailable through the default MCP surface.

### R4. Goose-compatible Skills

- Keep `skills/` as the source of truth and stage its four Skills into the portable Goose
  Agent Skills location without copying Trellis development Skills.
- Update instructions so Goose uses the MCP tools for the standard CSV workflow and never
  substitutes its generic shell or Developer extension.
- Keep the existing direct CLI contract documented for diagnostics and non-Goose callers.

### R5. Reproducible validation and release

- Add offline-capable checks for Goose manifest integrity, Desktop and CLI presence/version,
  portable config generation, Skill staging, MCP initialization/tool listing, and the full
  CSV profile-to-PNG flow through MCP.
- Extend release packaging to include Goose, the MCP bridge, launcher, Skills in the expected
  Agent location, locks/manifests, and third-party license material.
- The release ZIP must exclude Trellis/Codex metadata, caches, build inputs, credentials, and
  user workspace contents.
- Document the build, local-archive option, first launch, Provider configuration, security
  boundary, and update procedure in English and Chinese project docs.

## Acceptance Criteria

- [x] A build command accepts the supplied ZIP, verifies the locked size and SHA-256, and
      installs Goose `v1.43.0` under the generated runtime tree.
- [x] Goose Desktop and its bundled CLI run `--version` or equivalent smoke checks without a
      system language runtime or CUDA.
- [x] The launcher creates/uses package-local Goose backend state, preserves existing user
      config, stages only ChartPilot Skills, and starts the pinned Desktop executable.
- [x] A protocol test initializes the ChartPilot MCP server and lists exactly the intended
      deterministic business tools.
- [x] An MCP integration test profiles a fixture CSV, executes an allowlisted plan, renders a
      valid PNG, and verifies the expected manifests and hashes.
- [x] Standard runtime tests, all four Skill validators, Python compilation, and PowerShell
      syntax checks pass after the dependency update.
- [x] Packaging produces a ChartPilot Windows x64 ZIP containing the launcher, Goose Desktop,
      bundled Python, MCP bridge, Skills, manifests, locks, and required licenses.
- [x] No tracked file contains the local Downloads path, API credentials, generated runtime,
      or user workspace data.

## Out Of Scope

- Rebuilding or rebranding Goose from source in this task.
- CUDA, bundled local LLM weights, or GPU-specific inference setup.
- Enabling arbitrary shell execution or arbitrary generated Python by default.
- Claiming that Goose provides a Windows OS sandbox.
- Automated release-ZIP relocation testing under Chinese or space-containing paths, per the
  user's earlier explicit exclusion.
- Forcing Electron UI caches that upstream stores in the Windows user profile into the package;
  the Goose backend config/data/state is portable through `GOOSE_PATH_ROOT`.
