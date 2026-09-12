# Music Agent Workbench 设计文档

> 面向音乐创作学习、钢琴改编、参考作品分析与 DAW 协作的可扩展 Agent 系统  
> 状态：Draft v0.3
>
> 日期：2026-09-06

---

## 1. 项目概述

本项目希望把现代 Coding Agent 带来的高效率学习路径迁移到音乐创作领域。

目标用户具备较强的钢琴演奏、听觉判断和审美能力，但缺乏系统的作曲训练。传统学习常见的问题是：理论与创作脱节、反馈周期长、模糊听感难以转化为可执行修改、创作版本和学习成果难以持续积累；与此同时，通用大模型对复音音乐、长时结构和高级音乐分析的理解仍不稳定。

因此，本项目不以“自动生成完整音乐”为核心，而是建设一个类似 **Composition IDE** 的系统：

> 利用成熟 Agent Runtime 提供推理、工具调用、文件操作、权限、会话和任务执行能力；利用音乐领域核心提供 MIDI、MusicXML、音频、曲式、和声、动机、版本和 DAW 语义；通过长期记忆与项目状态，让 Agent 在创作过程中持续教学、分析、实验和记录。

目标补充（2026-09-05）：用户也经常希望从歌曲、配乐等原曲音频出发，完成听辨扒谱和
钢琴改编。产品因此有两条并列主线：原创创作与学习，以及参考作品的转录与钢琴改编。
用户可以选择以完成改编作品为目标，教学讲解和练习是可选支持，不是每次任务的必经步骤。
音频优先的下一条纵向切片、事实/改编边界与实施顺序见第 24 节。

---

## 2. 项目目标与非目标

### 2.1 核心目标

系统应帮助用户形成以下学习循环：

```text
创作意图
→ 拆解成音乐约束
→ 用户完成初稿
→ Agent 读取并分析
→ 提出一个主要问题
→ 创建受控变量实验
→ 渲染和 A/B 试听
→ 用户做审美选择
→ 记录项目决策与学习成果
```

具体目标：

1. 支持 MIDI、MusicXML、钢琴录音以及歌曲/配乐等参考音频；
2. 对乐谱和 MIDI 给出有证据的小节级分析；
3. 针对选区创建“只改变一个主要变量”的候选版本；
4. 比较版本差异，而不是简单宣称某一版更好；
5. 记录项目状态、创作决策、用户偏好和学习状态；
6. 逐步接入 FL Studio、Cubase 等 DAW；
7. 复用 Codex、OpenCode 等成熟 Agent Runtime；
8. 各领域模块与 Agent Host 解耦；
9. 自动结论尽可能附带来源、位置、置信度和替代解释；
10. 保护用户的核心审美决策，避免自动覆盖正式版本。
11. 从参考音频逐段听辨旋律、低音和必要和声，生成带来源和待核对状态的转录草稿；
12. 根据保留主题、双手分配、织体和演奏难度约束，完成可试听、可校正的钢琴改编；
13. 分开记录原曲证据、转录推测和有意的编配改变，支持单纯完成作品或伴随学习两种目标。

### 2.2 非目标

第一阶段不追求：

- 从任意混合音频中准确还原完整管弦总谱；
- 自动创作完整、成熟、可发行的作品；
- 由模型替代用户作出最终审美判断；
- 一开始支持所有 DAW 和插件格式；
- 构建新的通用 Agent Runtime；
- 建立复杂自治多 Agent 社会；
- 将所有记忆交给自由形式的 LLM 分类；
- 使用屏幕视觉自动化作为主要 DAW 控制方式；
- 实现完整实时低延迟音频处理。

---

## 3. 设计原则

### 3.1 Agent Runtime 与音乐领域逻辑分离

- **Agent Runtime**：会话、工具调用、权限、文件、Shell、上下文、取消、日志和恢复；
- **Music Domain Core**：音乐对象、分析、变换、验证和渲染；
- **Music Workbench**：乐谱、钢琴卷帘、时间线、试听、选区和人工审批；
- **Memory & Project State**：长期状态、项目事实、实验、决策和学习轨迹。

Agent Runtime 可以替换，Music Domain Core 不依赖特定宿主内部 API。

### 3.2 少生成，多诊断

默认教学行为：

1. 先让用户提供或完成初稿；
2. 先描述观察到的现象；
3. 再提出理论假设；
4. 每次只选择一个高价值问题；
5. 每个实验尽量只改变一个主要变量；
6. 候选数量默认不超过三个；
7. 用户决定是否接受候选。

上述“用户先写”是教学默认行为。参考作品任务中，用户提供原曲也构成有效起点；系统
可以按用户目标协助制作转录草稿或局部编配候选，不强制用户先写完一份 MIDI。

### 3.3 音乐结论必须可定位

重要分析应尽量包含：

- 小节和拍点；
- MIDI note、音名或声部；
- 音频时间范围；
- 使用的分析工具；
- 置信度；
- 可能的替代解释。

### 3.4 业务状态不依赖“做梦”

当前项目版本、拍号、核心动机、已接受决策、开放任务等属于业务状态，应通过显式工具和数据结构更新，而不是依赖 LLM 从聊天历史中自行总结。

### 3.5 卡片是显示形式，不是唯一存储原子

前端可以把记忆表现为卡片，但底层应区分：

- 原始事件；
- 观察；
- 命题；
- 证据；
- 可见性策略；
- 生命周期；
- 项目决策；
- 学习状态。

### 3.6 人在审美环路中

以下操作默认需要用户批准：

- 修改核心主题；
- 覆盖正式版本；
- 删除创作材料；
- 修改全曲结构或调性；
- 将实验分支合并至主版本；
- 写入长期审美偏好；
- 将局部选择推断为全局偏好。

---

## 4. 总体架构

架构决策：Workbench 统一采用 B/S 架构，浏览器端负责 UI 与交互，FastAPI 服务端
提供 Domain API 和 WebSocket。仓库中的 `apps/phonolite` 是冻结的历史 Qt 桌面应用，
只接受严重缺陷修复，不再承接新功能；其中可复用的音频算法继续沉淀到无 Qt 的
`packages/audio-core`，后续产品能力通过 Web/Server 暴露。

