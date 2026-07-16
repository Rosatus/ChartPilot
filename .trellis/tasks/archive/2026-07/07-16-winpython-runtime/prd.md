# WinPython 独立运行时与 Skill 改造

## Goal

让 ChartPilot 可以随发布包携带一套固定、可迁移的 Windows x64 Python
运行时。最终用户解压后即可运行 CSV 剖析、分析和绘图，无需安装 Python、
无需管理员权限，也不得依赖系统 `PATH` 中的 `python` 或 `py.exe`。

同时改造三个业务 Skill 的运行约定，使未来 Agent 底座能够：

- 明确定位 ChartPilot 自带的 Python 解释器；
- 生成受约束、可审计的 Python/JSON 分析产物；
- 始终通过指定的本地运行时执行代码；
- 在运行时缺失、依赖损坏或路径越界时给出稳定错误，而不是回退到系统 Python。

## Background

- WinPython 官方将自身定义为 Windows 便携 Python 发行版，并说明
  `winpython/winpython` 仓库主要是 WPPM 与构建工具链；本项目应使用官方
  Release 发行包作为基线，而不是把源码仓库直接当运行时。
- 当前最新稳定 Release 是 `17.4.20260511final`，发布于 2026-05-17。
  计划采用其中的 `WinPython64-3.13.13.0dot.zip`：Windows x64、标准
  CPython 3.13、精简 `dot` 变体、ZIP 便于无交互解压。
- 该 ZIP 大小为 27,697,763 字节，官方 SHA-256 为
  `c6ada5d0a2fef7dc7ae79e4f9c046a55f98e7221a221a250e34dfcab02f384d1`。
- 当前运行依赖固定为 pandas 3.0.3、matplotlib 3.11.0、Pillow 12.3.0
  （`requirements.txt:1-3`）；三者均有标准 CPython 3.13 Windows x64 wheel。
- README 仍推荐 Python 3.12（`README.zh-CN.md:36`），并使用裸 `python`
  命令演示三个 Skill（`README.zh-CN.md:59,67,76`），需要与便携运行时约定统一。
- 现有离线部署文档已提出可移植 Python、wheel 离线安装以及 pandas、numpy、
  matplotlib、openpyxl 等候选包（`Windows离线部署方案.md:69-89`），但尚未定义
  固定发行版、目录契约、锁文件、启动器和 Agent 调用协议。

## Requirements

### Scope Decision

- 首版运行时只安装当前 CSV MVP 实际使用的 pandas 3.0.3、matplotlib 3.11.0、
  Pillow 12.3.0 及其传递依赖。
- openpyxl、seaborn、pyarrow、duckdb 等未来候选包不进入首版运行时；构建定义应允许
  后续通过显式依赖配置扩展，而不是预装未被业务能力使用的包。

### R1. 固定并验证运行时来源

- 固定 GitHub Release 标签、资产文件名、下载 URL、文件大小和 SHA-256。
- 构建流程必须在解压前校验 SHA-256，校验失败立即停止。
- 不使用预发布版本、自由线程 CPython 或包含大量无关包的 `slim` 变体。
- 上游 ZIP 不直接提交到 Git；构建产物和下载缓存必须有清晰的忽略与归档策略。

### R2. 建立可重复的依赖装配流程

- 使用 WinPython 自带的 `python.exe -m pip` 安装依赖，禁止调用系统 Python。
- 只接受 Windows x64 二进制 wheel，不允许构建机从源码现场编译。
- 区分直接依赖与传递依赖，生成带版本和 SHA-256 的锁定清单。
- 保存构建清单，至少记录 WinPython 版本、Python 版本、已安装包、wheel 哈希和构建时间。
- 正式发布构建应支持使用本地 wheelhouse 重建；目标机运行时不得在线安装包。

### R3. 定义解压即用的目录与启动契约

- 运行时放在仓库/发布包内的固定相对目录，通过项目根目录解析，不能写死构建机绝对路径。
- 提供唯一的运行时解析/启动入口，供 Agent 和人工命令共同使用。
- 启动时设置 `PYTHONNOUSERSITE=1`、`PYTHONUTF8=1`，清除外部 `PYTHONPATH`，
  并把临时文件、Matplotlib 配置和缓存指向可写的 `workspace`。
- 业务 CLI 必须继续支持包含空格和中文的数据文件及任务目录。
- 找不到内置运行时或健康检查失败时必须显式报错，禁止静默回退系统 Python。

### R4. 改造 Skill 与 Agent 执行协议

- 三个 `SKILL.md` 和相关契约统一使用项目提供的运行时入口，不再指导 Agent 执行裸 `python`。
- 明确 Agent 生成代码的边界：优先生成声明式计划；允许的 Python 产物必须写入任务目录、
  可审计、不得自行安装依赖、不得联网、不得使用 `eval`/`exec` 或绕过读写根目录。
- Agent 必须以参数数组调用运行时入口，路径与用户数据不得拼接成 shell 命令。
- 分析和绘图仍保持当前职责边界；运行时改造不得允许绘图阶段重新计算业务指标。
- 运行时协议应与未来 Agent 底座解耦，不绑定 Open Interpreter、Goose 或其他特定底座。

### R5. 文档、验证与供应链记录

- 更新中英文 README、Windows 离线部署说明和必要的 Skill 契约。
- 提供构建、健康检查、测试和重新打包的可重复命令。
- 验证 `pip check`、关键模块导入、三个 CLI 的 `--help`、现有回归测试和端到端示例。
- 生成第三方许可证/归属清单，至少覆盖 WinPython、CPython 和所有已安装 wheel。
- 在干净 Windows 10/11 x64、非管理员账户、无系统 Python、无外网环境下定义最终验收步骤。

## Acceptance Criteria

- [x] 构建脚本能下载固定的 `WinPython64-3.13.13.0dot.zip`，并在解压前通过官方 SHA-256 校验。
- [x] 构建脚本能从空目录生成版本化的便携运行时和完整构建清单，重复执行结果可解释、失败可恢复。
- [x] 运行时只使用标准 CPython 3.13 Windows x64 wheel，并通过 `pip check`。
- [x] 内置 Python 能导入所有锁定依赖，并能处理中文文件名、中文字段和带空格的数据路径。
- [x] 在系统未安装 Python 或系统 Python 不可用时，所有 Skill 仍通过项目运行时工作。
- [x] 内置运行时缺失或损坏时，命令明确失败且不会调用 `python`、`py.exe` 或用户 site-packages。
- [x] 三个 Skill 清楚说明代码/计划生成边界、固定运行时调用方式、工作目录和安全环境变量。
- [x] 原始 CSV、分析结果 SHA-256、原子产物提交和三段式职责边界保持不变。
- [x] 当前自动化测试、CLI 冒烟测试和一条端到端 CSV 到 PNG 流程均通过内置运行时。
- [x] 构建产物包含运行时版本、依赖版本与哈希、许可证信息和离线重建说明。

## Out Of Scope

- 选择或实现最终 Agent 底座。
- 构建 GUI、安装器或自动更新服务。
- 把 WinPython 视为安全沙箱；进程资源限制、ACL 和网络白名单仍由未来 Agent 底座负责。
- 在本任务中新增 Excel、SQL、Parquet 或 DuckDB 业务能力。
