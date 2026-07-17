# ChartPilot Windows 独立运行时与离线部署方案

## 目标

在 Windows 10/11 x64 上提供解压即用的 ChartPilot：

- 不要求系统安装 Python、Node.js、Rust、CUDA、WSL、Docker 或 Conda；
- Goose Desktop 提供图形界面和模型 Provider；
- WinPython 执行 Agent 针对每次 prompt+CSV 编写的任务代码；
- 数据处理和绘图在本地完成；
- 目标机不在线安装依赖；
- 任务代码、执行记录和产物保存在包内 `workspace/`。

交付内容为“便携 Goose Desktop + 便携 WinPython + 单一自适应 Skill + 两工具 MCP + 构建、
测试和打包流程”。

## 固定运行时

### WinPython

| 项目 | 固定值 |
| --- | --- |
| Release | `17.4.20260511final` |
| 资产 | `WinPython64-3.13.13.0dot.zip` |
| Python | CPython 3.13.13 x64 |
| 大小 | `27,697,763` 字节 |
| SHA-256 | `c6ada5d0a2fef7dc7ae79e4f9c046a55f98e7221a221a250e34dfcab02f384d1` |

选择 `dot` ZIP 作为干净基线，只安装 ChartPilot 实际依赖。`runtime.lock.json` 是上游、
解释器相对路径和环境策略的来源。

直接依赖包括 pandas、matplotlib、Pillow、mcp 和 PyYAML；numpy 等传递依赖由
`requirements.runtime.lock.txt` 按 CPython 3.13 Windows x64 wheel 和 SHA-256 完整锁定。
当前自适应流程不需要 openpyxl、seaborn、pyarrow 或 duckdb。

### Goose

| 项目 | 固定值 |
| --- | --- |
| Release | `v1.43.0` |
| 资产 | `Goose-win32-x64.zip` |
| 架构 | Windows x64，无 CUDA |
| 大小 | `250,045,188` 字节 |
| SHA-256 | `9014edf214395370d3de5a3dd7acc90cb2eace2abc5ee398266f7809b7726956` |

Goose 和 WinPython 分别由 `goose.lock.json` 和 `runtime.lock.json` 管理，可以独立升级，
但每次升级都必须重新构建、验证和打包。

## 生成目录

```text
runtime/       # 两套已构建运行时与清单
wheelhouse/    # 哈希锁 wheel
workspace/     # Goose 状态、任务、缓存、执行记录
build/         # staging
dist/          # 发布 ZIP
```

这些目录不进入 Git。源码提交 MCP、模板、Skills、锁文件、构建脚本和文档。

## 构建

刷新依赖锁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

构建 WinPython：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

构建 Goose：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\build-goose.ps1 `
  -SourceArchive "C:\path\to\Goose-win32-x64.zip"
```

所有构建都先验证大小和哈希，在 `build/` staging 中完成依赖安装、版本检查、测试和清单
生成，全部通过后才替换已有 runtime；失败时保留旧运行时。

## Agent 调用协议

Goose 通过 Summon 只加载 `chartpilot-run-python`，通过 stdio 启动
`agent/mcp/chartpilot_mcp.py`。MCP 恰好暴露：

- `chartpilot_prepare_adaptive_task`
- `chartpilot_run_task_python`

准备工具接收 CSV 和 inline prompt 或 UTF-8 `.md`/`.txt` prompt 文件，保存 `request.md`，
记录源文件哈希、运行时清单和三份模板。执行工具接收 task ID、stage 与完整 Python 源码，
用绝对捆绑解释器运行：

```text
<ChartPilot>\runtime\winpython\python\python.exe -I <generated-script> `
  --context <attempt-task-context.json>