```text
┌─────────────────────────────────────────────────────┐
│                    Music Workbench                  │
│ 乐谱 / Piano Roll / 时间线 / A-B 试听 / 批注 / 审批 │
└──────────────────────┬──────────────────────────────┘
                       │ Domain API / WebSocket
┌──────────────────────▼──────────────────────────────┐
│               Python Application Layer             │
│ Chatbot / 人格 / 用户会话 / 任务路由 / API / UI状态 │
├──────────────────────┬──────────────────────────────┤
│ Memory & Project     │ Agent Runtime Adapter        │
│ State                │ OpenCode-first / replaceable │
└──────────────┬───────┴──────────────┬───────────────┘
               │                      │ MCP / JSON-RPC
┌──────────────▼──────────────────────▼───────────────┐
│                    Music Domain Core                │
│ Score IR / MIDI / MusicXML / 分析 / 变换 / 校验     │
├─────────────────────────────────────────────────────┤
│ External Backends                                   │
│ music21 / MuseScore / FFmpeg / FluidSynth / MIR     │
└──────────────────────┬──────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────┐
│                   DAW Adapter Layer                 │
│ FL Studio Bridge / Cubase Bridge / File Exchange   │
└─────────────────────────────────────────────────────┘
```

---

## 5. 建议仓库结构

```text
music-agent-workbench/
├── apps/
│   ├── chatbot/
│   ├── workbench-web/
│   └── local-service/
├── packages/
│   ├── music-core/
│   │   ├── domain/
│   │   ├── io/
│   │   ├── analysis/
│   │   ├── transforms/
│   │   ├── validators/
│   │   └── rendering/
│   ├── memory-core/
│   ├── project-state/
│   ├── agent-runtime/       # AgentRuntime 协议 + OpenCode CLI Adapter
│   ├── music-mcp/
│   └── shared-protocol/
├── adapters/
│   ├── fl-studio/
│   ├── cubase/
│   ├── musescore/
│   └── filesystem/
├── skills/
│   ├── composition-lesson/
│   ├── piano-draft-review/
│   ├── motif-experiment/
│   ├── reference-analysis/
│   └── version-comparison/
├── schemas/
├── tests/
│   ├── fixtures/
│   ├── memory-replay/
│   ├── music-golden/
│   └── integration/
└── docs/
```

建议保持单仓库，但边界明确。第一阶段以 Python 为主；性能敏感模块以后可替换为 Rust/C++ 服务。

---

## 6. Agent Runtime 策略

### 6.1 不自研通用 Agent Core

以下能力优先复用：

- 多轮会话；
- 工具调用循环；
- 文件读写和搜索；
- Shell 与子进程；
- 权限审批；
- sandbox；
- 取消和超时；
- 上下文压缩；
- streaming；
- 日志和错误恢复；
- MCP 客户端；
- Skills 和项目指令。

### 6.2 Runtime 抽象

```python
from dataclasses import dataclass
from typing import AsyncIterator, Protocol

@dataclass
class RuntimeTask:
    task_id: str
    prompt: str
    workspace: str
    session_id: str | None
    permission_profile: str
    tool_profile: str
    metadata: dict

@dataclass
class RuntimeEvent:
    type: str
    payload: dict

class AgentRuntime(Protocol):
    async def run(self, task: RuntimeTask) -> AsyncIterator[RuntimeEvent]:
        ...

    async def cancel(self, task_id: str) -> None:
        ...

    async def resume(
        self, session_id: str, prompt: str
    ) -> AsyncIterator[RuntimeEvent]:
        ...
```

上层业务只能依赖该接口，不直接依赖 Codex 或 OpenCode SDK。

### 6.3 OpenCode-first 接入

MVP-1 首个实际宿主固定为 OpenCode，用于快速验证：

- 自定义工具；
- MCP server；
- Agent/模式；
- Skills；
- 插件和事件钩子；
- 不同角色的工具权限。

Workbench 通过宿主无关的 `AgentRuntime` 调用 `opencode run --format json`，保留
OpenCode session id 并把流式事件转发到 WebSocket。OpenCode 以本地 stdio 方式启动
`music-mcp`；`music-mcp` 只代理现有 Domain API，不复制音乐业务逻辑。Analyze、Learn、
Experiment 是同一个主 Agent 的三个权限配置，不是自治多 Agent。

应用层任务接口为：

```text
POST /api/agent/tasks
GET  /api/agent/tasks/{task_id}
POST /api/agent/tasks/{task_id}/cancel
POST /api/agent/sessions/{session_id}/resume
WS   /ws?task_id={task_id}
```

任务事件会保留序号，WebSocket 晚订阅时先回放再推送实时事件；Server 关闭时必须取消
仍在运行的 OpenCode 子进程。项目级 `opencode.json` 只注册 `music-mcp`，三个模式的
工具白名单放在 `.opencode/agents/`，所有未列出的内建工具默认拒绝。

音乐逻辑仍应在 `music-core` 和 `music-mcp`，不要只写成 OpenCode 内部插件。

Agent Runtime 包含异步循环、权限、sandbox、子进程和流式事件，天然更适合作为独立
进程。进程隔离也便于取消、重启、版本固定和故障恢复。

### 6.4 后续 Runtime Adapter

Codex 保留为可替换的后续 Adapter，接入优先级为：

1. 官方 Python SDK；
2. Codex app-server JSON-RPC；
3. 必要时 fork app-server 增加 RPC；
4. 保持进程边界的自定义 Codex runtime；
5. 最后才考虑 PyO3 等原生 Python binding。

### 6.5 Chatbot 与 Runtime 职责

```text
Python Chatbot
├── 人格与对话风格
├── 用户身份与长期关系
├── 轻量普通聊天
├── 业务状态
├── 任务路由
└── 调用 Agent Runtime

Agent Runtime
├── 复杂任务规划
├── 文件和代码操作
├── 调用音乐工具
├── 长程执行
├── 并行或子任务
└── 生成结构化结果
```

普通聊天无需全部经过 Codex。只有需要复杂执行、项目操作或多工具协同时才委派。

---

## 7. Music Domain Core

### 7.1 统一 Score IR

```python
@dataclass
class NoteEvent:
    id: str
    track_id: str
    voice_id: str | None
    pitch: int
    onset_beats: float
    duration_beats: float
    velocity: int
    channel: int | None
    articulations: list[str]
    source_ref: str | None

@dataclass
class TempoEvent:
    beat: float
    bpm: float

@dataclass
class MeterEvent:
    beat: float
    numerator: int
    denominator: int

@dataclass
class ScoreDocument:
    id: str
    ppq: int
    notes: list[NoteEvent]
    tempos: list[TempoEvent]
    meters: list[MeterEvent]
    markers: list[dict]
    metadata: dict
```

原则：

- 内部时间统一用 beat 或有理数时间；
- 保留来源映射，可回到 MusicXML measure、MIDI tick 或 DAW clip；
- 音名和调性属于分析投影，不替代 MIDI pitch；
- 所有变换生成新版本，不原地覆盖正式材料。

### 7.2 音乐分析模块

第一阶段：

- 音域、密度、力度曲线；
- 旋律轮廓；
- 节奏型与重复；
- 同时发声音集合；
- 基础和弦候选；
- 低音线；
- 声部同向/反向运动；
- 乐句和停顿候选；
- 动机相似度；
- 小节级差异；
- 钢琴手跨度；
- 重叠、交叉和不可演奏候选。

