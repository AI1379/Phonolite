import { useProjectApi } from "./ProjectApiContext";
// The detail panel for the currently selected version: metadata, warnings,
// and the actions that operate on a single version (inspect / render / export
// / accept as main). Transform and compare are surfaced as callbacks that the
// App wires to their dedicated panels.

import { useEffect, useState } from "react";

import { errMsg, type InspectQuery } from "../api";
import type {
  ExportResult,
  InspectResult,
  RenderResult,
  VersionSummary,
  ScoreRegion,
} from "../types";
import { ArtifactLink, Button, Section, Tag } from "./common";
import { Findings } from "./Findings";
import { ScoreNotes } from "./ScoreNotes";
import { PianoRoll, type RollFocus } from "./PianoRoll";

export function VersionDetail({
  version,
  isActive,
  onError,
  onChanged,
  onTransform,
  onCompare,
  onEdited,
  onSelectionChange,
  externalFocus,
  referenceCursor,
}: {
  version: VersionSummary;
  isActive: boolean;
  onError: (message: string) => void;
  onChanged: () => void;
  onTransform: (region: ScoreRegion, noteId?: string) => void;
  onCompare: () => void;
  onEdited: (id: string) => void;
  onSelectionChange: (region: ScoreRegion | null) => void;
  externalFocus: RollFocus | null;
  referenceCursor: number | null;
}) {
  const api = useProjectApi();
  const [findings, setFindings] = useState<InspectResult | null>(null);
  const [render, setRender] = useState<RenderResult | null>(null);
  const [exported, setExported] = useState<ExportResult | null>(null);
  const [regionStart, setRegionStart] = useState("");
  const [regionEnd, setRegionEnd] = useState("");
  const [trackId, setTrackId] = useState("");
  const [noteQuery, setNoteQuery] = useState<InspectQuery>({});
  const [busy, setBusy] = useState(false);
  const [rollFocus, setRollFocus] = useState<RollFocus | null>(null);

  const visualSelection: ScoreRegion | null = regionStart !== "" && regionEnd !== ""
    && Number.isFinite(Number(regionStart)) && Number.isFinite(Number(regionEnd))
    && Number(regionStart) >= 0 && Number(regionEnd) > Number(regionStart)
    ? { start_beat: Number(regionStart), end_beat: Number(regionEnd), track_ids: trackId ? [trackId] : undefined } : null;

  useEffect(() => { onSelectionChange(visualSelection); }, [regionStart, regionEnd, trackId, onSelectionChange]);
  useEffect(() => {
    if (!externalFocus) return;
    setRegionStart(String(externalFocus.region.start_beat)); setRegionEnd(String(externalFocus.region.end_beat));
    setRollFocus(externalFocus);
  }, [externalFocus]);

  function setRegion(region: ScoreRegion | null) {
    setRegionStart(region ? String(region.start_beat) : "");
    setRegionEnd(region ? String(region.end_beat) : "");
    setNoteQuery(region ? { start_beat: region.start_beat, end_beat: region.end_beat, track_ids: trackId || undefined } : { track_ids: trackId || undefined });
    setRollFocus(null);
  }

  function selectedRegion(): ScoreRegion {
    if ((regionStart === "") !== (regionEnd === "")) throw new Error("请同时填写起止拍，或同时留空分析全曲。");
    const start = regionStart === "" ? 0 : Number(regionStart);
    const end = regionEnd === "" ? version.duration_beats : Number(regionEnd);
    if (!Number.isFinite(start) || !Number.isFinite(end) || start < 0 || end <= start) throw new Error("选区需要满足 0 ≤ 起始拍 < 结束拍。");
    return { start_beat: start, end_beat: end, track_ids: trackId ? [trackId] : undefined };
  }

  function transformRegion() {
    try { onTransform(selectedRegion()); } catch (e) { onError(errMsg(e)); }
  }

  async function doInspect() {
    setBusy(true);
    try {
      const region = selectedRegion();
      const query = { start_beat: region.start_beat, end_beat: region.end_beat, track_ids: trackId || undefined };
      setFindings((await api.inspect(version.version_id, query)).result);
      setNoteQuery(query);
    } catch (e) {
      onError(errMsg(e));
    } finally { setBusy(false); }
  }

  async function doRender(backend: string) {
    setBusy(true);
    try {
      setRender((await api.render(version.version_id, backend)).result);
    } catch (e) {
      onError(errMsg(e));
    } finally { setBusy(false); }
  }

  async function doExport() {
    try {
      setExported((await api.exportMidi(version.version_id)).result);
    } catch (e) {
      onError(errMsg(e));
    }
  }

  async function doAccept() {
    try {
      await api.accept(version.version_id);
      onChanged();
    } catch (e) {
      onError(errMsg(e));
    }
  }

  const meterText = version.meters
    .map((m) => `${m.numerator}/${m.denominator}`)
    .join(", ");

  return (
    <Section
      title={`当前 MIDI · ${version.branch ?? version.version_id.slice(0, 12)}`}
      actions={<Tag tone={version.origin}>{({import:"导入",transform:"变换",draft:"草稿",edit:"校正"} as Record<string,string>)[version.origin] ?? version.origin}</Tag>}
    >
      <details className="version-metadata"><summary>版本信息 · {version.note_count} 个音符 · {version.duration_beats.toFixed(2)} 拍 · {meterText || "未标注拍号"}</summary><dl className="meta-grid">
        <dt>version_id</dt>
        <dd>{version.version_id}</dd>
        <dt>parent</dt>
        <dd>{version.parent_version ?? version.parent_id ?? "—"}</dd>
        <dt>created</dt>
        <dd>{version.created_at}</dd>
        <dt>notes / duration</dt>
        <dd>
          {version.note_count} · {version.duration_beats.toFixed(2)} beats
        </dd>
        <dt>tracks</dt>
        <dd>{version.track_ids.join(", ") || "—"}</dd>
        <dt>meter</dt>
        <dd>{meterText || "—"}</dd>
      </dl></details>

      {version.description && version.origin === "transform" ? <p className="muted">{version.description}</p> : null}

      {version.import_warnings?.length ? (
        <ul className="warnings">
          {version.import_warnings.map((w, i) => (
            <li key={i}>{w}</li>
          ))}
        </ul>
      ) : null}

      <div className="action-row">
        <span className="region-input" title="可选:仅分析指定拍区间">
          <input
            value={regionStart}
            onChange={(e) => setRegionStart(e.target.value)}
            placeholder="起始拍（留空为全曲）"
            aria-label="分析起始拍"
            inputMode="decimal"
          />
          <input
            value={regionEnd}
            onChange={(e) => setRegionEnd(e.target.value)}
            placeholder="结束拍（不含）"
            aria-label="分析结束拍"
            inputMode="decimal"
          />
        </span>
        <select className="track-select" aria-label="分析音轨" value={trackId} onChange={(e) => {
          setTrackId(e.target.value); setNoteQuery((current) => ({ ...current, track_ids: e.target.value || undefined })); setRollFocus(null);
        }}>
          <option value="">全部音轨</option>{version.track_ids.map((id) => <option key={id} value={id}>{id}</option>)}
        </select>
        <Button disabled={busy} onClick={doInspect}>{busy ? "处理中…" : "分析选区"}</Button>
        <Button onClick={transformRegion}>变换选区</Button>
        <Button onClick={onCompare}>对比为 A</Button>
        <span className="spacer" />
        <Button disabled={busy} onClick={() => doRender("auto")} title="优先已配置的外部合成器，失败时使用内置预听">
          自动渲染
        </Button>
        <Button onClick={doExport}>导出 MIDI</Button>
        {!isActive ? (
          <Button variant="primary" onClick={doAccept}>
            设为主版本
          </Button>
        ) : null}
      </div>

      <PianoRoll version={version} trackId={trackId} selection={visualSelection} focus={rollFocus}
        onRegion={setRegion} onShift={onTransform} onEdited={onEdited} referenceCursor={referenceCursor} />

      {findings ? (
        <div className="subsection">
          <h3>分析结论 · 拍 {findings.region.start_beat}–{findings.region.end_beat}</h3>
          <Findings findings={findings.findings} onLocate={(finding) => {
            const location = finding.location;
            const targetTrack = location.track_ids.length === 1 ? location.track_ids[0] : "";
            setTrackId(targetTrack);
            setRegionStart(String(location.start_beat)); setRegionEnd(String(location.end_beat));
            const region = { start_beat: location.start_beat, end_beat: location.end_beat,
              track_ids: targetTrack ? [targetTrack] : undefined };
            setNoteQuery({ start_beat: region.start_beat, end_beat: region.end_beat, track_ids: targetTrack || undefined });
            setRollFocus({ region, noteIds: finding.note_ids });
          }} />
        </div>
      ) : null}

      <ScoreNotes key={JSON.stringify(noteQuery)} versionId={version.version_id} query={noteQuery}
        onShift={(note) => onTransform({ start_beat: noteQuery.start_beat ?? 0,
          end_beat: noteQuery.end_beat ?? version.duration_beats,
          track_ids: [note.track_id] }, note.id)} />

      {render ? (
        <div className="subsection">
          <h3>渲染产物（backend: {render.backend}）</h3>
          <ArtifactLink
            token={render.artifact_token}
            filename={render.filename}
            contentType={render.backend === "midi-file" ? "audio/midi" : "audio/wav"}
            sizeBytes={render.size_bytes}
          />
          {render.warnings.length > 0 ? (
            <ul className="warnings">
              {render.warnings.map((w, i) => (
                <li key={i}>{w}</li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}

      {exported ? (
        <div className="subsection">
          <h3>导出产物</h3>
          <ArtifactLink
            token={exported.artifact_token}
            filename={exported.filename}
            contentType="audio/midi"
            sizeBytes={exported.size_bytes}
          />
        </div>
      ) : null}
    </Section>
  );
}
