# AGENTS.md

> 本文件是面向后续 Agent（以及人类协作者）的仓库工作流说明。
> 修改仓库结构、构建方式、测试命令或设计约定时，必须同步更新本文件。

## 1. 这个仓库是什么

一个 uv workspace，承载两个相互关联的项目：

1. **Phonolite**（`apps/phonolite/` + `packages/audio-core/`）——已可用的桌面应用：
   实时麦克风/音频文件频谱分析与音高探索（PySide6 + pyqtgraph）。Qt 应用现已
   **冻结**：除严重缺陷外不再修改，也不新增功能。`audio-core` 是持续维护的纯算法库
   （numpy/scipy，无 Qt），未来会成为 Workbench 的音频分析（MIR）后端。
2. **Music Agent Workbench**（`packages/`、`apps/`）——面向原创创作/学习，以及从原曲
   音频扒谱并做钢琴改编的 Agent 工作台（Composition IDE），统一采用 React + FastAPI。

**架构的唯一事实来源是 `music_agent_workbench_design.md`（中文）。**
做任何结构性决策前必须先读它；代码与设计文档冲突时，要么改代码，要么先更新
设计文档再改代码。

## 2. 目录结构

```text
Phonolite/
├── pyproject.toml            # uv workspace 虚拟根（members + dev 依赖 + pytest 配置）
├── packages/
│   ├── music-core/           # 宿主无关的音乐领域核心：Score IR / io / 分析 / 变换
│   ├── memory-core/          # 宿主无关的事件溯源记忆、学习状态与 Recall Planner
│   ├── agent-runtime/        # AgentRuntime 协议与 OpenCode CLI Adapter
│   ├── music-mcp/            # OpenCode stdio MCP → Server Domain API 薄代理
│   └── audio-core/           # 音频 DSP 与音高工具（STFT/峰值/chroma/音名），未来 MIR 后端
├── apps/
│   ├── phonolite/            # 已冻结的历史 Qt 桌面应用；仅修严重缺陷
│   ├── server/               # FastAPI 应用层（Domain API / WebSocket）
│   └── web/                  # Workbench 前端（Vite + React + TypeScript）
├── music_agent_workbench_design.md   # 设计文档（架构事实来源）
├── examples/                 # 音乐分析/试听的合成 MIDI 验收材料与生成脚本
└── AGENTS.md                 # 本文件
```

## 3. 常用命令

```powershell
uv sync --all-packages        # 安装整个 workspace（含全部成员包与 dev 依赖）
uv run phonolite              # 启动冻结的历史 Phonolite Qt 应用
uv run workbench-server       # 启动 FastAPI（127.0.0.1:8000，带 reload）
opencode mcp list             # 验证项目级 music MCP 已连接（需先安装并登录 OpenCode）
ffmpeg -version              # 视频导入需要 FFmpeg 和 ffprobe（纯音频不需要）
uv run pytest                 # 运行 workspace 全部 Python 测试
uv run pyright                # 对整个 Python workspace 执行严格类型检查
uv run pre-commit install     # 首次 clone 后安装 Git pre-commit hook
uv run pre-commit run --all-files  # 手动执行与提交前相同的检查

cd apps/web
pnpm install                  # 首次安装前端依赖
pnpm dev                      # Vite dev server（:5173，代理 /api 与 /ws 到 :8000）
pnpm build                    # 类型检查 + 构建（提交前至少跑一次）
pnpm test                     # 标尺、媒体对齐与项目请求隔离测试（Node >=22.6）
```

## 4. 代码该放哪里（决策规则）

- **音乐领域逻辑**（Score IR、分析、变换、校验、渲染）→ `packages/music-core`。
  它不依赖任何 Agent 宿主、Web 框架或 UI，保持纯 Python、可单测。
- **HTTP/WebSocket 接口、会话、任务路由** → `apps/server`。保持薄层：
  只做参数校验、调用 music-core / memory-core、返回设计文档第 8.4 节的统一 Envelope。