后续：

- 调性区域；
- 罗马数字；
- 非和弦音；
- 终止式；
- 主题变形；
- 曲式分段；
- 配器与音色；
- 多模态音频证据。

分析输出：

```json
{
  "observation": "第 9–16 小节的音域、和声节奏和低音方向变化很小",
  "location": {
    "bars": [9, 16],
    "tracks": ["piano"]
  },
  "evidence": [
    {"metric": "register_range", "value": "7 semitones"},
    {"metric": "bass_contour_similarity", "value": 0.91}
  ],
  "interpretation": "重复感可能来自多个维度同时保持不变",
  "confidence": 0.82,
  "alternatives": [
    "重复感也可能是音色和演奏动态造成的"
  ]
}
```

### 7.3 音乐变换模块

```python
@dataclass
class TransformRequest:
    source_version_id: str
    region: dict
    operation: str
    parameters: dict
    preserve: list[str]
    vary: list[str]
    output_branch: str
```

第一阶段操作：

- transpose；
- octave displacement；
- rhythmic augmentation/diminution；
- bass replacement；
- register expansion；
- density reduction/increase；
- motif truncation；
- inversion；
- retrograde；
- voice reassignment；
- delayed resolution；
- controlled reharmonization。

每次变换输出：

- 新版本；
- diff；
- 修改说明；
- 验证报告；
- 可试听渲染。

### 7.4 验证模块

确定性校验优先于 LLM 判断：

- 小节时值；
- 音符越界；
- 声部重叠；
- 手跨度；
- 速度下的可演奏性；
- MIDI/MusicXML 一致性；
- 核心动机是否保留；
- 用户指定音是否被改动；
- 调号、拍号和小节线合法性；
- 输出文件可解析；
- 渲染是否成功。

验证器可以产生 warning，不擅自判定音乐“错误”。

---

## 8. 核心工具接口

MVP 工具控制在 8～12 个。

### 8.1 项目工具

```text
project_status
project_update_goal
project_record_decision
project_create_experiment
project_accept_variant
project_list_open_questions
```

### 8.2 乐谱工具

```text
inspect_score
extract_region
compare_versions
apply_transformation
check_playability
render_score
export_score
```

### 8.3 记忆工具

```text
memory_query
memory_propose_claim
memory_confirm_claim
memory_record_episode
learning_record_outcome
```

### 8.4 统一返回 Envelope

```json
{
  "ok": true,
  "result": {},
  "warnings": [],
  "artifacts": [],
  "provenance": {
    "tool": "inspect_score",
    "version": "0.1.0",
    "inputs": []
  }
}
```

---

## 9. Skills 与行为模式

第一版使用一个主 Agent 和三个模式，不做自治多 Agent。

### 9.1 Learn

- 明确当前学习目标；
- 优先让用户先写；
- 每次只指出一个主要问题；
- 设计小规模练习；
- 限制直接生成；
- 记录用户是否理解和掌握。

### 9.2 Analyze

- 读取指定选区；
- 输出可定位观察；
- 分离事实、解释和建议；
- 显示不确定性；
- 不自动修改文件。

### 9.3 Experiment

- 创建实验分支；
- 每个候选只改变一个主要变量；
- 最多三个候选；
- 自动渲染；
- 生成差异报告；
- 等待用户选择；
- 不自动合并主分支。

### 9.4 Skill 内容

每个 Skill 包含：

- 适用条件；
- 不适用条件；
- 输入要求；
- 执行步骤；
- 工具权限；
- 输出格式；
- 审批点；
- 失败降级；
- 评测样例。

---

## 10. 项目状态模型

### 10.1 项目目录

```text
project/
├── project.yaml
├── intentions/
│   ├── narrative.md
│   └── constraints.yaml
├── themes/
├── drafts/
│   ├── main/
│   └── experiments/
├── analyses/
├── references/
├── renders/
├── decisions/
├── learning/
└── project.db
```

### 10.2 `project.yaml`

```yaml
id: lake-tower
title: Lake Tower
active_version: v013

current_goal:
  description: 写出八小节逐渐失稳但尚未爆发的钢琴段落
  region:
    bars: [17, 24]

musical_context:
  meter: 9/8
  tempo_bpm: 72
  tonal_center: d_minor

preserve:
  - 主动机上行小二度
  - 九拍的大拍感

avoid:
  - 电影配乐式大和弦堆叠
  - 用单纯增密替代结构推进
  - 自动重写完整段落

learning_focus:
  - motif_development
  - harmonic_rhythm
```

### 10.3 版本与实验

```python
@dataclass
class ProjectVersion:
    id: str
    parent_id: str | None
    branch: str
    artifact_refs: list[str]
    created_by: str
    created_at: str
    status: str
    summary: str

@dataclass
class Experiment:
    id: str
    project_id: str
    hypothesis: str
    controlled_variable: str
    source_version_id: str
    variant_ids: list[str]
    user_choice: str | None
    user_reason: str | None
    status: str
```

---

## 11. 记忆系统设计

### 11.1 现有卡片式方案的主要风险

- 类别漂移；
- 同义分类碎片化；
- 临时状态被误记为长期偏好；
- 项目事实和用户事实混淆；
- scope、权限和语义绑定过紧；
- 更新、覆盖和冲突处理困难；
- 所有记忆在同一向量池竞争。

### 11.2 记忆流水线

```text
Raw Event（不可变）
    ↓
Observation（发生了什么）
    ↓
Claim Proposal（可能说明什么）
    ↓
Policy & Consolidation
    ↓
Confirmed Claim / Project State / Learning State
    ↓
Recall View
```

### 11.3 Raw Event

```python
@dataclass
class MemoryEvent:
    id: str
    event_type: str
    actor_id: str
    project_id: str | None
    payload: dict
    occurred_at: str
```

原始事件不可原地修改。

### 11.4 Observation

低推断描述：

```json
{
  "subject": "person:user",
  "event": "在 lake-tower 项目中选择了延迟低音解决版本",
  "context": "experiment:exp-017",
  "confidence": 1.0
}
```

### 11.5 Claim

```python
@dataclass
class MemoryClaim:
    id: str
    subject_type: str
    subject_id: str
    predicate: str
    value: dict
    context_type: str | None
    context_id: str | None
    claim_type: str
```

固定粗类型：

```text
fact
preference
goal
constraint
decision
relationship
procedure
skill
artifact_state
```

模型不能创建新的粗类型。

开放 tags：

```text
music
piano
harmony
delayed-resolution
lake-tower
```

tags 可由模型提出，但不直接决定权限和生命周期。

### 11.6 Evidence、State、Policy

