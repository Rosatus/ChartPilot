# ChartPilot

[English](README.md) | 简体中文

ChartPilot 是一套面向 Windows 本地数据分析 Agent 的 CSV 分析 Skill。它随项目携带
固定的 WinPython 运行时，可以在本地完成 CSV 剖析、声明式分析和 PNG 图表生成，
不依赖系统 Python，也不需要把数据处理或绘图任务交给远程服务。

> [!IMPORTANT]
> 当前仓库包含三个业务 Skill、一个 Python 运行时 Skill、确定性 Python 工具和便携
> 运行时构建流程，尚未包含最终 Agent 底座或图形界面。

## 核心能力

- 识别 UTF-8、UTF-8 BOM、GBK/GB18030、分隔符、字段类型、缺失值、重复记录和候选字段角色。
- 通过白名单分析计划执行清洗、筛选、时间分桶、分组指标、Top N、占比和变化率计算。
- 从 SHA-256 绑定的 `result.csv` 生成折线图、条形图、环形图和散点图，不在绘图阶段重新计算业务指标。
- 使用固定的 WinPython CPython 3.13.13 Windows x64 运行时，不调用系统 `python` 或 `py.exe`。
- 保护原始文件，返回结构化错误，并以事务方式提交多文件结果。
- 支持中文路径、中文字段、中文图表标签和离线运行。

## 仓库结构

```text
ChartPilot/
├── runtime.lock.json
├── requirements.txt
├── requirements.runtime.lock.txt
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

只有修改 `requirements.txt` 时才刷新完整依赖锁：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

刷新后必须审查 `requirements.runtime.lock.txt` 中的版本和哈希变化。

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
```

生成发布 ZIP：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

输出位于 `dist/ChartPilot-runtime-win-x64-py3.13.zip`。最终发布前仍应在干净的
Windows 10/11 非管理员环境进行人工验收。

## Agent 运行时协议

`chartpilot-run-python` 说明未来 Agent 底座如何读取 `runtime/runtime-manifest.json`、
验证解释器、清理 Python 环境变量、用参数数组直接启动进程，以及如何保存生成代码和
执行审计。三个业务 Skill 仍优先使用固定的确定性 runner，不会因为新增运行时 Skill
而允许任意表达式进入标准 CSV 分析链路。

## 安全边界

- 随附的业务工具不会发起网络请求，也不会执行模型生成的 Python 表达式。
- 源文件和上游产物通过 SHA-256 绑定，并在下游使用前校验。
- CSV 剖析阶段可以关闭样例输出或对敏感字段进行脱敏。
- 目标机不得在线运行 pip；依赖只能在构建阶段通过哈希锁更新。
- API Key 不得写入计划、生成代码、日志或结果。
- WinPython 不是操作系统沙箱。目录 ACL、进程超时、资源限制和网络策略仍由未来 Agent 底座负责。

## 项目文档

- [需求规格说明](ChartPilot需求规格说明.md)
- [Skill 开发说明](Skill开发说明.md)
- [Windows 离线部署方案](Windows离线部署方案.md)

## 许可证

项目尚未选择软件许可证。仓库公开并不自动授予超出适用法律范围的使用、修改或再分发权限。
生成的 `runtime/third-party-licenses.json` 记录便携环境中第三方发行包的许可证元数据。
