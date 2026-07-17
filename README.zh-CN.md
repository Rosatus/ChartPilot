# ChartPilot

[English](README.md) | 简体中文

ChartPilot 是一个基于 Goose Desktop 的 Windows 本地优先 CSV 分析 Agent。它随项目携带
固定的 Goose 和 WinPython 运行时，能够针对每次自然语言需求和 CSV 修改 Python 模板，
并在本地完成分析与 PNG 图表生成，不依赖系统 Python。

> [!IMPORTANT]
> ChartPilot 默认 MCP 只暴露两个自适应工具：准备 prompt+CSV 任务，以及执行 Agent 编写
> 的阶段 Python；不默认启用 Goose 的通用 Developer 扩展。

## 核心能力

- 从精简的 inspect、analysis、render 模板起步，按真实字段、业务口径、阈值和呈现要求修改。
- 使用 pandas/numpy 直接完成嵌套分组、同群基准、风险分类等任务，不套固定操作词表。
- 使用 matplotlib/Pillow 生成任务特定的单图或多区域 PNG 报告，并支持中文字体。
- 使用固定的 WinPython CPython 3.13.13 Windows x64，不调用系统 `python` 或 `py.exe`。
- 使用固定的 Goose Desktop 1.43.0 Windows x64 无 CUDA 版本，不要求 Node.js、Rust 或安装程序。
- 保存完整生成代码、运行时身份、受限进程输出、执行状态、产物哈希和任务结果。

## 仓库结构

```text
ChartPilot/
├── Start-ChartPilot.cmd
├── goose.lock.json
├── runtime.lock.json
├── requirements.txt
├── requirements.runtime.lock.txt
├── agent/
├── scripts/agent/
├── scripts/runtime/
├── skills/
│   └── chartpilot-run-python/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
└── Windows离线部署方案.md
```

`runtime/`、`wheelhouse/`、`workspace/`、`build/` 和 `dist/` 是本地生成目录，不进入 Git。

## 构建便携运行时

构建机要求 Windows 10/11 x64 和 PowerShell 5.1 或更高版本，不要求预先安装 Python。
项目固定使用 WinPython Release `17.4.20260511final` 中的
`WinPython64-3.13.13.0dot.zip`，并校验大小和 SHA-256。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

项目同时固定 Goose Release `v1.43.0` 的无 CUDA `Goose-win32-x64.zip`：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\build-goose.ps1 `
  -SourceArchive "C:\path\to\Goose-win32-x64.zip"
```

省略 `-SourceArchive` 时下载锁定资产。只有修改 `requirements.txt` 时才刷新完整依赖锁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

刷新后必须审查 `requirements.runtime.lock.txt` 中的版本和哈希变化。

## 启动 ChartPilot

运行 `Start-ChartPilot.cmd`。启动器会校验两套运行时清单，在 `workspace/goose` 初始化
便携状态，只同步一个 ChartPilot 自适应 Skill，然后启动 Goose Desktop。首次使用时在
Goose 中配置模型 Provider。

启动器默认允许读取 ChartPilot 目录和当前 Windows 用户目录，任务代码和产物写入
`workspace/tasks/`。

## 运行自适应流程

向 Goose 提供需求和 CSV 路径，或本地 UTF-8 `.md`/`.txt` 需求文件与 CSV 路径。Skill
调用 `chartpilot_prepare_adaptive_task`，阅读任务上下文和三份模板，再按需修改并分别以
`inspect`、`analysis`、`render` 阶段调用 `chartpilot_run_task_python`。

```text
request.md + task_context.json + generated_inspect.py
  -> inspection.json
  -> generated_analysis.py + result.csv + analysis_result.json
  -> generated_chart.py + chart.png + chart_result.json + summary.md
```

如果计算、标签、图表组合或呈现效果不符合需求，Agent 应修改生成代码并重试。系统不存在
确定性备用路由。

## 验证与打包

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\test-agent.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

输出位于 `dist/ChartPilot-win-x64-goose-py3.13.zip`。可选 SY135 参考验收通过
`scripts/agent/test-sy135-adaptive.py` 接收外部案例目录，不打包原始数据或人工产物。

## 运行与安全边界

- MCP 验证 `runtime/runtime-manifest.json`，保存完整任务代码，以参数数组启动捆绑
  WinPython，在 staging 中验证产物并记录每次执行。
- 任务 Python 有意保持灵活，不经过操作或 import 白名单。
- 源文件通过 SHA-256 绑定并在每个阶段执行前校验，阶段产物验收后才提交 completion manifest。
- 目标机不得在线运行 pip；依赖只能在构建阶段通过哈希锁更新。
- Goose 和 WinPython 都不是 Windows 操作系统沙箱。生成代码拥有当前用户权限，部署 ACL
  与网络策略由外部环境落实。
- 固定发行包中不要使用 Goose 自更新；应更新 `goose.lock.json` 并重新构建。

## 项目文档

- [需求规格说明](ChartPilot需求规格说明.md)
- [Skill 开发说明](Skill开发说明.md)
- [Windows 离线部署方案](Windows离线部署方案.md)

## 许可证

项目尚未选择软件许可证。仓库公开并不自动授予超出适用法律范围的使用、修改或再分发权限。
生成的 `runtime/third-party-licenses.json` 记录 Python 发行包许可证元数据；Goose 的
Apache-2.0 和 Chromium 通知保留在 `runtime/goose/`。