```python
@dataclass
class ClaimEvidence:
    claim_id: str
    event_id: str
    excerpt: str | None
    extractor: str
    weight: float
    observed_at: str

@dataclass
class ClaimState:
    claim_id: str
    status: str
    confidence: float
    valid_from: str | None
    valid_until: str | None
    superseded_by: str | None
    last_confirmed_at: str | None

@dataclass
class MemoryPolicy:
    claim_id: str
    owner_id: str
    visibility: str
    sensitivity: str
    allowed_contexts: list[str]
```

状态：

```text
proposed
confirmed
weakened
contradicted
superseded
expired
context_limited
rejected
```

未知 sensitivity 应 fail-closed，默认 private/quarantine，而不是 public。

### 11.7 逻辑 Store

```text
User Profile Store
Project State Store
Episode Store
Learning Model
Task/Working State
Knowledge/Reference Store
```

可以共享 SQLite，但写入规则、生命周期、召回通道、配额和权限必须分开。

### 11.8 Recall Planner

```json
{
  "channels": [
    "user_preferences",
    "active_project",
    "recent_project_episodes",
    "learning_state"
  ],
  "entities": [
    "person:user",
    "project:lake-tower"
  ],
  "time_horizon": "long",
  "need_raw_history": false
}
```

各 channel 独立检索和限额，再统一排序。

### 11.9 音乐实验的多重投影

一个实验可以产生：

1. 项目决策；
2. 项目知识；
3. 偏好候选；
4. 学习状态；
5. 情节记忆。

偏好只先成为 proposal，不能因一次局部选择直接确认成全局偏好。

---

## 12. DAW 接入

### 12.1 DAW 的角色

DAW 是：

- 创作界面；
- 时间线和工程宿主；
- 输入输出端；
- 试听环境。

DAW 不是：

- Agent Runtime；
- 长期记忆数据库；
- 重型分析环境；
- 模型执行容器。

使用独立 sidecar：

```text
DAW Script / Plugin
        ↕ localhost WebSocket / HTTP / OSC
Python Local Service
        ↕
Music Core + Agent Runtime
```

### 12.2 Level 1：文件交换

```text
agent_exchange/
├── inbox/
│   ├── selection.mid
│   ├── selection.wav
│   └── context.json
└── outbox/
    ├── variant_a.mid
    ├── variant_b.mid
    └── report.json
```

先证明 Agent 的音乐价值，再做深度 DAW 自动化。

### 12.3 Level 2：轻量 Bridge

- 获取当前选区；
- 获取 tempo/meter；
- 发送选区 MIDI；
- 接收并插入候选；
- transport 控制；
- 创建实验 track/clip；
- 用户选择回传。

复杂工作全部在 DAW 外运行。

### 12.4 Level 3：原生 Workbench 插件

VST3/CLAP 或 DAW 面板：

- 当前选区；
- 分析；
- A/B 候选；
- 差异摘要；
- 批注和审批；
- 与外部 Agent service 通信。

不要假设 VST 插件可任意访问整个 DAW 工程。

### 12.5 FL Studio

优先作为 MIDI 编辑闭环的首个 DAW：

- MIDI Controller Scripting 使用 Python；
- Piano Roll Scripting 可创建、修改和删除音符、标记；
- 适合“选区 → Agent → 变体 → 回写”。

FL 侧脚本只负责桥接。

### 12.6 Cubase

Cubase MIDI Remote API 更适合：

- transport；
- track selection；
- MixConsole；
- Quick Controls；
- 触发宏和工作流。

第一阶段结合：

- MIDI Remote；
- 虚拟 MIDI；
- MIDI/MusicXML 文件交换；
- 外部 sidecar；
- 后续 VST3 面板。

### 12.7 DAW 协议示例

```json
{
  "project_id": "lake-tower",
  "selection": {
    "start_bar": 17,
    "end_bar": 24,
    "track_ids": ["piano-main"]
  },
  "transport": {
    "tempo": 72,
    "meter": "9/8"
  },
  "assets": {
    "midi": "selection.mid",
    "audio": "selection.wav"
  },
  "request": {
    "mode": "experiment",
    "preserve": ["melodic_contour"],
    "vary": ["bass_motion"]
  }
}
```

---

## 13. Music Workbench UI

```text
┌──────────────────────────────────────────────┐
│ Project / Version / Agent Mode               │
├─────────────────────┬────────────────────────┤
│ Score / Piano Roll  │ Analysis & Conversation│
│                     │                        │
│ 当前选区高亮         │ Observation            │
│ 版本差异高亮         │ Interpretation         │
│                     │ Suggested Experiment   │
├─────────────────────┴────────────────────────┤
│ A/B Transport / Waveform / Render Status     │
├──────────────────────────────────────────────┤
│ [Accept A] [Accept B] [Reject] [Annotate]    │
└──────────────────────────────────────────────┘
```

聊天框不是唯一核心。音乐任务更依赖选区、版本、播放、高亮、差异、可撤销操作和明确审批。

当前 Web 最小视图包含 MIDI 钢琴卷帘，默认显示在项目/Agent 表单之前。通过已有 Score
API 按可视时间窗口分页读取音符，以音轨颜色、音高位置和矩形长度表示 MIDI；标尺展示
原有拍号图对应的小节/拍点。拖选同步到分析与变换，点击结论定位并高亮音符；试听根据
速度图显示播放线，支持从选区起点播放并在末端停止。客户端仅推导显示坐标，不重复
核心音乐分析。数值表作为折叠明细保留；五线谱排版和直接拖拽编辑仍属于后续工作。

---

## 14. 安全、权限与审计

### 14.1 权限层级

```text
read_only
analysis_write
experiment_write
project_write
external_process
network_access
daw_control
```

### 14.2 修改隔离

- Agent 默认只能写 `experiments/`；
- 主分支只通过 `project_accept_variant` 更新；
- 原始用户演奏不可覆盖；
- 所有修改可追踪 parent version；
- 所有接受操作保留用户理由。

### 14.3 审计日志

记录：

- 谁调用工具；
- 输入和输出；
- 修改哪些 artifact；
- 模型和工具版本；
- 审批；
- 失败和回滚。

---

## 15. 测试与评测

### 15.1 音乐 Golden Tests

- 固定 MIDI；
- 固定 MusicXML；
- 固定预期分析；
- 固定变换后 note diff；
- 固定可演奏性 warning；
- 固定渲染成功条件。

### 15.2 Agent 行为测试

- 是否先分析再改写；
- 是否只改变指定变量；
- 是否保留用户约束；
- 是否不擅自合并主分支；
- 是否引用正确小节；
- 是否区分观察和解释；
- 是否在不确定时降低置信度。

### 15.3 记忆 Replay Benchmark

标注：

- 应写入哪些观察；
- 哪些不应长期记；
- 哪条 claim 应更新；
- 是否应产生冲突；
- 当前任务应召回哪些 channel；
- 哪些内容绝不能跨 scope 召回。

