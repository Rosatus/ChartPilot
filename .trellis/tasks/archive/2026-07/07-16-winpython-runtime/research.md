# WinPython Runtime Research

## Selected Baseline

- Repository: `https://github.com/winpython/winpython`
- Stable release: `17.4.20260511final`
- Published: `2026-05-17T07:45:31Z`
- Asset: `WinPython64-3.13.13.0dot.zip`
- Size: `27,697,763` bytes
- SHA-256: `c6ada5d0a2fef7dc7ae79e4f9c046a55f98e7221a221a250e34dfcab02f384d1`
- URL: `https://github.com/winpython/winpython/releases/download/17.4.20260511final/WinPython64-3.13.13.0dot.zip`

Associated upstream metadata:

- `pylock.64-3_13_13_0dot.toml`
- `requir.64-3_13_13_0dot.txt`

## Selection Rationale

- `dot` is the cleanest official WinPython base suitable for adding only ChartPilot dependencies.
- ZIP supports deterministic, unattended extraction without running a self-extracting executable.
- CPython 3.13 is a conservative compatibility target compared with newer 3.14/3.15 releases.
- Standard CPython is required; free-threaded `cp313t` is excluded.
- The existing project recommends 3.12, so moving to 3.13 requires full regression and Windows acceptance testing.

## Current Direct Dependency Compatibility

All current pins provide standard `cp313-cp313-win_amd64` wheels on PyPI:

| Package | Version | Python requirement | Windows x64 wheel SHA-256 |
| --- | --- | --- | --- |
| pandas | 3.0.3 | `>=3.11` | `a82d532a3351d435432cd913edbccaf8b8e01d4dd0e5ced5a8d2e8ecd94c7e44` |
| matplotlib | 3.11.0 | `>=3.11` | `ab3722f04f3ff34c23b5012c5873d2894174e06c3822fcdac3610965a5ac7d06` |
| Pillow | 12.3.0 | `>=3.10` | `1cca606cd25738df4ed873d5ad46bbdb3d83b5cbca291f6b4ff13a4df6b0bbe8` |

The final lock must also include every transitive dependency selected by pip, including NumPy and Matplotlib dependencies.

## Existing Repository Evidence

- `requirements.txt:1-3` pins pandas, matplotlib and Pillow.
- `README.zh-CN.md:36` recommends Python 3.12.
- `README.zh-CN.md:59,67,76` invokes the three skills with bare `python`.
- `Windows离线部署方案.md:69-89` proposes a portable runtime and lists current/future package candidates.
- `skills/chartpilot-analyze-data/SKILL.md:50` already prohibits runtime dependency downloads.

## Decisions Already Recovered From Session History

- Use a WinPython release distribution, not the build-tool repository itself, as the runtime.
- Prefer `dot` over `slim` to minimize unrelated packages and supply-chain surface.
- Never use system `python` or `py.exe` at runtime.
- Production builds should keep a hash-locked wheelhouse for reproducibility; it need not ship to end users.
- Validate Chinese/space data paths and no-network operation automatically; keep clean-host and
  non-admin validation as a manual release gate. The user explicitly removed automated release
  ZIP relocation testing from this task.
