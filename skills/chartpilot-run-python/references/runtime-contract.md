# Portable Python Runtime Contract

ChartPilot resolves only the interpreter declared by `runtime/runtime-manifest.json` and invokes
it directly with `-I`. It never searches `PATH`, `py.exe`, Conda, virtual environments, or user
site-packages.

The child environment applies the manifest's `set`, `unset`, and workspace-path rules. The MCP
bridge removes credential- and proxy-shaped environment variables before it starts.

Generated task code may use any package in `installed_distributions`. It may implement arbitrary
task-specific pandas, numpy, matplotlib, or Pillow logic and is not checked against an operation
or import allowlist. Do not call pip at task time; reusable dependencies belong in the locked
portable runtime and release license inventory.

Each execution records the runtime ID and manifest hash, submitted source and hash, stage,
attempt, duration, exit status, bounded stdout/stderr, and committed output hashes. WinPython
provides dependency and version isolation, not an operating-system sandbox.