- **Agent Runtime 与宿主 Adapter** → `packages/agent-runtime`。应用层只依赖
  `AgentRuntime` 协议；MVP-1 的首个实际宿主固定为 OpenCode，使用 CLI JSON 事件流并
  保持进程边界。不要把 OpenCode SDK 类型传入 Server 或领域核心。
- **Agent 音乐工具协议** → `packages/music-mcp`。它是 stdio MCP 到现有 Domain API 的
  薄代理，不复制 music-core / memory-core 逻辑。项目级 `opencode.json` 注册它，
  `.opencode/agents/` 定义 Analyze / Learn / Experiment 三种权限模式。
- **记忆与学习状态** → `packages/memory-core`。Raw Event 只追加，Observation、Claim、
  Project State、Learning State 都是可 replay 的 SQLite 投影；召回先由 Recall Planner
  分通道规划。长期偏好必须显式确认，未知 sensitivity 必须 fail-closed。
- **UI** → `apps/web`。聊天框不是唯一核心，选区/版本/试听/审批才是。
- **音频/MIR 分析** → `packages/audio-core`。保持纯 numpy/scipy、无 Qt、无音频
  I/O，这样 server 和未来 Agent 工具都能直接复用；新的采集、回放和可视化能力
  通过 Web/Server 实现，不再扩展 `apps/phonolite`。
- **不要向 `apps/phonolite` 添加功能**。它是冻结的历史参考实现，只允许修复导致
  无法启动、数据损坏或核心功能不可用的严重缺陷；一般重构、类型清理和 UI 改进也
  不应触碰它。后续产品开发默认采用 B/S 架构。
- **不要**创建设计文档里"暂时不做"的东西：自治多 Agent、VST3、知识图谱、
  通用向量库、完整音频转录。也不要提前把 `skills/`、`adapters/` 等目录一次性
  建全——按 MVP 路线（设计文档第 16 节）用到再建。

## 5. 编码约定

- Python 3.12（`>=3.12,<3.13`，全 workspace 统一）；src layout；hatchling 构建。
- 新 Python 包需在根 `pyproject.toml` 的 `[tool.uv.workspace] members` 注册，
  依赖方用 `[tool.uv.sources] xxx = { workspace = true }` 引用。
- 风格跟随现有代码：英文模块 docstring、`from __future__ import annotations`、
  dataclass + 类型标注、注释用英文。
- Pyright 以根 `pyproject.toml` 中的 strict 配置为准，覆盖活跃的 packages 与
  server（冻结的 `apps/phonolite` 不在强制类型门禁内）。所有函数参数和返回值必须
  标注类型；禁止裸 `dict`、`list`、`tuple` 等容器类型。领域数据优先使用
  dataclass、`TypedDict` 或明确的类型别名，不要让 `Any`/`Unknown` 穿过模块边界。
- 对 mido 等动态或类型信息不完整的第三方库，
  应在适配边界通过 `cast`、显式类型或运行时检查收窄。确需忽略时，只允许使用带
  具体规则名的最小范围 `# pyright: ignore[reportXxx]`，并在旁边说明原因；禁止
  整文件关闭 strict、无规则名的 `type: ignore` 或为了通过检查而扩大为 `Any`。
- 类型错误可能暴露真实逻辑错误，不能视为编辑器噪声。修改代码时应检查错误根因，
  尤其关注 Optional、容器元素、回调签名、动态库返回值和跨包 API。
- 设计文档与中文讨论用中文；代码、docstring、commit message 用英文。
- 测试：pytest，每个包的测试放在自己的 `tests/`（如 `packages/music-core/tests/`）；
  根 `pyproject.toml` 的 `testpaths` 需同步注册。
