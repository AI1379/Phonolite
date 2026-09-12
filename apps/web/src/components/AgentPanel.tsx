import { useProjectApi } from "./ProjectApiContext";
import { useCallback, useEffect, useRef, useState } from "react";

import { errMsg } from "../api";
import type { AgentMode, AgentTask, AgentTaskEvent } from "../types";
import { Button, Section, Tag } from "./common";

const TERMINAL = new Set(["runtime.completed", "runtime.cancelled", "runtime.error"]);

const MODE_HELP: Record<AgentMode, string> = {
  analyze: "只分析，不修改乐谱",
  learn: "围绕当前材料讲解一个重点",
  experiment: "创建受控分支，不自动接受",
};

function asObject(value: unknown): Record<string, unknown> | null {
  return typeof value === "object" && value !== null
    ? (value as Record<string, unknown>)
    : null;
}

function eventText(event: AgentTaskEvent): string | null {
  if (event.type !== "text") return null;
  const part = asObject(event.payload.part);
  return part && typeof part.text === "string" ? part.text : null;
}

function toolSummary(event: AgentTaskEvent): string | null {
  if (event.type !== "tool_use") return null;
  const part = asObject(event.payload.part);
  if (!part || typeof part.tool !== "string") return null;
  const state = asObject(part.state);
  const status = state && typeof state.status === "string" ? state.status : "running";
  return `${part.tool} · ${status}`;
}

export function AgentPanel({
  enabled,
  onError,
  onProjectChanged,
}: {
  enabled: boolean;
  onError: (message: string) => void;
  onProjectChanged: () => Promise<void>;
}) {
  const api = useProjectApi();
  const [mode, setMode] = useState<AgentMode>("analyze");
  const [prompt, setPrompt] = useState("");
  const [task, setTask] = useState<AgentTask | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const socketRef = useRef<WebSocket | null>(null);
  const actionsRef = useRef(0);

  const syncTask = useCallback(
    async (taskId: string) => {
      try {
        const current = (await api.agentTask(taskId)).result.task;
        setTask(current);
        setSessionId(current.session_id);
        if (current.mode === "experiment" && current.status === "completed") {
          await onProjectChanged();
        }
      } catch (error) {
        onError(errMsg(error));
      }
    },
    [onError, onProjectChanged],
  );

  const connect = useCallback(
    (taskId: string) => {
      socketRef.current?.close();
      const socket = new WebSocket(api.agentSocketUrl(taskId));
      socketRef.current = socket;
      socket.onmessage = (message) => {
        let event: AgentTaskEvent | null = null;
        try {
          const parsed = JSON.parse(String(message.data)) as AgentTaskEvent;
          if (typeof parsed.sequence === "number") event = parsed;
        } catch {
          event = null;
        }
        if (!event) return;
        setTask((current) => {
          if (!current || current.task_id !== taskId) return current;
          if (current.events.some((item) => item.sequence === event.sequence)) return current;
          return { ...current, events: [...current.events, event] };
        });
        if (TERMINAL.has(event.type)) void syncTask(taskId);
      };
      socket.onclose = () => void syncTask(taskId);
    },
    [syncTask],
  );

  useEffect(() => () => socketRef.current?.close(), []);

  useEffect(() => {
    let cancelled = false;
    const actions = actionsRef.current;
    api.latestAgentTask().then((env) => {
      const latest = env.result.task;
      if (cancelled || actionsRef.current !== actions || !latest) return;
      setTask(latest); setSessionId(latest.session_id); setMode(latest.mode);
      if (["queued", "running", "cancelling"].includes(latest.status)) connect(latest.task_id);
    }).catch((error) => { if (!cancelled) onError(errMsg(error)); });
    return () => { cancelled = true; };
  }, [api, connect, onError]);

  async function run() {
    const value = prompt.trim();
    if (!value) return;
    actionsRef.current += 1;
    try {
      const envelope = sessionId
        ? await api.resumeAgentSession(sessionId, value, mode)
        : await api.createAgentTask(value, mode);
      const created = envelope.result.task;
      setTask(created);
      setPrompt("");
      connect(created.task_id);
    } catch (error) {
      onError(errMsg(error));
    }
  }

  async function cancel() {
    if (!task) return;
    try {
      setTask((await api.cancelAgentTask(task.task_id)).result.task);
    } catch (error) {
      onError(errMsg(error));
    }
  }

  const busy = task?.status === "queued" || task?.status === "running" || task?.status === "cancelling";
  const textBlocks = task?.events.map(eventText).filter((text): text is string => text !== null) ?? [];
  const tools = task?.events.map(toolSummary).filter((text): text is string => text !== null) ?? [];

  return (
    <Section
      title="OpenCode Agent"
      actions={task ? <Tag tone={task.status === "completed" ? "active" : ""}>{task.status}</Tag> : null}
    >
      <div className="agent-mode-row">
        {(["analyze", "learn", "experiment"] as AgentMode[]).map((item) => (
          <button
            type="button"
            className={`agent-mode ${mode === item ? "selected" : ""}`}
            key={item}
            onClick={() => setMode(item)}
            disabled={busy}
          >
            <strong>{item}</strong>
            <span>{MODE_HELP[item]}</span>
          </button>
        ))}
      </div>
      <label>
        任务
        <textarea
          rows={3}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder={enabled ? "说明要分析、学习或实验的目标与选区…" : "请先新建草稿或导入 MIDI"}
          disabled={!enabled || busy}
        />
      </label>
      <div className="action-row">
        <Button variant="primary" onClick={() => void run()} disabled={!enabled || busy || !prompt.trim()}>
          {sessionId ? "继续会话" : "运行"}
        </Button>
        {busy ? (
          <Button variant="danger" onClick={() => void cancel()}>
            取消
          </Button>
        ) : null}
        {sessionId && !busy ? (
          <Button
            variant="ghost"
            onClick={() => {
              actionsRef.current += 1;
              setSessionId(null);
              setTask(null);
            }}
          >
            新会话
          </Button>
        ) : null}
        {sessionId ? <code className="agent-session">{sessionId}</code> : null}
      </div>
      {tools.length ? (
        <div className="agent-tools">
          {tools.map((tool, index) => (
            <Tag key={`${tool}-${index}`}>{tool}</Tag>
          ))}
        </div>
      ) : null}
      {textBlocks.length ? <pre className="agent-output">{textBlocks.join("\n\n")}</pre> : null}
    </Section>
  );
}
