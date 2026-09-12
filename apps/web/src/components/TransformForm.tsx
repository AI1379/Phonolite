import { useProjectApi } from "./ProjectApiContext";
// Controlled-transform form. Enforces the "one variable per experiment" red
// line: the operation picker reveals only the parameter relevant to that
// operation (delay_beats OR factor), and the region scopes where it applies.

import { useState } from "react";

import { errMsg } from "../api";
import type { VersionSummary, ScoreRegion } from "../types";
import { Button, Section } from "./common";

export function TransformForm({
  source,
  onError,
  onDone,
  onCancel,
  initialRegion,
  noteId,
}: {
  source: VersionSummary;
  onError: (message: string) => void;
  onDone: (newVersionId: string, warnings: string[]) => void;
  onCancel: () => void;
  initialRegion?: ScoreRegion;
  noteId?: string;
}) {
  const api = useProjectApi();
  const [operation, setOperation] = useState(noteId ? "shift_note_onset" : "delay_bass_resolution");
  const [start, setStart] = useState(String(initialRegion?.start_beat ?? 0));
  const [end, setEnd] = useState(String(initialRegion?.end_beat ?? source.duration_beats));
  const [trackId, setTrackId] = useState(initialRegion?.track_ids?.[0] ?? "");
  const [shift, setShift] = useState("0.5");
  const [delayBeats, setDelayBeats] = useState("1.0");
  const [factor, setFactor] = useState("2.0");
  const [branch, setBranch] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit() {
    setBusy(true);
    try {
      const region = {
        start_beat: Number(start),
        end_beat: Number(end),
        track_ids: trackId ? [trackId] : undefined,
      };
      const parameters: Record<string, string | number | boolean> = {};
      if (operation === "delay_bass_resolution") {
        parameters.delay_beats = Number(delayBeats);
      } else if (operation === "rhythmic_scaling") {
        parameters.factor = Number(factor);
      } else {
        parameters.note_id = noteId ?? "";
        parameters.shift_beats = Number(shift);
      }
      const env = await api.transform({
        source_version_id: source.version_id,
        region,
        operation,
        parameters,
        output_branch: branch || undefined,
      });
      onDone(env.result.version.version_id, [...env.result.validation.errors, ...env.result.validation.warnings]);
    } catch (e) {
      onError(errMsg(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section title="受控变换（每次只改一个变量）">
      <div className="form-grid">
        <label>
          源版本
          <input value={source.version_id} readOnly />
        </label>
        <label>
          操作
          <select value={operation} onChange={(e) => setOperation(e.target.value)}>
            <option value="delay_bass_resolution">
              推迟选区低音起音（不推断和声解决）
            </option>
            <option value="rhythmic_scaling">
              rhythmic_scaling（节奏缩放）
            </option>
            {noteId ? <option value="shift_note_onset">只移动所选音符的起音</option> : null}
          </select>
        </label>
        <label>目标音轨<select value={trackId} onChange={(e) => setTrackId(e.target.value)}>
          <option value="">全部音轨</option>{source.track_ids.map((id) => <option key={id} value={id}>{id}</option>)}
        </select></label>
        <label>
          区间 start beat
          <input
            value={start}
            onChange={(e) => setStart(e.target.value)}
            inputMode="decimal"
          />
        </label>
        <label>
          区间 end beat
          <input
            value={end}
            onChange={(e) => setEnd(e.target.value)}
            inputMode="decimal"
          />
        </label>
        {operation === "delay_bass_resolution" ? (
          <label>
            delay_beats（推迟拍数）
            <input
              value={delayBeats}
              onChange={(e) => setDelayBeats(e.target.value)}
              inputMode="decimal"
            />
          </label>
        ) : operation === "rhythmic_scaling" ? (
          <label>
            factor（&gt;1 放大,&lt;1 缩小,不能为 1）
            <input
              value={factor}
              onChange={(e) => setFactor(e.target.value)}
              inputMode="decimal"
            />
          </label>
        ) : <label>起音位移（拍，正数推迟、负数提前）<input aria-label="起音位移" value={shift} onChange={(e) => setShift(e.target.value)} /></label>}
        <label>
          输出分支名（可选）
          <input
            value={branch}
            onChange={(e) => setBranch(e.target.value)}
            placeholder="留空自动生成"
          />
        </label>
      </div>
      <div className="action-row">
        <Button variant="primary" disabled={busy} onClick={submit}>
          {busy ? "变换中…" : "应用变换"}
        </Button>
        <Button onClick={onCancel}>取消</Button>
      </div>
    </Section>
  );
}