- 提交前：`uv run pyright` 与 `uv run pytest` 必须全绿；改了前端则 `pnpm build`
  通过。仓库的 `.pre-commit-config.yaml` 会在每次 commit 前对整个 Python
  活跃 Python workspace 执行 Pyright；首次 clone 或 hook 更新后运行
  `uv run pre-commit install`。

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
支持。

**进度**：设计文档第 17 节的前 8 个 issue（Score IR、MIDI round-trip、
project.yaml、基础分析、两种受控变换、diff、渲染）已完成，即 **MVP-0 离线音乐
核心已就位**——见 `packages/music-core` 的 `ir.py` / `io/midi.py` / `project.py` /
`analysis.py` / `validation.py` / `transform.py` / `diff.py` / `render.py`
（`uv run pyright` 与 `uv run pytest` 全绿）。

设计文档的正式路线为 **MVP-0 到 MVP-5，共 6 个阶段**；第 19 节纵向切片是步骤链，
不是额外的 MVP 阶段。

**当前优先级（2026-09-05）**：先完善音乐分析、受控实验和 FastAPI + Web UI 的实际
使用闭环，暂缓 MVP-3 FL Studio Bridge。仍不做自治多 Agent、VST3、完整音频转录或
复杂 MVP-4 编辑器。

**下一条纵向切片**：用户主要从歌曲/配乐等原曲音频开始扒谱和钢琴改编，实施依据为
设计文档第 24 节。近期先补音频听辨、草稿校正和保存重开；再接候选转录后端与钢琴
缩编。辅助扒谱在范围内，完整混音全部声部的自动还原仍不承诺。完成改编作品本身是
有效目标，不强制每次进入教学/练习流程。

**MVP-1 OpenCode Agent Runtime 已就位**：新增宿主无关的 `AgentRuntime` / `RuntimeTask` /
`RuntimeEvent` 协议与 OpenCode CLI Adapter，支持 JSON 事件流、session 续接、取消和进程
清理。`packages/music-mcp` 通过 stdio 向 OpenCode 暴露 10 个现有 Domain API 工具；
Analyze / Learn / Experiment 使用同一个主 Agent 的三个权限配置，默认拒绝内建文件、
Shell 和子 Agent 工具，Experiment 只能创建/渲染/比较实验分支，不能 accept 或 merge。
Server 提供 `POST /api/agent/tasks`、`GET /api/agent/tasks/{id}`、
`POST /api/agent/tasks/{id}/cancel`、`POST /api/agent/sessions/{id}/resume`，并由
`/ws?task_id={id}` 回放和推送事件。Web UI 的 OpenCode Agent 面板可直接选择三种模式、
查看工具调用/输出、取消或续接会话。真实 OpenCode 联调已验证 Analyze 调用确定性分析、
Experiment 创建新分支但不更新 active version、Learn 不改谱以及 session id 原样续接。

**MVP-1 薄接线层已就位**：`apps/server` 把 music-core 包成 Domain API，全部走
设计文档 8.4 的统一 Envelope。乐谱工具（设计文档 8.2）：`POST /api/score/import`
（base64 MIDI）、`GET /api/score/{id}`、`GET /api/score/{id}/inspect`、
`POST /api/score/compare`、`POST /api/score/transform`、`POST /api/score/{id}/render`、
`POST /api/score/{id}/export`、`GET /api/artifact/{token}`（下载渲染/导出产物）。
项目工具（设计文档 8.1）：`GET /api/project`、`PATCH /api/project/goal`、
`POST /api/project/decision`、`POST /api/project/accept`、`POST /api/project/choose`
（A/B 选择 + 决策记录的切片便捷端点，reason 作为轻量学习事件）。项目、版本、原件
和产物由 `persistence.py` 的 `SQLiteProjectStore` 持有，`store.py` 管理其生命周期。
第 19 节纵向切片（Import → Goal → Inspect → Delayed Bass Transform → Diff →
Render → A/B Choose → Decision）已由 `apps/server/tests/test_vertical_slice.py`
端到端跑通；当前 `uv run pyright` 与 `uv run pytest`（含多项目，共 176 项）全绿，前端有
9 项时轴/对齐/项目请求隔离测试。

