# ChartPilot

[English](README.md) | 简体中文

ChartPilot 是一个基于 Goose Desktop 的 Windows 本地优先 CSV 分析 Agent。它随项目
携带固定的 Goose 和 WinPython 运行时，可以在本地完成 CSV 剖析、声明式分析和 PNG
图表生成，不依赖系统 Python，也不需要把数据处理或绘图任务交给远程服务。

> [!IMPORTANT]
> Goose 提供图形化 Agent 外壳和模型 Provider 集成。ChartPilot 默认 MCP 扩展只暴露
> 三个确定性 CSV 工具，不默认启用 Goose 的通用 Developer 扩展。

## 核心能力

- 识别 UTF-8、UTF-8 BOM、GBK/GB18030、分隔符、字段类型、缺失值、重复记录和候选字段角色。
- 通过白名单分析计划执行清洗、筛选、时间分桶、分组指标、Top N、占比和变化率计算。
- 从 SHA-256 绑定的 `result.csv` 生成折线图、条形图、环形图和散点图，不在绘图阶段重新计算业务指标。
- 使用固定的 WinPython CPython 3.13.13 Windows x64 运行时，不调用系统 `python` 或 `py.exe`。
- 使用固定的 Goose Desktop 1.43.0 Windows x64 无 CUDA 版本，不要求 Node.js、Rust 或安装程序。
- 保护原始文件，返回结构化错误，并以事务方式提交多文件结果。
- 支持中文路径、中文字段、中文图表标签和离线运行。

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
│   ├── chartpilot-run-python/
│   ├── chartpilot-profile-csv/
│   ├── chartpilot-analyze-data/
│   └── chartpilot-render-chart/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
└── Windows离线部署方案.md
```

`runtime/`、`wheelhouse/`、`build/` 和 `dist/` 是本地生成目录，不进入 Git。

## 构建便携运行时

构建机要求 Windows 10/11 x64 和 PowerShell 5.1 或更高版本，不要求预先安装 Python。
项目固定使用 WinPython Release `17.4.20260511final` 中的
`WinPython64-3.13.13.0dot.zip`，下载前后均校验大小和 SHA-256。

生成运行时：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

该命令会生成 `runtime/`，从 `wheelhouse/` 按哈希锁离线安装依赖，并运行依赖检查、
CLI 冒烟测试、回归测试和 CSV 到 PNG 端到端测试。

项目同时固定 Goose Release `v1.43.0` 的无 CUDA `Goose-win32-x64.zip`。使用已经下载
的 ZIP 构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\build-goose.ps1 `
  -SourceArchive "C:\path\to\Goose-win32-x64.zip"
```

省略 `-SourceArchive` 时会下载锁定资产。两种方式都会先按 `goose.lock.json` 校验精确
大小和 SHA-256，再执行解压。

只有修改 `requirements.txt` 时才刷新完整依赖锁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

刷新后必须审查 `requirements.runtime.lock.txt` 中的版本和哈希变化。

## 启动 ChartPilot

运行 `Start-ChartPilot.cmd`。启动器会校验两套运行时清单，在 `workspace/goose` 初始化
Goose 状态，只同步四个 ChartPilot Skill，然后启动 Goose Desktop。首次使用时在 Goose
中配置支持的模型 Provider；Provider 凭据由 Goose 管理，不写入 ChartPilot 任务产物。

启动器默认允许读取 ChartPilot 目录和当前 Windows 用户目录下的 CSV，写入仍限制在
`workspace/tasks/`。

## 使用流程

所有命令都直接使用项目内解释器：

```powershell
$python = ".\runtime\winpython\python\python.exe"
```

剖析 CSV：

```powershell
& $python -I .\skills\chartpilot-profile-csv\scripts\profile_csv.py "data\sales.csv" `
  --task-id demo-001 `
  --output-dir "workspace\tasks\demo-001"
```

根据[分析契约](skills/chartpilot-analyze-data/references/contracts.md)创建
`analysis_plan.json`，然后执行：

```powershell
& $python -I .\skills\chartpilot-analyze-data\scripts\run_analysis.py `
  --profile "workspace\tasks\demo-001\input_profile.json" `
  --plan "workspace\tasks\demo-001\analysis_plan.json" `
  --output-dir "workspace\tasks\demo-001"
```

绘制已保存的分析结果：

```powershell
& $python -I .\skills\chartpilot-render-chart\scripts\render_chart.py `
  --analysis-result "workspace\tasks\demo-001\analysis_result.json"
```

标准产物链路：

```text
input_profile.json
  -> analysis_plan.json
  -> result.csv + analysis_result.json
  -> chart.png + chart_result.json + summary.md
```

## 验证与打包

运行完整验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\agent\test-agent.ps1
```

生成发布 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

输出位于 `dist/ChartPilot-win-x64-goose-py3.13.zip`。最终发布前仍应在干净的
Windows 10/11 非管理员环境进行人工验收。

## Agent 运行时协议

Goose 通过 Summon 加载 ChartPilot Skill，并调用随包提供的 stdio MCP 服务。MCP 服务
验证 `runtime/runtime-manifest.json`，只以参数数组启动三个确定性业务 CLI，并通过任务
ID 定位下游阶段。直接 CLI 协议仍保留用于诊断；默认 MCP 不暴露任意生成 Python。

## 安全边界

- 随附的业务工具不会发起网络请求，也不会执行模型生成的 Python 表达式。
- 源文件和上游产物通过 SHA-256 绑定，并在下游使用前校验。
- CSV 剖析阶段可以关闭样例输出或对敏感字段进行脱敏。
- 目标机不得在线运行 pip；依赖只能在构建阶段通过哈希锁更新。
- API Key 不得写入计划、生成代码、日志或结果。
- 默认 Goose 配置只启用 Summon 和 ChartPilot MCP，使用 `smart_approve` 并关闭 Goose 遥测。
- Goose 和 WinPython 都不是 Windows 操作系统沙箱。MCP 桥接限制自身路径、工具、子进程
  和超时；部署 ACL 与网络策略仍需由外部环境落实。
- 固定发行包中不要使用 Goose 自更新；应更新 `goose.lock.json` 并重新构建完整 Goose 运行时。

## 项目文档

- [需求规格说明](ChartPilot需求规格说明.md)
- [Skill 开发说明](Skill开发说明.md)
- [Windows 离线部署方案](Windows离线部署方案.md)

## 许可证

项目尚未选择软件许可证。仓库公开并不自动授予超出适用法律范围的使用、修改或再分发权限。
生成的 `runtime/third-party-licenses.json` 记录 Python 发行包许可证元数据；Goose 的
Apache-2.0 和 Chromium 通知保留在 `runtime/goose/`。
