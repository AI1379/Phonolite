// Project state panel: the current goal (editable), the musical context,
// preserve/avoid/learning-focus notes, and the decision audit log.

import { useEffect, useState } from "react";

import { api, errMsg } from "../api";
import type { ProjectConfig } from "../types";
import { Button, Empty, Section, Tag } from "./common";

function TagList({ items, tone }: { items: string[] | undefined; tone: string }) {
  if (!items || items.length === 0) return null;
  return (
    <div className="tag-list">
      {items.map((item, i) => (
        <Tag key={i} tone={tone}>
          {item}
        </Tag>
      ))}
    </div>
  );
}

export function ProjectPanel({
  project,
  onError,
  onChanged,
}: {
  project: ProjectConfig;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const goal = project.current_goal;
  const [desc, setDesc] = useState(goal?.description ?? "");
  const [barLo, setBarLo] = useState(goal?.region?.bars?.[0]?.toString() ?? "");
  const [barHi, setBarHi] = useState(goal?.region?.bars?.[1]?.toString() ?? "");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDesc(goal?.description ?? "");
    setBarLo(goal?.region?.bars?.[0]?.toString() ?? "");
    setBarHi(goal?.region?.bars?.[1]?.toString() ?? "");
  }, [goal?.description, goal?.region?.bars]);

  async function saveGoal() {
    setBusy(true);
    try {
      const bars =
        barLo !== "" && barHi !== ""
          ? ([Number(barLo), Number(barHi)] as [number, number])
          : undefined;
      await api.updateGoal({ description: desc, bars });
      onChanged();
    } catch (e) {
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const ctx = project.musical_context;
  const decisions = project.decisions ?? [];

  return (
    <Section title={`项目 · ${project.title}`}>
      <dl className="meta-grid">
        <dt>project_id</dt>
        <dd>{project.id}</dd>
        <dt>active_version</dt>
        <dd>{project.active_version ?? "—"}</dd>
        <dt>context</dt>
        <dd>
          {ctx
            ? [ctx.meter, ctx.tempo_bpm ? `${ctx.tempo_bpm} bpm` : null, ctx.tonal_center]
                .filter(Boolean)
                .join(" · ")
            : "—"}
        </dd>
      </dl>

      <div className="subsection">
        <h3>当前目标</h3>
        <div className="form-grid">
          <label className="full">
            目标描述
            <textarea value={desc} onChange={(e) => setDesc(e.target.value)} rows={2} />
          </label>
          <label>
            起始小节
            <input value={barLo} onChange={(e) => setBarLo(e.target.value)} inputMode="numeric" />
          </label>
          <label>
            结束小节
            <input value={barHi} onChange={(e) => setBarHi(e.target.value)} inputMode="numeric" />
          </label>
        </div>
        <div className="action-row">
          <Button variant="primary" disabled={busy} onClick={saveGoal}>
            {busy ? "保存中…" : "保存目标"}
          </Button>
        </div>
      </div>

      {(project.preserve?.length || project.avoid?.length || project.learning_focus?.length) ? (
        <div className="subsection">
          <h3>约束与学习焦点</h3>
          {project.preserve?.length ? (
            <div className="row">
              <span className="muted">保留</span>
              <TagList items={project.preserve} tone="keep" />
            </div>
          ) : null}
          {project.avoid?.length ? (
            <div className="row">
              <span className="muted">避免</span>
              <TagList items={project.avoid} tone="avoid" />
            </div>
          ) : null}
          {project.learning_focus?.length ? (
            <div className="row">
              <span className="muted">学习焦点</span>
              <TagList items={project.learning_focus} tone="learn" />
            </div>
          ) : null}
        </div>
      ) : null}

      <div className="subsection">
        <h3>决策记录（{decisions.length}）</h3>
        {decisions.length === 0 ? (
          <Empty>尚无决策。在 A/B 对比中选择一个候选即可记录第一条。</Empty>
        ) : (
          <ul className="decisions">
            {[...decisions].reverse().map((d) => (
              <li key={d.id}>
                <div className="decision-head">
                  <span className="decision-at">{d.at}</span>
                  {d.chosen_version_id ? (
                    <Tag tone="active">→ {d.chosen_version_id.slice(0, 12)}</Tag>
                  ) : null}
                </div>
                <p className="decision-summary">{d.summary}</p>
                {d.reason ? <p className="muted">理由:{d.reason}</p> : null}
                {d.tags?.length ? <TagList items={d.tags} tone="learn" /> : null}
              </li>
            ))}
          </ul>
        )}
      </div>
    </Section>
  );
}