**MVP-1 检查 UI 已提前就位**：`apps/web` 现可直接操作并检查上述纵向切片，包括
MIDI 导入、版本树、项目目标、可定位分析结论、受控变换、A/B semantic diff、
渲染/导出产物下载、候选选择与决策时间线。现有轻量 MIDI 钢琴卷帘负责音符显示、
拖选与播放定位；不包含五线谱排版、直接拖拽改音或完整谱面编辑。联调时分别运行
`uv run workbench-server` 与 `apps/web` 下的 `pnpm dev`，访问 Vite 打印的
`http://localhost:5173/`；`pnpm build` 已通过。

**MVP-2 记忆与学习状态已就位**：新增 `packages/memory-core`，以 SQLite `project.db`
保存不可变 Raw Event，并确定性投影 Observation、固定粗类型 Claim + Evidence/State/
Policy、Project State 与 Learning State。Recall Planner 按用户偏好、当前项目、近期项目
情节、学习状态独立检索和限额，默认不读取 Raw Event；未知 sensitivity 会进入 private
quarantine。A/B `choose` 会投影显式项目决策、项目状态、偏好 proposal（不会因一次选择
自动确认）和学习状态。Server 已提供 `memory_query` / `memory_propose_claim` /
`memory_confirm_claim` / `memory_record_episode` / `learning_record_outcome` 对应 API，
`packages/memory-core/tests/test_replay.py` 验证全部派生表可从事件账本重建。

## 8. 音乐分析与试听闭环

- `music_core/timing.py` 处理变拍号小节定位与速度图；区间采用半开区间，时值统计必须
  裁剪到选区。无拍号按 4/4 分段；拍号中途改变会结束当前不完整小节。
- `analysis.py` 增加相邻完整小节的十六分音符网格起音重复，以及逐小节三和弦/七和弦
  候选（最多三个），带音符 ID、位置、证据、置信度和替代解释。分析基于按键时值，
  不包含踏板共鸣；模板匹配不代表调性、功能和声或终止式识别。
- Score IR 保留 CC（含 CC64）、program change、pitch bend、pressure；不支持的 MIDI
  数据必须产生导入提示。变换保留控制事件的原时间，并提示用户检查踏板与新音符关系。
- `shift_note_onset` 只移动指定音符的起音，保留音高、时值、力度和其余材料；原有
  `delay_bass_resolution` 的实际语义是低音起音后移，不表示已识别和声解决点。
- `preview.py` 用 numpy 输出确定性的参考音色 PCM16 WAV，支持速度变化、力度、CC64，
  固定增益便于 A/B。不模拟真实钢琴，不渲染 program/bend/其他表情事件，MIDI 导出仍
  保留。每次最多五分钟、20000 音符，并限制累计发声时长。
- `render` 的 `auto` 优先外部合成器，失败后使用内置 `preview`；`midi` 必须显式指定。
  FluidSynth 可用 `WORKBENCH_SOUNDFONT` 配置音色库。音频端点支持 HTTP byte ranges。
- `GET /api/score/{id}` 返回摘要和音符分页，可选起止拍/音轨、`offset` + `limit`
  （默认 256，上限 1024），返回 `next_offset`。MCP `get_score` 使用相同接口。
- Web 可按音轨/拍区间分析、从结论定位音符、选择单音实验；变换后自动设置 A/B，
  两个音频互斥播放并支持同秒切换，也可分别从头播放。接受 A/B 才更新主版本。
- `apps/web/src/components/PianoRoll.tsx` 是默认可见的音乐工作区：SVG 音高/时值矩形、
  音轨颜色、小节/拍点标尺、分段缩放、拖选、点击音符、分析证据高亮、试听选区及播放线。
  按可见时间范围分页加载全部音符，超过 20000 个提示缩小窗口，不静默只显示第一页。
  卷帘选区与分析/变换表单共享范围；数值明细默认折叠，项目与 Agent 面板放到音乐区后。
