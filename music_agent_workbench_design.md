# Music Agent Workbench 设计文档

> 面向音乐创作学习、钢琴改编、参考作品分析与 DAW 协作的可扩展 Agent 系统  
> 状态：Draft v0.1  
> 日期：2026-07-27

---

## 1. 项目概述

本项目希望把现代 Coding Agent 带来的高效率学习路径迁移到音乐创作领域。

目标用户具备较强的钢琴演奏、听觉判断和审美能力，但缺乏系统的作曲训练。传统学习常见的问题是：理论与创作脱节、反馈周期长、模糊听感难以转化为可执行修改、创作版本和学习成果难以持续积累；与此同时，通用大模型对复音音乐、长时结构和高级音乐分析的理解仍不稳定。

因此，本项目不以“自动生成完整音乐”为核心，而是建设一个类似 **Composition IDE** 的系统：

> 利用成熟 Agent Runtime 提供推理、工具调用、文件操作、权限、会话和任务执行能力；利用音乐领域核心提供 MIDI、MusicXML、音频、曲式、和声、动机、版本和 DAW 语义；通过长期记忆与项目状态，让 Agent 在创作过程中持续教学、分析、实验和记录。

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

1. 支持 MIDI、MusicXML 和钢琴音频等常用材料；
2. 对乐谱和 MIDI 给出有证据的小节级分析；
3. 针对选区创建“只改变一个主要变量”的候选版本；
4. 比较版本差异，而不是简单宣称某一版更好；
5. 记录项目状态、创作决策、用户偏好和学习状态；
6. 逐步接入 FL Studio、Cubase 等 DAW；
7. 复用 Codex、OpenCode 等成熟 Agent Runtime；
8. 各领域模块与 Agent Host 解耦；
9. 自动结论尽可能附带来源、位置、置信度和替代解释；
10. 保护用户的核心审美决策，避免自动覆盖正式版本。

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
│ State                │ Codex / OpenCode / Legacy    │
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
│   ├── agent-adapters/
│   │   ├── codex/
│   │   ├── opencode/
│   │   └── legacy/
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

### 6.3 Codex 接入优先级

1. 官方 Python SDK；
2. Codex app-server JSON-RPC；
3. 必要时 fork app-server 增加 RPC；
4. 保持进程边界的自定义 Codex runtime；
5. 最后才考虑 PyO3 等原生 Python binding。

Agent Runtime 包含异步循环、权限、sandbox、子进程和流式事件，天然更适合作为独立服务。进程隔离也便于重启、版本固定和故障恢复。

### 6.4 OpenCode 接入

OpenCode 可作为早期实验宿主，用于快速验证：

- 自定义工具；
- MCP server；
- Agent/模式；
- Skills；
- 插件和事件钩子；
- 不同角色的工具权限。

音乐逻辑仍应在 `music-core` 和 `music-mcp`，不要只写成 OpenCode 内部插件。

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

## 16. MVP 路线

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

- Codex 或 OpenCode Adapter；
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
11. `runtime: Codex adapter`
12. `runtime: OpenCode MCP adapter`
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

- 复用 Codex/OpenCode 等 Agent Runtime；
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

> Music Agent Workbench 是一套建立在成熟 Agent Runtime 之上的音乐创作学习环境：它把乐谱、MIDI、音频、DAW、项目版本、创作实验与长期学习状态连接起来，让用户通过可定位分析、受控变量修改和 A/B 试听，逐渐获得真实的音乐创作能力，而不是只获得 AI 生成的成品。
