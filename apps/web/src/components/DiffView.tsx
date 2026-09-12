import { useProjectApi } from "./ProjectApiContext";
// A/B comparison: pick two stored versions, show the semantic diff keyed on
// stable note ids, and (optionally) choose variant B as the main version while
// recording a decision with a learning-flavoured reason.

import { useEffect, useState } from "react";

import { errMsg } from "../api";
import type { NoteChange, ScoreDiff, VersionSummary } from "../types";
import { Button, Empty, Section, Tag } from "./common";
import { ABPlayer } from "./ABPlayer";

function versionLabel(version: VersionSummary): string {
  return `${version.branch ?? version.version_id.slice(0, 8)} · ${version.origin}`;
}

function fmt(value: unknown): string {
  if (typeof value === "number") return String(Math.round(value * 1000) / 1000);
  return String(value);
}

function DiffGroup({
  title,
  changes,
  tone,
}: {
  title: string;
  changes: NoteChange[];
  tone: string;
}) {
  if (changes.length === 0) return null;
  return (
    <div className={`diff-group ${tone}`}>
      <h5>{title}（{changes.length}）</h5>
      <ul>
        {changes.map((change) => (
          <li key={change.note_id}>
            <Tag tone={tone}>{change.kind}</Tag>
            <code>{change.note_id.slice(0, 12)}</code>
            {Object.entries(change.field_changes).map(([field, [old, next]]) => (
              <span key={field} className="fc">
                {field}: {fmt(old)} → {fmt(next)}
              </span>
            ))}
          </li>
        ))}
      </ul>
    </div>
  );
}

export function DiffView({
  versions,
  aId,
  bId,
  setAId,
  setBId,
  onError,
  onChanged,
}: {
  versions: VersionSummary[];
  aId: string | null;
  bId: string | null;
  setAId: (id: string | null) => void;
  setBId: (id: string | null) => void;
  onError: (message: string) => void;
  onChanged: () => void;
}) {
  const api = useProjectApi();
  const [diff, setDiff] = useState<ScoreDiff | null>(null);
  const [reason, setReason] = useState("");
  const [tags, setTags] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    setDiff(null);
    if (!aId || !bId || aId === bId) return;
    let cancelled = false;
    api
      .compare(aId, bId)
      .then((env) => {
        if (!cancelled) setDiff(env.result);
      })
      .catch((e) => {
        if (!cancelled) onError(errMsg(e));
      });
    return () => {
      cancelled = true;
    };
  }, [aId, bId, onError]);

  async function choose(side: "a" | "b") {
    const chosenId = side === "a" ? aId : bId;
    if (!chosenId) return;
    setBusy(true);
    try {
      await api.choose({
        chosen_version_id: chosenId,
        reason: reason || undefined,
        tags:
          tags.length > 0
            ? tags.split(",").map((s) => s.trim()).filter(Boolean)
            : undefined,
      });
      onChanged();
    } catch (e) {
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  const ready = aId !== null && bId !== null && aId !== bId;

  return (
    <Section title="A/B 版本对比">
      <div className="compare-selectors">
        <label>
          版本 A（基线）
          <select value={aId ?? ""} onChange={(e) => setAId(e.target.value || null)}>
            <option value="">— 选择 —</option>
            {versions.map((v) => (
              <option key={v.version_id} value={v.version_id}>
                {versionLabel(v)}
              </option>
            ))}
          </select>
        </label>
        <label>
          版本 B（候选）
          <select value={bId ?? ""} onChange={(e) => setBId(e.target.value || null)}>
            <option value="">— 选择 —</option>
            {versions.map((v) => (
              <option key={v.version_id} value={v.version_id}>
                {versionLabel(v)}
              </option>
            ))}
          </select>
        </label>
      </div>

      {ready && aId && bId ? <ABPlayer key={`${aId}:${bId}`} aId={aId} bId={bId} /> : null}

      {!ready ? (
        <Empty>选择两个不同的版本以查看语义差异。</Empty>
      ) : !diff ? (
        <p className="muted">加载差异…</p>
      ) : (
        <>
          <p className="diff-summary">{diff.summary}</p>
          {diff.is_empty ? (
            <Empty>两个版本完全相同。</Empty>
          ) : (
            <div className="diff-list">
              <DiffGroup title="新增" changes={diff.added} tone="added" />
              <DiffGroup title="删除" changes={diff.removed} tone="removed" />
              <DiffGroup title="修改" changes={diff.modified} tone="modified" />
            </div>
          )}

          <div className="choose-box">
            <h4>试听后选择正式版本并记录理由</h4>
            <input
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="为什么选这个?(作为轻量学习记录)"
            />
            <input
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="标签,逗号分隔(如 bass,timing)"
            />
            <div className="action-row">
              <Button disabled={busy} onClick={() => void choose("a")}>保留 A 并记录决策</Button>
              <Button variant="primary" disabled={busy} onClick={() => void choose("b")}>
                {busy ? "记录中…" : "选择 B 并记录决策"}
              </Button>
            </div>
          </div>
        </>
      )}
    </Section>
  );
}