- `pianoRollLayout.ts` 仅从已有 tempo/meter map 推导显示坐标，不承担音乐分析或修改。
  `pnpm test` 使用 Node 内置测试器验证小节边界、变拍号和播放秒数/拍点转换，无新增依赖。
- 手动验收：`uv run python examples/music_lab_demo.py` 生成八小节 MIDI；页面导入，
  检查和弦候选、移动一个旋律音、试听 A/B 并记录理由。示例是合成测试材料，不代表
  已完成真实作品的音乐质量评测。
- 新增自动测试为 `packages/music-core/tests/test_music_lab.py` 与
  `apps/server/tests/test_music_lab_api.py`。修改交互后还需浏览器实测。
- 乐谱/版本/产物及参考音频已持久化到本机 `project.db`，与记忆账本使用不同表。包构建
  readme 应位于包内或使用 inline text，避免新版 hatchling 拒绝父目录路径。

## 9. 音频扒谱与钢琴改编（R1 已实现，R2/R3 待实现）

- 分开保存参考原件、转录假设/确认状态和钢琴编配版本。原曲证据核对与有意的编配
  改动不能混为一谈；模型候选不自动成为事实，人工校正不得被重跑模型覆盖。
- 参考音频秒轴与乐谱 beat 轴通过显式锚点关联，考虑弱起、前奏与变速。原曲和改编
  的对照试听不能假定相同秒数对应相同乐句。
- R1 先实现音频导入/波形/循环降速、手动对齐、谱草稿增删改音、旋律/低音标注和
  持久化恢复；R2 再评估可取消的候选转录/分离任务；R3 做约束下的双手缩编与谱面输出。
- 跨度校验依据显式左右手/声部；不得只按音高高低猜测旋律、左右手，或把两手总跨度
  判成单手不可演奏。用户明确选择保留声部、难度和织体后再生成局部编配候选。
- audio-core 保持纯数值、无 Qt 和文件 I/O；解码/文件保存/后台任务在 Server，谱草稿
  与编配逻辑在 music-core，Web 负责听辨和确认交互。按切片需要添加模块，不预建大平台。
- R1 已提供参考音频导入、循环降速、锚点对齐、表单增删改音、旋律/低音/内声部标注、
  待核对/已确认状态及来源秒数。仍没有自动扒谱、音源分离、钢琴缩编或五线谱输出。

### R1 实现与验收

- `audio-core/dsp/waveform.py` 从已解码数组计算有限波形包络；Server 的 `assets.py`
  用 soundfile 解码 WAV/FLAC/OGG/MP3，保留原件并生成浏览器使用的 PCM16 WAV 副本。
  上传上限 64 MB、10 分钟、4000 万解码采样点，限单/双声道；不自动下载转录模型。
- `music-core/reference.py` 定义严格递增的秒↔拍锚点与音符来源；只在锚点覆盖区间内
  插值，不外推。`edit.py` 建空草稿、校正音符和绑定音频，每次创建新 ID 的版本。
  修改既有版本的对齐会产生新稿，并将改变的参考依据标为待核对。
- Score IR 增加 `length_beats`（保留空白稿/尾部休止）、`reference`、音符 `role` /
  `transcription_status` / `reference_evidence`。变换与 SQLite 原生 JSON 保存这些字段；
  MIDI 是交换格式，不负责保存确认状态和音频对齐。
- 新 API：`GET /api/references`、`POST /api/references/import`（base64 音频）、
  `PUT /api/references/{id}/alignment`、`POST /api/score/draft`、`POST /api/score/edit`、
  `POST /api/score/{id}/reference`。全部走统一 Envelope。
