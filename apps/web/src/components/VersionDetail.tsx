// The detail panel for the currently selected version: metadata, warnings,
// and the actions that operate on a single version (inspect / render / export
// / accept as main). Transform and compare are surfaced as callbacks that the
// App wires to their dedicated panels.

import { useState } from "react";

import { api, errMsg } from "../api";
import type {
  ExportResult,
  InspectResult,
  RenderResult,
  VersionSummary,
} from "../types";
import { ArtifactLink, Button, Section, Tag } from "./common";
import { Findings } from "./Findings";

export function VersionDetail({
  version,
  isActive,
  onError,
  onChanged,
  onTransform,
  onCompare,
}: {
  version: VersionSummary;
  isActive: boolean;
  onError: (message: string) => void;
  onChanged: () => void;
  onTransform: () => void;
  onCompare: () => void;
}) {
  const [findings, setFindings] = useState<InspectResult | null>(null);
  const [render, setRender] = useState<RenderResult | null>(null);
  const [exported, setExported] = useState<ExportResult | null>(null);
  const [regionStart, setRegionStart] = useState("");
  const [regionEnd, setRegionEnd] = useState("");

  async function doInspect() {
    try {
      const query =
        regionStart !== "" && regionEnd !== ""
          ? { start_beat: Number(regionStart), end_beat: Number(regionEnd) }
          : undefined;
      setFindings((await api.inspect(version.version_id, query)).result);
    } catch (e) {
      onError(errMsg(e));
    }
  }

  async function doRender(backend: string) {
    try {
      setRender((await api.render(version.version_id, backend)).result);
    } catch (e) {
      onError(errMsg(e));
    }
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
      title={`版本 · ${version.branch ?? version.version_id.slice(0, 12)}`}
      actions={<Tag tone={version.origin}>{version.origin === "import" ? "导入" : "变换"}</Tag>}
    >
      <dl className="meta-grid">
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
      </dl>

      {version.description ? <p className="muted">{version.description}</p> : null}

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
            placeholder="start beat"
            inputMode="decimal"
          />
          <input
            value={regionEnd}
            onChange={(e) => setRegionEnd(e.target.value)}
            placeholder="end beat"
            inputMode="decimal"
          />
        </span>
        <Button onClick={doInspect}>分析 Inspect</Button>
        <Button onClick={onTransform}>变换 Transform</Button>
        <Button onClick={onCompare}>对比为 A</Button>
        <span className="spacer" />
        <Button onClick={() => doRender("midi")} title="MIDI 回退,任何环境可用">
          渲染 MIDI
        </Button>
        <Button onClick={() => doRender("auto")} title="优先音频合成器,无则回退 MIDI">
          渲染音频
        </Button>
        <Button onClick={doExport}>导出 MIDI</Button>
        {!isActive ? (
          <Button variant="primary" onClick={doAccept}>
            设为主版本
          </Button>
        ) : null}
      </div>

      {findings ? (
        <div className="subsection">
          <h3>分析结论（{findings.region.scope === "region" ? "区间" : "全曲"}）</h3>
          <Findings findings={findings.findings} />
        </div>
      ) : null}

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