指标：

```text
write precision
write recall
duplicate rate
subject attribution accuracy
contradiction handling
cross-scope leakage
recall precision@k
decision usefulness
```

### 15.4 用户价值指标

- 用户完成小作品的比例；
- 每次会话实际接受的修改数量；
- 用户能否解释 A/B 差异；
- 同类问题是否逐渐减少；
- 是否形成可复用技术卡；
- 是否降低“知道不对但不知道怎么改”的频率。

---

## 16. MVP 路线（MVP-0 至 MVP-5，共 6 个阶段）

**执行优先级更新（2026-09-05）**：暂缓 FL Studio/Cubase Bridge，先确保音乐核心与
FastAPI + Web UI 可完成实际分析和试听实验。阶段编号不变，这轮完善 MVP-0/1 的音乐
能力及已有检查 UI，不提前建设完整 MVP-4 编辑器。

下一条产品纵向切片优先采用第 24 节的音频听辨与钢琴改编流程，补齐参考音频、草稿
校正和持久化，再接可替换的候选转录后端。辅助扒谱属于近期范围；完整混音自动还原
全部声部仍不是第一阶段承诺。

本轮验收范围：

- 变拍号、跨选区持续音与不完整小节的正确定位和统计；
- 相邻完整小节的起音网格重复；逐小节按音高集合和时值覆盖率给出至多三个和弦候选，
  不把模板匹配当作调性/功能和声/终止式识别；
- MIDI CC、program change、pitch bend 和 pressure 透传；不支持的数据显式提示；
- 音符分页与证据定位；单音起音位移实验（保留音高、时值、力度、其他音符）；
- 无外部工具时仍产生实际 WAV：numpy 参考音色预听处理速度图、力度与 CC64，固定增益；
  其余表情事件只保证 MIDI 保留，预听会提示限制；
- Web A/B 两版自动渲染、互斥播放、按秒切换、分别从头播放及显式选择 A/B；音频下载
  支持 HTTP byte ranges。测试验证 PCM 有信号、速度/踏板改变时长、单音实验改变音频；
- `examples/music_lab_demo.py` 可生成带踏板及变速的八小节合成验收材料。

实现位于 `music-core` 的 `timing.py` / `preview.py` 与现有 analysis/io/transform，
不把音乐逻辑写入前端或 Server。`render` 增加 `preview` 后端，`auto` 的最终后备改为
实际 WAV；显式 `midi` 仍用于文件交换。可通过 `WORKBENCH_SOUNDFONT` 配置 FluidSynth。
`GET /api/score/{id}` 增加起止拍、音轨及 offset/limit 音符分页，供 UI 与 MCP 共同使用。

**仍待解决**：真实作品评测、调性与更深层的和声分析；项目持久化已在第 24 节 R1 中实现。
内置预听不是采样钢琴；分析时值不包含踏板共鸣；节奏缩放时控制事件保持原位并提示。

### MVP-0：离线音乐核心

- 导入 MIDI；
- 转为 Score IR；
- 音域、密度、低音和节奏重复分析；
- 提取选区；
- 两种受控变换；
- FluidSynth/MuseScore 渲染；
- 版本 diff；
- 项目 YAML。

### MVP-1：Agent + 文件工作流

- AgentRuntime 抽象 + OpenCode Adapter；
- `inspect_score`；
- `compare_versions`；
- `apply_transformation`；
- `render_score`；
- Learn / Analyze / Experiment；
- 文件式 A/B；
- 显式项目决策。

### MVP-2：记忆和学习状态

- Raw Event；
- Observation；
- Claim；
- Project State；
- Learning State；
- Recall Planner；
- 实验结果投影；
- 记忆 replay tests。

### MVP-3：FL Studio Bridge

- Piano Roll 选区读取；
- 发送 MIDI/context；
- 导入候选；
- 用户选择回传；
- 创建实验 clip/channel；
- 非阻塞 sidecar 通信。

### MVP-4：Workbench UI

- Score/Piano Roll；
- 分析高亮；
- A/B 试听；
- 版本差异；
- 项目目标；
- 审批和批注。

### MVP-5：Cubase Bridge

- MIDI Remote 控制；
- 文件/虚拟 MIDI 交换；
- transport 和选轨；
- 外部 Workbench；
- 评估是否需要 VST3。

---

## 17. 首批 GitHub Issues

1. `core: define Score IR and stable event IDs`
2. `io: MIDI import/export round-trip`
3. `project: project.yaml schema and loader`
4. `analysis: register, density and bass contour`
5. `transform: delayed bass resolution`
6. `transform: rhythmic augmentation and diminution`
7. `diff: semantic score version comparison`
8. `render: FluidSynth or MuseScore audio render`
9. `protocol: tool result envelope`
10. `runtime: AgentRuntime interface`
11. `runtime: OpenCode CLI adapter`
12. `protocol: OpenCode music MCP adapter`
13. `skill: analyze selected score region`
14. `skill: controlled motif experiment`
15. `memory: immutable event store`
16. `memory: observation and claim schemas`
17. `memory: recall planner`
18. `learning: experiment outcome projection`
19. `daw: file exchange protocol`
20. `daw-fl: piano roll selection bridge`
21. `test: music golden fixtures`
22. `test: memory replay benchmark`

---

## 18. 主要风险

### 18.1 音乐学幻觉

缓解：

- 工具优先；
- 证据定位；
- 观察/解释分离；
- 置信度；
- 用户可纠正；
- 不把 LLM 结论直接写成项目事实。

### 18.2 系统替用户创作过多

缓解：

- Learn 模式限制生成；
- 用户先写；
- 每次一个变量；
- 候选数量限制；
- 正式版本需用户接受；
- 记录用户学会什么，而不只记录 Agent 写了什么。

### 18.3 记忆污染

缓解：

- 固定 claim 类型；
- 显式 subject；
- observation 与 claim 分离；
- 项目状态独立；
- 一次选择不直接确认长期偏好；
- replay benchmark；
- sensitivity fail-closed。

### 18.4 DAW API 不够开放

缓解：

- 先文件交换；
- sidecar；
- 统一协议；
- 虚拟 MIDI；
- 每个 DAW 薄适配；
- 不把核心能力绑定到某一 DAW。

### 18.5 Runtime 宿主变化

缓解：

- `AgentRuntime` abstraction；
- MCP；
- host-independent Skills；
- music-core 独立；
- 不 fork 宿主作为第一选择。

### 18.6 范围过大

缓解：

- 第一目标不是“音乐 AI 平台”；
- 第一目标是完成一次 8 小节受控实验；
- 每个里程碑必须有可试听输出；
- 真实使用反馈优先于架构完整性。

---

## 19. 推荐第一条纵向切片