- `SQLiteProjectStore` 使用项目目录及按项目分区的版本、产物与参考材料表（详见第 10 节），
  与 memory-core 的账本表并存。每次修改提交后响应；版本只插入，不覆盖。默认路径
  为仓库 `project.db`，也可用 `WORKBENCH_DB_PATH` 指定；重启自动恢复最近编辑的
  `working_version`，正式 `active_version` 仍通过显式接受更新。
- `ReferencePanel` 管音频听辨、对齐和建稿；`NoteEditor` 管单音修订。原曲秒轴与谱稿
  beat 轴双向定位使用当前谱稿的对齐快照；修改参考资产上的锚点不会暗中改旧稿。
- 测试通过 `configure_project_store(tmp_path / "project.db")` 隔离；禁止重置实际项目
  数据库。重开测试校验原件字节、锚点、ID、确认状态、旧版本与产物可读。
- `uv run python examples/reference_audio_demo.py` 生成带一秒前导空白的参考 WAV；
  可把音频 1–7 秒对应到谱稿 0–8 拍，记音后校正并重启验证。示例是合成验收材料，
  不代表模型已自动扒谱或已完成真实歌曲的听辨质量评测。

### 视频参考材料（2026-09-06）

- R1 同时支持本地参考视频，用于观察琴键、手部和 MIDI 特效。`video.py` 在 Server
  通过 FFmpeg/ffprobe 生成浏览器 MP4（H.264/AAC，最长十分钟，最高 1920×1080），
  保留原视频字节；支持 MP4/MOV/MKV/WebM 等本地容器，输入和输出上限各 256 MB。
  路径可由 `WORKBENCH_FFMPEG` / `WORKBENCH_FFPROBE` 覆盖；纯音频仍不依赖这两个程序。
- 视频、波形和锚点统一采用预览视频的秒轴。相对音画时间戳保留，波形从同一预览提取，
  在开头/结尾补齐静音；不能把视频与音轨各自归零而消除原有延迟。无音轨的视频仍能
  导入、定位和建稿，但不伪造波形/音频。默认选择首路非封面视频和首路音轨。
- `POST /api/references/import-video` 接收 `video_b64` + `filename`。参考记录增加带默认
  值的 `media_kind` / `video_token` / 分辨率 / `has_audio`，旧音频 JSON 自动兼容，无
  破坏性数据库迁移。原件、视频预览与可选音频副本都以独立 artifact 保存，支持 Range。
- 前端共用媒体时钟，支持循环、0.25/0.5/0.75/1 倍速、暂停 ±0.05 秒移动、起止点标记、
  定位当前画面与同步卷帘播放线。±0.05 秒不是逐原始帧步进。悬浮对照可边看视频边记音。
  所有 audio/video 播放器统一互斥，避免视频和谱稿同时出声。
- 视频不执行自动琴键、手指或光条识别；画面只作为人工听辨证据，确认状态和版本审批
  仍沿用 R1。网络视频链接下载暂未实现。
- `examples/reference_video_demo.py` 生成合成 MIDI 瀑布视频作验收；真实 FFmpeg 测试覆盖
  MP4/MOV/MKV/WebM、延迟音轨、无声视频、原件保留、Range、重开恢复及旧音频兼容。

### 频段辅助听辨（2026-09-07）

- `ListeningEqPanel.tsx` / `listeningEq.ts` 在参考 audio/video 的同一播放时钟上提供
  三段 EQ、低/中/高频听辨预设和实际滤波器响应曲线；默认原声，可原位置切回核对。
  只衰减竞争频段（-24–0 dB），不自动分离声部、识别音符或确认转录。
- Web Audio 图由用户操作延迟创建，材料/项目切换释放；无声视频隐藏 EQ。参数仅本次
  听辨生效，不修改参考文件、锚点或谱稿。曲线表示增益，不是频谱或声部轨迹。
- 修改时验证真实滤波响应、原声恢复、循环降速、音视频播放和材料/项目切换；
  频段重叠与泛音使精确声部分离不可保证，未知音符仍应人工核对。
