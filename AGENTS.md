# AGENTS.md

> 本文件是面向后续 Agent（以及人类协作者）的仓库工作流说明。
> 修改仓库结构、构建方式、测试命令或设计约定时，必须同步更新本文件。

## 1. 这个仓库是什么

一个 uv workspace，承载两个相互关联的项目：

1. **Phonolite**（`apps/phonolite/` + `packages/audio-core/`）——已可用的桌面应用：
   实时麦克风/音频文件频谱分析与音高探索（PySide6 + pyqtgraph）。状态稳定，
   **不要破坏它**；`audio-core` 是纯算法库（numpy/scipy，无 Qt），未来会成为
   Workbench 的音频分析（MIR）后端。
2. **Music Agent Workbench**（`packages/`、`apps/`）——新建项目：面向音乐创作
   学习的 Agent 系统（Composition IDE）。

**架构的唯一事实来源是 `music_agent_workbench_design.md`（中文）。**
做任何结构性决策前必须先读它；代码与设计文档冲突时，要么改代码，要么先更新
设计文档再改代码。

## 2. 目录结构

```text
Phonolite/
├── pyproject.toml            # uv workspace 虚拟根（members + dev 依赖 + pytest 配置）
├── packages/
│   ├── music-core/           # 宿主无关的音乐领域核心：Score IR / io / 分析 / 变换
│   └── audio-core/           # 音频 DSP 与音高工具（STFT/峰值/chroma/音名），未来 MIR 后端
├── apps/
│   ├── phonolite/            # Phonolite Qt 桌面应用（audio 采集/回放 + ui；算法依赖 audio-core）
│   ├── server/               # FastAPI 应用层（Domain API / WebSocket）
│   └── web/                  # Workbench 前端（Vite + React + TypeScript）
├── music_agent_workbench_design.md   # 设计文档（架构事实来源）
└── AGENTS.md                 # 本文件
```

## 3. 常用命令

```powershell
uv sync --all-packages        # 安装整个 workspace（含全部成员包与 dev 依赖）
uv run phonolite              # 启动 Phonolite Qt 应用
uv run workbench-server       # 启动 FastAPI（127.0.0.1:8000，带 reload）
uv run pytest                 # 运行 workspace 全部 Python 测试

cd apps/web
pnpm install                  # 首次安装前端依赖
pnpm dev                      # Vite dev server（:5173，代理 /api 与 /ws 到 :8000）
pnpm build                    # 类型检查 + 构建（提交前至少跑一次）
```

## 4. 代码该放哪里（决策规则）

- **音乐领域逻辑**（Score IR、分析、变换、校验、渲染）→ `packages/music-core`。
  它不依赖任何 Agent 宿主、Web 框架或 UI，保持纯 Python、可单测。
- **HTTP/WebSocket 接口、会话、任务路由** → `apps/server`。保持薄层：
  只做参数校验、调用 music-core、返回设计文档第 8.4 节的统一 Envelope。
- **UI** → `apps/web`。聊天框不是唯一核心，选区/版本/试听/审批才是。
- **音频/MIR 分析** → `packages/audio-core`。保持纯 numpy/scipy、无 Qt、无音频
  I/O，这样 server 和未来 Agent 工具都能直接复用；Qt 采集/回放代码留在
  `apps/phonolite`。
- **不要**创建设计文档里"暂时不做"的东西：自治多 Agent、VST3、知识图谱、
  通用向量库、完整音频转录。也不要提前把 `skills/`、`adapters/` 等目录一次性
  建全——按 MVP 路线（设计文档第 16 节）用到再建。

## 5. 编码约定

- Python 3.12（`>=3.12,<3.13`，全 workspace 统一）；src layout；hatchling 构建。
- 新 Python 包需在根 `pyproject.toml` 的 `[tool.uv.workspace] members` 注册，
  依赖方用 `[tool.uv.sources] xxx = { workspace = true }` 引用。
- 风格跟随现有代码：英文模块 docstring、`from __future__ import annotations`、
  dataclass + 类型标注、注释用英文。
- 设计文档与中文讨论用中文；代码、docstring、commit message 用英文。
- 测试：pytest，每个包的测试放在自己的 `tests/`（如 `packages/music-core/tests/`）；
  根 `pyproject.toml` 的 `testpaths` 需同步注册。
- 提交前：`uv run pytest` 全绿；改了前端则 `pnpm build` 通过。

## 6. 设计红线（来自设计文档，写代码时必须遵守）

- **少生成，多诊断**：先分析再改写；每次只改一个主要变量；候选默认不超过三个。
- **可定位**：分析结论必须带小节/拍点/音轨位置、置信度、替代解释。
- **不覆盖用户材料**：所有变换生成新版本（branch），不原地修改；主版本只能通过
  显式的 accept 操作更新。
- **业务状态显式化**：项目状态/决策/学习状态通过结构化数据更新，不依赖 LLM
  从聊天历史总结。
- **人在审美环路中**：修改核心主题、覆盖正式版本、合并实验分支、写长期偏好等
  操作必须留审批点。
- **工具优先于模型判断**：确定性校验（时值、音域、手跨度等）先于 LLM 结论。

## 7. 当前里程碑

锚点是设计文档第 19 节的**第一条纵向切片**：

```text
MIDI Import → Score IR → Project Goal → Inspect → Delayed Resolution Transform
→ Semantic Diff → Render → A/B Selection → Project Decision → Learning Event
```

在它跑通之前，不投入：完整音频转录、自治多 Agent、VST3、复杂 UI、多 DAW
支持。优先完成设计文档第 17 节列出的前几个 issue（Score IR、MIDI round-trip、
project.yaml、基础分析、受控变换、diff、渲染）。
