# ChartPilot Windows 独立运行时与离线部署方案

## 目标

在 Windows 10/11 x64 上提供解压即用的 ChartPilot Skill 与 Python 运行环境：

- 不要求系统安装 Python；
- 不依赖 WSL、Docker、Conda 或系统 `PATH`；
- 数据处理和绘图完全在本地执行；
- 目标机不得在线安装依赖；
- 未来 Agent 底座只需按固定清单定位和启动解释器。

当前仓库尚未包含最终 Agent 底座，因此本方案交付的是“便携 Python 运行时 + Skill +
确定性工具 + 构建与打包流程”。

## 固定运行时基线

| 项目 | 固定值 |
| --- | --- |
| 上游 | WinPython |
| Release | `17.4.20260511final` |
| 资产 | `WinPython64-3.13.13.0dot.zip` |
| Python | CPython 3.13.13 x64 |
| 大小 | `27,697,763` 字节 |
| SHA-256 | `c6ada5d0a2fef7dc7ae79e4f9c046a55f98e7221a221a250e34dfcab02f384d1` |

选择 `dot` ZIP，而不是 `slim`、自由线程版本或自解压 EXE：

- `dot` 是最干净的官方基线，只增加 ChartPilot 当前实际依赖；
- ZIP 可以无交互解压和校验；
- 标准 CPython 3.13 的第三方 wheel 兼容面比 3.14/3.15 更稳妥；
- 项目不需要 WinPython `slim` 中的大量无关科学计算包。

`runtime.lock.json` 是上游来源、哈希、解释器路径和环境策略的单一来源。

## 依赖范围与锁定

当前直接依赖：

- pandas 3.0.3
- matplotlib 3.11.0
- Pillow 12.3.0

openpyxl、seaborn、pyarrow、duckdb 不进入首版运行时。全部直接和传递依赖记录在
Windows x64 CPython 3.13 专用的 `requirements.runtime.lock.txt`，每一项都包含
SHA-256。`wheelhouse/` 只接受 `.whl`，不允许源码包或自由线程 wheel。

依赖变更流程：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\update-lock.ps1
```

该脚本会：

1. 下载并校验固定 WinPython ZIP；
2. 使用 ZIP 中的 Python/pip，而不是系统 Python；
3. 只解析 CPython 3.13 Windows x64 二进制 wheel；
4. 生成确定排序的完整哈希锁；
5. 事务式替换 `wheelhouse/` 和依赖锁。

刷新后必须人工审查依赖版本、wheel 标签和哈希变化。

## 目录结构

```text
ChartPilot/
  runtime.lock.json
  requirements.txt
  requirements.runtime.lock.txt
  scripts/runtime/
  skills/
  runtime/                       # 生成，不入 Git
    runtime-manifest.json
    third-party-licenses.json
    winpython/
      python/
        python.exe
  wheelhouse/                    # 构建缓存，不随最终包安装依赖
  workspace/                     # 运行时可写目录
  build/                         # staging 和下载缓存
  dist/                          # 发布 ZIP
```

最终解释器相对项目根目录固定为：

```text
runtime/winpython/python/python.exe
```

## 构建运行时

联网构建机要求：

- Windows 10/11 x64；
- PowerShell 5.1 或更高版本；
- 可访问 GitHub Release 和 PyPI；
- 不需要预先安装 Python 或管理员权限。

构建命令：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\build-runtime.ps1
```

构建过程：

1. 校验缓存或重新下载 WinPython ZIP；
2. 解压到 `build/` staging；
3. 通过 `--no-index --find-links --require-hashes` 从 wheelhouse 安装；
4. 生成运行时清单和第三方许可证元数据；
5. 检查 Python 版本、架构、`pip check` 和关键模块导入；
6. 执行三个 CLI 的 `--help`、分析回归测试和 CSV 到 PNG 端到端测试；
7. staging 全部通过后才替换 `runtime/`，替换失败时恢复原运行时。

构建生成物不进入 Git。正式发布应归档 WinPython 原始 ZIP、wheelhouse、依赖锁和发布
ZIP，以便在无外网构建环境重现同一版本。

## Agent 调用协议

未来 Agent 底座应使用 `chartpilot-run-python` Skill 和
`skills/chartpilot-run-python/references/runtime-contract.md`：

1. 从受信任安装配置获得 ChartPilot 根目录；
2. 读取 `runtime/runtime-manifest.json`；
3. 验证 schema、状态、健康结果和解释器相对路径；
4. 解析后确认解释器仍位于项目根目录下；
5. 用进程 API 直接启动绝对解释器，所有参数独立传递；
6. 失败时明确返回运行时错误，不搜索系统 Python、不在线安装包。

子进程环境至少应：

- 设置 `PYTHONNOUSERSITE=1`、`PYTHONUTF8=1`、`PYTHONDONTWRITEBYTECODE=1`；
- 设置 `MPLBACKEND=Agg`；
- 清除 `PYTHONHOME`、`PYTHONPATH`、`VIRTUAL_ENV` 和 Conda 变量；
- 将 `HOME`、`TEMP`、`TMP`、`MPLCONFIGDIR`、`PYTHONPYCACHEPREFIX` 指向可写 workspace；
- 移除与当前任务无关的密钥、代理和工具凭据。

禁止拼接 PowerShell/cmd 命令字符串。用户文件路径必须作为进程参数数组中的独立元素。

## 生成 Python 代码的边界

标准 CSV 流程继续优先使用三个确定性业务 Skill：

- profiler 只剖析；
- analyzer 只执行白名单声明式计划；
- renderer 只渲染冻结结果。

只有在业务契约无法覆盖、部署策略明确允许时，Agent 才能通过
`chartpilot-run-python` 生成通用 Python。生成代码必须：

- 保存到当前 `workspace/tasks/<task-id>/`；
- 使用明确输入输出和可审计 `main()`；
- 只使用运行时清单中的包；
- 禁止 pip、网络、shell、子进程、动态导入、`eval`、`exec` 和目录外写入；
- 保存代码哈希、运行时 ID、退出码、耗时及受限输出记录。

WinPython 只提供运行时隔离，不提供安全沙箱。超时、资源限制、ACL、子进程和网络策略
仍由 Agent 底座落实。

## 验证与发布

完整验证：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\test-runtime.ps1
```

发布打包：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\runtime\package-release.ps1
```

发布 ZIP 包含运行时、Skill、确定性工具、锁文件、清单和用户文档，不包含 `.git`、
`.trellis`、`.codex`、wheelhouse、构建缓存或用户 workspace。

当前自动验证覆盖中文文件名、中文字段、带空格的数据路径和 CSV 到 PNG 链路。最终发布前
仍需在干净 Windows 10/11 x64、非管理员、无系统 Python、无通用外网环境下人工验收。

## 目标机运行规则

- 解压发布 ZIP 后直接使用，不执行安装步骤；
- 不修改系统 PATH 或注册表；
- 不在目标机运行 pip；
- 只允许对指定数据目录和 workspace 读写；
- 除配置的 LLM API 外，不允许主动访问网络；
- 升级时替换完整的版本化运行时和清单，不做原地依赖漂移升级。