- `apps/web/tests/listeningEq.browser.cjs` 使用合成音频与模拟 API 做浏览器回归，不访问
  项目数据库。启动 Vite 后从仓库根运行 `node apps/web/tests/listeningEq.browser.cjs`；
  需可解析的 Playwright（或 `WORKBENCH_PLAYWRIGHT_PATH` 指向其模块），默认 Edge，
  可设 `WORKBENCH_BROWSER` 与 `WORKBENCH_WEB_URL`。覆盖滤波响应、StrictMode、原声
  切换、降速循环、材料切换及无声视频隐藏控件；真实作品听辨效果仍需人工验收。

## 10. 多项目工作区（2026-09-06）

- **项目**对应一首作品或一次改编任务，拥有自己的目标、参考音视频、谱稿、版本和决策；
  **版本**是一个项目内部的修改历史。新建项目不继承旧项目材料，导入文件不重命名项目。
- 新增 `GET /api/projects`、`POST /api/projects`、`POST /api/projects/{id}/open`、
  `PATCH /api/projects/{id}`，用于列表、新建、打开和重命名。项目工作方向可选原创/学习
  或扒谱/改编；迁移的旧项目不猜测方向。暂不提供项目删除、复制或多用户权限管理。
- SQLite schema v2：`wb_projects` 保存各项目配置，`wb_workspace` 记最后打开的项目；
  `wb_versions` / `wb_artifacts` 按 `project_id` 过滤，`wb_project_references` 以
  `(project_id,id)` 为主键，因此同一原件可在不同项目中使用不同锚点。`wb_schema`
  标记版本；`project_schema.py` 事务迁移旧单项目库，保留所有 ID、原件、版本和状态。
  旧 `wb_project` / `wb_references` 仅作为迁移来源保留，不再读写。升级真实库前先备份。
- 每个 HTTP 请求通过 `X-Workbench-Project` 或 URL `project_id` 绑定项目；不提供时
  在请求开始捕获最后打开的项目。项目目录接口不依赖某个项目。无项目的旧 Domain API
  调用仍可创建默认项目；新 UI 必须通过明确的新建入口开始。
- `ProjectApiContext` 提供固定项目的 `createApi(projectId)` 实例。切换时重挂工作区，
  清理选区、A/B、媒体和会话显示；上传/渲染等旧请求及其媒体 URL 仍绑定原项目，禁止
  用可变全局 project_id 让完成较晚的请求写进新项目。
- `active_project_id` 是当前打开的作品；项目里的 `working_version` 是最近编辑谱稿；
  `active_version` 是正式主版本，只能显式接受。三个概念不能合并。重开恢复所选项目及
  它的最近谱稿，版本浏览不等于更新正式主版本。
- Agent 任务固定 `project_id`，CLI 通过 `WORKBENCH_PROJECT_ID` 传给 MCP，MCP 客户端
  固定请求头。`wb_agent_sessions` 持久记录会话归属，禁止跨项目或未知归属的续接；旧会话
  未记录归属时需开始新会话。`GET /api/agent/tasks` 恢复本项目最近任务（任务事件仍仅在
  当前 Server 进程保留）；切回项目可继续观察/取消正在运行的任务。
- Workbench 的项目任务必须使用专属 CLI 进程；设置 `WORKBENCH_OPENCODE_ATTACH` 时
  会显式拒绝，因为共享宿主不能保证每个任务的 MCP 环境独立。手动使用 MCP 时可设置
  `WORKBENCH_PROJECT_ID`；应用创建的任务自动设置。WebSocket URL 同样携带 project_id。
- 测试覆盖旧库无损迁移、切换重开、同文件独立锚点、跨项目访问拒绝、导入中途切换、
  固定客户端、媒体 URL、任务/会话归属及 Runtime 环境传递；不要通过清空真实库验收。