> 用户导入一段 8 小节钢琴 MIDI，系统分析重复感，创建“仅改变低音解决时间”的两个候选，渲染 A/B，用户选择其一，系统记录项目决策和一次学习结果。

```text
MIDI Import
→ Score IR
→ Project Goal
→ Inspect
→ Delayed Resolution Transform
→ Semantic Diff
→ Render
→ A/B Selection
→ Project Decision
→ Learning Event
```

在它跑通之前，不建议投入：

- 完整音频转录；
- 自治多 Agent；
- VST3 插件；
- 知识图谱；
- Codex Rust binding；
- 复杂 UI；
- 多 DAW 同时支持。

---

## 20. 技术选型

### Python

- 应用层；
- MusicXML/MIDI；
- music21；
- Agent orchestration；
- Web API；
- 记忆和项目状态；
- 快速迭代。

### Rust

暂不作为 Codex Python binding，后续适合：

- 高性能 MIDI/音频处理；
- 实时 sidecar；
- VST3/CLAP；
- 可靠本地服务；
- 性能敏感 diff/analysis。

### SQLite

适合第一阶段：

- 项目元数据；
- 版本；
- 实验；
- 记忆；
- FTS；
- 审计；
- 单用户本地工作流。

向量检索后加，不应成为唯一召回机制。

### 外部工具

- `music21`：乐谱和基础音乐理论；
- MuseScore CLI：MusicXML 和谱面渲染；
- FluidSynth：快速 MIDI 音频渲染；
- FFmpeg：音频格式和切片；
- librosa / Essentia：音频特征；
- Basic Pitch 等：可选初步转录；
- Demucs 等：可选声部分离。

---

## 21. 公开扩展能力参考

实现时需重新核对具体版本。

1. OpenAI Codex SDK  
   https://developers.openai.com/codex/codex-sdk

2. Codex Skills  
   https://developers.openai.com/codex/build-skills

3. Codex MCP Server  
   https://developers.openai.com/codex/mcp-server

4. OpenCode MCP  
   https://opencode.ai/docs/mcp-servers/

5. OpenCode Custom Tools  
   https://opencode.ai/docs/custom-tools/

6. OpenCode Agents  
   https://opencode.ai/docs/agents/

7. FL Studio Piano Roll Scripting  
   https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/pianoroll_scripting_api.htm

8. FL Studio MIDI Scripting  
   https://www.image-line.com/fl-studio-learning/fl-studio-online-manual/html/midi_scripting.htm

9. Steinberg MIDI Remote API  
   https://steinbergmedia.github.io/midiremote_api_doc/

10. MIDI Remote API Reference  
    https://steinbergmedia.github.io/midiremote_api_doc/codedoc_api_reference/

---

## 22. 架构决策摘要

### 应该做

- MVP-1 先复用 OpenCode Agent Runtime，并保留 Codex 等后续 Adapter；
- 建立宿主无关的 Music Core；
- 使用 MCP/JSON-RPC/CLI 暴露音乐工具；
- 保留 Python Chatbot 的人格、记忆和业务状态；
- 将项目状态与通用记忆分离；
- 将记忆拆成事件、观察、命题、证据、状态和策略；
- 优先实现 MIDI/MusicXML；
- 优先做受控实验和 A/B；
- 先接 FL Studio Piano Roll；
- Cubase 使用 sidecar、文件、虚拟 MIDI 和 MIDI Remote 的组合；
- 所有正式创作修改保留人工审批。

### 暂时不做

- 从头开发通用 Agent Runtime；
- 直接绑定 Codex 内部 Rust crate；
- 让 LLM 自由维护记忆分类本体；
- 用一个通用向量库承载全部状态；
- 一开始做完整音频理解；
- 一开始做多 Agent；
- 一开始做 VST3；
- 一次生成整首作品；
- 自动把局部选择升级为长期偏好。

---

## 23. 一句话定义

> Music Agent Workbench 是一套建立在成熟 Agent Runtime 之上的音乐创作与改编环境：连接原曲音频、乐谱、MIDI、项目版本和学习状态，帮助用户完成原创作品、逐段扒谱和可演奏的钢琴改编，并通过有证据的分析、受控实验和试听选择积累音乐能力。

---

## 24. 原曲音频 → 辅助扒谱 → 钢琴改编（R1 已实现，R2/R3 待实现）

### 24.1 使用目标与入口

用户主要从歌曲、配乐等原曲音频开始，也允许已有 MIDI/MusicXML 作为辅助材料。
参考输入也包括演奏视频、键盘/MIDI 可视化视频；视频画面与声音共同辅助人工判断。
系统应支持“帮我做出改编”与“陪我分析学习”两种任务意图。它们复用现有 Analyze /
Learn / Experiment 权限模式，不因此增加自治 Agent 或独立宿主。

```text
导入参考音频 → 选择一段乐句 → 循环/降速听辨 → 标记拍点与小节
→ 建立旋律、低音及关键和声草稿 → 用户校正不确定处
→ 指定钢琴改编目标 → 创建双手编配候选 → 原曲/草稿/候选对照试听
→ 保留选择及理由 → 保存、重开、导出
```

可先处理 20–40 秒或约 4–8 小节；允许从已确认的主旋律和低音开始编配，不要求先把
整个混音的所有乐器转录完毕。

### 24.2 三类材料与两类判断

1. **参考原件**：原始音频文件及内容标识，保留原字节。分离音轨、片段、降噪结果是
   可追踪的派生材料，不能替换原件。
2. **转录草稿**：对原曲音符、节奏、低音、和声的假设。证据记录音频资产、起止秒数、
   声部、工具/模型版本和置信度；区分 inferred / confirmed / rejected，允许只确认一段。
3. **钢琴改编**：基于已知或暂定材料创建的新 Score IR 版本。保留来源版本和关联音符，
   记录删去、移八度、重新分配双手或替换织体等有意改变。

“原曲这里是哪个音”属于证据核对；“为了钢琴效果换成哪个音/织体”属于编配决策。
拒绝一个编配候选不等于推翻原曲转录；一次局部取舍也不能自动成为长期偏好。
原始音频本身可作为事实材料，但模型音符和和弦候选不能未经确认就写成项目事实。

音频使用秒轴，乐谱使用 beat 轴。通过显式的秒数↔拍点锚点关联；R1 先支持片段首拍与
后续拍点手动标记，必要时增加中间锚点。不能默认音频第 0 秒就是第一小节，也不能用
一个固定 BPM 对齐带前奏、弱起、变速或自由速度的整首作品。未知拍号/对齐状态需显式显示。

### 24.3 Web 工作区的最小布局

- 上方：参考音频波形、秒数选区、循环、保持音高的降速播放及对齐锚点；
- 中间：转录草稿的钢琴卷帘，按主旋律/低音/内声部标记，显示已确认与待核对部分；
- 旁侧：Agent 针对当前片段的证据、候选音和待确认问题；
- 下方：钢琴改编候选及差异，切换原曲、转录草稿和改编渲染，定位同一乐句。

