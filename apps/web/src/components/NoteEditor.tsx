import { useProjectApi } from "./ProjectApiContext";
import { useEffect, useState } from "react";
import { errMsg } from "../api";
import type { Note, NoteInput, ScoreRegion, VersionSummary } from "../types";
import { Button } from "./common";
import { pitchLabel } from "./pianoRollLayout";

export function NoteEditor({ version, chosen, selection, onSaved }: {
  version: VersionSummary; chosen: Note | null; selection: ScoreRegion | null; onSaved: (id: string) => void;
}) {
  const api = useProjectApi();
  const [pitch, setPitch] = useState("60");
  const [onset, setOnset] = useState("0");
  const [duration, setDuration] = useState("1");
  const [velocity, setVelocity] = useState("80");
  const [role, setRole] = useState<NoteInput["role"]>("melody");
  const [track, setTrack] = useState("melody");
  const [status, setStatus] = useState<NoteInput["transcription_status"]>("uncertain");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setPitch(String(chosen?.pitch ?? 60)); setOnset(String(chosen?.onset_beats ?? selection?.start_beat ?? 0));
    setDuration(String(chosen?.duration_beats ?? 1)); setVelocity(String(chosen?.velocity ?? 80));
    setRole(chosen?.role ?? "melody"); setTrack(chosen?.track_id ?? "melody");
    setStatus(chosen?.transcription_status ?? "uncertain");
  }, [chosen, selection?.start_beat]);

  async function save(action: "add" | "update" | "remove") {
    setBusy(true); setError(null);
    try {
      if (action !== "remove" && ![pitch, onset, duration, velocity].every((value) => value.trim() !== "" && Number.isFinite(Number(value)))) throw new Error("请填写完整的音高、起音、时值和力度。");
      const result = (await api.editNote({ source_version_id: version.version_id, action, note_id: chosen?.id,
        note: action === "remove" ? undefined : { pitch: Number(pitch), onset_beats: Number(onset), duration_beats: Number(duration),
          velocity: Number(velocity), track_id: track, role, transcription_status: status } })).result;
      onSaved(result.version.version_id);
    } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  }

  return <details className="note-editor" open={version.kind === "transcription" || !!chosen}>
    <summary>记音与校正 {chosen ? `· 已选 ${pitchLabel(chosen.pitch)}` : "· 新建音符"}</summary>
    <p className="muted">选择音符后可校正或删去；每次保存新稿，之前的版本仍可打开。主版本通过“设为主版本”更新。</p>
    <div className="form-grid">
      <label>音高 MIDI（{Number.isInteger(Number(pitch)) && Number(pitch) >= 0 && Number(pitch) <= 127 ? pitchLabel(Number(pitch)) : "—"}）<input aria-label="记音音高" type="number" min={0} max={127} value={pitch} onChange={(e) => setPitch(e.target.value)} /></label>
      <label>起音（拍）<input aria-label="记音起始拍" type="number" min={0} step={0.25} value={onset} onChange={(e) => setOnset(e.target.value)} /></label>
      <label>时值（拍）<input aria-label="记音时值" type="number" min={0.01} step={0.25} value={duration} onChange={(e) => setDuration(e.target.value)} /></label>
      <label>力度<input aria-label="记音力度" type="number" min={1} max={127} value={velocity} onChange={(e) => setVelocity(e.target.value)} /></label>
      <label>声部角色<select aria-label="记音声部" value={role} onChange={(e) => { const value=e.target.value as NoteInput["role"]; setRole(value); if (!chosen) setTrack(value); }}>
        <option value="melody">主旋律</option><option value="bass">低音</option><option value="inner">内声部</option><option value="unknown">未分配</option>
      </select></label>
      <label>音轨<input aria-label="记音音轨" value={track} onChange={(e) => setTrack(e.target.value)} /></label>
      <label>听辨状态<select aria-label="记音确认状态" value={status} onChange={(e) => setStatus(e.target.value as NoteInput["transcription_status"])}>
        <option value="uncertain">待核对</option><option value="confirmed">已听辨确认</option>
      </select></label>
    </div>
    {chosen?.reference_evidence ? <p className="muted">来源音频 {chosen.reference_evidence.start_seconds.toFixed(2)}–{chosen.reference_evidence.end_seconds.toFixed(2)} 秒</p> : null}
    {error ? <p role="alert" className="error">{error}</p> : null}
    <div className="action-row"><Button disabled={busy} variant="primary" onClick={() => void save("add")}>添加为新音符并保存新稿</Button>
      <Button disabled={busy || !chosen} onClick={() => void save("update")}>校正所选音符并保存新稿</Button>
      <Button disabled={busy || !chosen} variant="danger" onClick={() => void save("remove")}>从新稿删去所选音符</Button></div>
  </details>;
}