```

stage 顺序为 inspect、analysis、render。MCP 使用临时输出目录，只有当阶段契约验证通过时
才事务式替换任务产物，`analysis_result.json` 或 `chart_result.json` 最后安装。Analysis 可
声明并提交额外 UTF-8 辅助文件；重试时不再声明的旧阶段文件会在同一事务中移除。

生成进程失败时，工具响应直接包含有界 stdout/stderr 尾部诊断。Render 出现 Matplotlib
中文缺字警告或文本替换字符时按可恢复错误处理，不会把仅“非空”的乱码 PNG 提交为成功。

## 子进程环境

运行时清单要求：

```text
set: PYTHONNOUSERSITE=1, PYTHONUTF8=1, PYTHONDONTWRITEBYTECODE=1, MPLBACKEND=Agg
unset: PYTHONHOME, PYTHONPATH, VIRTUAL_ENV, CONDA_PREFIX, CONDA_DEFAULT_ENV
workspace: HOME, TEMP, TMP, MPLCONFIGDIR, PYTHONPYCACHEPREFIX
```

MCP 启动时移除凭据和代理形态的环境变量。禁止通过 `PATH` 搜索 Python，也不在目标机
运行 pip。

## 生成代码边界

自适应 Python 是标准且唯一的 CSV 路径，不存在旧的 profile/analysis-plan/fixed-render
工具或备用 Skills。Agent 可以修改三份模板中的业务逻辑、图表类型、布局、标注和中文
说明，并使用 runtime manifest 中已经安装的包。

本版本不使用业务操作白名单、AST/import 白名单或 Python 沙箱。WinPython 只提供版本和
依赖隔离，生成代码拥有当前 Windows 用户权限。任务目录、输入哈希、staging、超时、受限
输出和执行记录用于可复现与故障定位，不构成操作系统安全边界。

## Goose 便携状态

启动器设置：

```text
GOOSE_PATH_ROOT=<ChartPilot>\workspace\goose
CHARTPILOT_ROOT=<ChartPilot>
CHARTPILOT_WORKSPACE_ROOT=<ChartPilot>\workspace
CHARTPILOT_ALLOWED_READ_ROOTS=<配置的本地读取根>
```

Goose 1.43.0 从 `GOOSE_PATH_ROOT/config/skills` 发现产品 Skill。启动工作目录必须是隔离的
`workspace/session`，防止仓库 `.agents/skills` 中的 Trellis 开发 Skills 进入产品会话。
初始化会刷新一个产品 Skill，并清理三个已删除的旧业务 Skill，同时保留 Provider 配置、
凭据和用户禁用 ChartPilot extension 的选择。

Electron UI 缓存仍可能按上游行为写入 `%APPDATA%`；ChartPilot 后端状态、任务和运行时保持
包内便携。

## 验证

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\test-agent.ps1
```

验证包括：

- runtime/Goose 资产、版本、架构和清单哈希；
- `pip check` 与 pandas、numpy、matplotlib、Pillow、mcp、PyYAML 导入；
- 三份模板 `--help`、单元测试、匿名变化字段/阈值回归和 CSV 到 PNG smoke；
- MCP 恰好两个工具，Goose 恰好一个产品 Skill；
- 旧工具和旧 Skills 不出现在 source staging 或发布 ZIP；
- Skill validator、PowerShell 解析和 PowerShell 5.1 ASCII 检查；
- 发布 ZIP 必需项和禁止目录检查。

SY135 参考案例可显式运行：

```powershell
runtime\winpython\python\python.exe -I scripts\agent\test-sy135-adaptive.py `
  --project-root . `
  --case-root "C:\path\to\SY135油耗分析" `
  --keep-output
```

该测试从外部 prompt 和 CSV 生成结果，不读取人工 XLSX，不把案例源数据打入发布包。

## 发布

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

发布 ZIP 包含 Goose、WinPython、MCP、启动器、单一 Skill、三份模板、锁文件、清单、许可证
和用户文档；不包含 `.git`、`.trellis`、`.codex`、wheelhouse、构建缓存或 workspace。

解压后运行 `Start-ChartPilot.cmd`，不执行安装步骤。首次启动在 Goose 中配置 Provider。
固定发行包不使用 Goose 自更新；升级应修改锁文件并重新生成完整 ZIP。