R1 已增加新建空草稿，以及表单增音、删音、改音高、改时值、调整节奏等最小修订能力，
所有修订产生新版本。应保留用户编辑
与模型候选的区别。按键时值、踏板共鸣和谱面记谱时值也需区分。

原曲与钢琴版本音色、动态、时值可能不同，A/B 首先比较旋律、低音、节奏、张力和段落
结构的保留程度；不要把制作响度或配器厚度直接当作改编好坏。试听对应关系依赖锚点，
不沿用两份同源 MIDI 的“相同秒数就是相同位置”假设。

### 24.4 钢琴改编需要明确的约束

每段先确定需要保留的内容：主旋律、低音走向、特征节奏、重要对位或标志性动机；再
决定可简化的内声部和配器细节。用户可指定独奏/伴奏、忠实程度、演奏难度、单手跨度、
是否允许八度加厚与琶音化等目标。难度与跨度属于本项目约束，不自动记录为全局能力上限。

第一批受控编配操作按需实现：

- 明确选择来源声部并映射到左右手；
- 在保留旋律、低音的前提下删减重复加倍与次要内声部；
- 对选定声部移八度或重排和弦，比较音区和旋律突出程度；
- 对一段伴奏尝试柱式/分解式等一个主要织体变化。

校验应依据显式的手/声部标注检查同时跨度、速度下的跳跃和音符密度。不能仅以最高音
作为旋律、最低音作为左手，或把整个钢琴织体的音域当作单手跨度。合理的连奏、踏板、
交叉与琶音要保留人工判断点，警告不能代替演奏可行性的最终判断。

### 24.5 实施顺序与验收

**R1：能实际使用的听辨与校正工作台（已实现）。**

- 参考音频导入、波形、片段循环和降速；
- 手动拍点锚定，与卷帘定位联动；
- 新建/导入转录草稿、逐音校正、主旋律/低音标注；
- 参考原件、草稿版本、对齐和确认状态保存并可重开；
- 对照播放原曲片段和草稿，导出 MIDI。

验收：从一段真实参考音频完成一个约 4–8 小节的旋律/低音草稿，能标注不确定处、修正
一个音、反复对照听，并在服务重启后恢复相同材料和状态。无需先安装转录模型即可验收。

**R2：有证据的候选转录。**

局部谱图与音高证据先复用/完善 `audio-core` 的确定性特征。可选转录模型及音源分离
作为后续独立、可取消的后台任务，仅产生派生材料和带来源的候选；使用实际歌曲/配乐
片段评测后再确定后端。保存模型配置、误差和用户修订，避免每次推理覆盖人工校正。

验收关注人工修订耗时、漏音/多音、八度与起止时间错误，以及听辨是否更容易，而不仅
是“模型产生了 MIDI”。频谱峰与 chroma 能量不直接等于确定音符。

**R3：可演奏的钢琴改编与谱面输出。**

基于校正后的关键声部按约束做局部缩编，给出最多两个候选；保留原曲→转录→编配的
来源关系，并检查双手可演奏性。随后增加 MusicXML 和五线谱预览/导出。记谱量化、
声部/左右手、休止与延音线需要独立处理，不能把钢琴卷帘截图当作正式琴谱。

这些是原有 MVP 路线内的产品纵向切片，不增加新的 MVP 编号；DAW Bridge 继续暂缓。

### 24.6 架构边界与工具依据

- `audio-core`：波形/谱图/音高等纯数值特征，不做文件 I/O 或引入 Qt；
- `music-core`：转录来源映射、可版本化的谱草稿修订、编配变换、验证和记谱导出；
- `apps/server`：参考文件与项目持久化、音频解码、异步后端任务和统一 Domain API；
- `apps/web`：波形/谱面/卷帘、循环试听、对齐与校正交互；
- `memory-core`：已确认的项目决策与可选学习结果；不承担原始音频存储；
- `music-mcp`：按需要把已有 API 暴露给现有 Agent，不复制音乐逻辑。

工具依据（2026-09-05 核对）：Spotify Basic Pitch 支持复音音频到 MIDI，但官方明确
说明更适合一次处理一种乐器；据此只把它视为可选草稿后端，不据此承诺歌曲混音的完整
准确转录。浏览器保持音高降速可使用 playbackRate/preservesPitch，需验证目标浏览器
在所选速度下的听辨效果。

- [Basic Pitch 官方仓库](https://github.com/spotify/basic-pitch)
- [MDN preservesPitch](https://developer.mozilla.org/en-US/docs/Web/API/HTMLMediaElement/preservesPitch)

R1 的参考音频听辨、手动校正和保存恢复已经实现；候选转录、音源分离、钢琴缩编及
MusicXML/五线谱输出仍待开发。不能将手工扒谱工作流描述为自动转录已经完成。

### 24.7 R1 当前实现约定

参考原件以内容哈希识别，与解码得到的浏览器试听 WAV 一起持久化。音频解码位于 Server，
波形包络在 audio-core 计算；两者均不依赖 Qt。文件导入限制为 64 MB、10 分钟、4000 万
采样点、单/双声道。已验证 WAV、FLAC、OGG、MP3，未承诺其他容器自动转换。

`ScoreReference` 保存资产 ID 和至少两个、最多 64 个严格递增锚点。新谱稿第一锚点的
beat 为 0，但对应音频秒数可以非零；分段 BPM 限 10–600。每份谱稿保存对齐快照，
依据锚点生成 tempo map。谱稿中的来源秒数只在有锚点覆盖时建立；超出范围保持未对齐。
重新对齐通过新版本实现，改变参考依据时重置相应听辨确认状态。

原生 Score IR 的 `length_beats` 保存空白草稿和休止区间；`reference` 保存对齐。音符
增加 `role`、`transcription_status` 和 `reference_evidence`，用于角色、待核对/已确认
及来源位置。增删改音保留旧版本及已有音符 ID。MIDI 保留音符、演奏控制与结束时长；
原生确认状态和音频来源保存在项目库中。

SQLite 的项目目录及按项目分区的版本/产物/参考表（见第 25 节）与记忆事件
账本共用数据库但保持职责分离，默认 `project.db`，支持 `WORKBENCH_DB_PATH`。服务重启
恢复完整 IR、音频、锚点与最近的 `working_version`；它与正式 `active_version` 分开。

Web 上方为参考波形、循环降速、对齐锚点；下方卷帘与记音表单支持单音修订。原曲与
卷帘可以互相定位；原曲播放与谱稿播放互斥。当前支持多项目工作区（见第 25 节），尚不包含
自动扒谱和正式谱面编辑器。验收示例与自动化测试验证的是流程、音频与数据恢复，不等同
于已经证明真实歌曲上的自动音乐理解质量。

### 24.8 视频辅助听辨（2026-09-06，已实现）

参考材料支持本地演奏视频或带 MIDI 可视化的视频。用户观察琴键、手部动作、光条，
结合声音校正谱稿；视觉线索同样需要确认，不能将特效颜色、遮挡的手势或按键动作
自动当成准确的音高/力度/发声证据。剪辑或特效自身的延迟需通过听辨和锚点核对。

Server 使用 FFmpeg/ffprobe 将本地视频制作为浏览器可播放的 H.264/AAC MP4，最高
1920×1080，保留原视频字节与哈希。支持 MP4/MOV/MKV/WebM 等本地容器；上传与预览
各不超过 256 MB、时长不超过十分钟。解码/转码有超时和本地输入格式/协议限制；缺少
FFmpeg 时报告错误，不影响原有纯音频流程。不自动获取网站视频或加载视觉转录模型。

参考记录使用 `media_kind=audio|video`，增加 `video_token`、预览尺寸和 `has_audio`，
保留原有 `playback_token` 作为音频副本（无声视频为 null）。缺少新字段的旧 JSON 默认为
audio，继续使用原有数据库表，无破坏性迁移。视频导入 API 为
`POST /api/references/import-video`，返回同一 Reference Envelope。

视频作为显示时钟，音频波形从同一预览提取；相对音画时间戳保留，开头延迟和末尾静音
不被删掉。不能分别把视频和音频的第一帧归零。对齐锚点与音符来源秒数均基于参考预览
秒轴，继续遵守锚点范围内插值和草稿快照规则。无声视频仍可用画面标记拍点。

Web 支持视频播放/暂停/全屏、0.25–1 倍速、循环片段、±0.05 秒微移、当前位置设为
起止点、定位当前画面到谱稿。微移按秒定位，不承诺变帧率素材的逐原始帧步进。
“悬浮对照”让用户滚到记音区后仍能看画面；“同步谱稿播放线”按当前稿的锚点跟随媒体
位置。所有参考视频、参考音频和谱稿播放器使用统一的互斥播放规则。

测试包含真实 FFmpeg 容器转换、延迟音轨保留、无声视频、Range 下载、原件不变、旧
音频兼容和重开恢复。`examples/reference_video_demo.py` 生成合成 MIDI 瀑布视频作
浏览器验收，不代表已实现从视频自动识别 MIDI。

时间戳处理参考：[FFmpeg 文档](https://ffmpeg.org/ffmpeg.html)。

---

### 24.9 频段辅助听辨（2026-09-07）

为逐音忠实扒谱提供播放端 EQ：低/中/高频预设、三段频率与衰减调节、对数频率响应曲线，
可在同一播放位置切回原声。通过衰减竞争频段突出目标，不自动补写伴奏或确认音符。
频段不等于声部：基音、泛音与其他音符重叠，EQ 不能保证分离声部或精确还原；必须回听
原声核对，不确定处保持待核对。响应曲线是滤波器增益，不是频谱或自动旋律轨迹。

Web Audio 的 MediaElementAudioSourceNode 接入当前参考 audio/video，串联低搁架、
中频钟形、高搁架 BiquadFilterNode；增益范围 -24–0 dB，平滑切换参数，默认原声。
同一媒体时钟继续负责循环、保持音高降速及视频同步。仅在用户操作后建立音频图；
每个材料独立生命周期，切换材料或项目释放音频图并恢复默认设置，无声视频不显示 EQ。
试听参数只在当前页面保存，不修改原件、产物、锚点、谱稿或确认状态；不产生派生文件。
这属于 R1 播放辅助，R2 的候选转录与音源分离仍待实现。

## 25. 项目与版本的分层（2026-09-06，已实现）

一个项目对应一首作品或一次扒谱/改编任务，包含目标、参考材料、谱稿、版本、决策和
关联会话。一个版本表示该项目内部一次修改后的完整 Score IR。新项目从空白开始；
导入 MIDI/音视频只是向当前项目增加材料，不创建新项目，也不改变项目名称。

Web 顶部提供项目选择、新建和重命名，明确区分原创/学习与扒谱/改编两种工作方向。
左侧“本项目版本”只列当前项目的修改历史。切换项目清理临时播放、选区、A/B 和会话
显示，恢复目标项目最近谱稿。尚未添加项目删除、复制或多用户权限管理。

API：`GET /api/projects`、`POST /api/projects`、`POST /api/projects/{id}/open` 和
`PATCH /api/projects/{id}`。目录可在完全没有项目时返回空列表；无项目的旧 Domain API
调用保留默认项目兼容行为，新 UI 使用显式创建流程。

数据库 schema v2 由 `project_schema.py` 事务迁移：旧单项目及全部版本/产物/参考材料
保留原 ID 和字节，登记到 `wb_projects`，最后打开项登记到 `wb_workspace`。
`wb_versions` / `wb_artifacts` 增加 project_id；`wb_project_references` 使用
(project_id,id) 复合主键，同一源文件可在不同项目拥有独立锚点。旧单例表保留作迁移来源，
活动代码不再使用。`wb_schema` 明确版本，未知版本拒绝打开，迁移前备份真实库。

每个 HTTP 请求通过 `X-Workbench-Project`（媒体/WS 使用 project_id 查询参数）固定
所属项目；未指定时在请求开始捕获最后打开的项目。后续切换不能改变进行中的导入、渲染
或工具调用的归属。客户端按项目创建不可变 API 实例，不依赖可变全局项目 ID。跨项目的
版本、参考与产物查找必须拒绝。项目范围用于本地资料隔离，不替代未来的多用户鉴权。

工作区当前项目 active_project_id、项目最近编辑稿 working_version、项目正式主版本
active_version 是三个独立状态。新建/打开项目更新第一项；手动编辑更新第二项；明确
接受版本才更新第三项。新项目创建不会复制旧项目的任何状态。

Agent 任务携带固定 project_id，经 RuntimeTask.metadata → CLI 的 WORKBENCH_PROJECT_ID
→ MCP 请求头传递。wb_agent_sessions 保存会话归属；未知归属或跨项目的 session 不能
续接。GET /api/agent/tasks 恢复本项目最近的进程内任务，切回项目时仍可观察和取消。
共享 OpenCode attach 服务无法保证每任务 MCP 环境隔离，项目任务在该配置下明确拒绝，
使用专属 CLI 进程。Server 重启后的任务事件恢复尚未实现，会话归属仍持久保存。

验收包括旧库迁移、新建/切换/重命名/重开、目标/材料/版本/决策隔离、同源文件的独立
锚点、导入中途切换、旧客户端仍写回原项目、媒体/WS 范围以及 Agent 会话和环境绑定。
