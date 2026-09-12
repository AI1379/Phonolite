// Renders stage-1 analysis findings as locatable, confidence-bearing cards
// (observation vs. interpretation split, per design doc section 7.2).

import { useState } from "react";
import type { Finding } from "../types";
import { Confidence, Empty, Tag } from "./common";

export function Findings({ findings, onLocate }: { findings: Finding[]; onLocate?: (finding: Finding) => void }) {
  const [category, setCategory] = useState("all");
  if (findings.length === 0) {
    return <Empty>该选区未产生分析结论。</Empty>;
  }
  return (
    <div className="findings">
      <label>分析维度
        <select value={category} onChange={(event) => setCategory(event.target.value)}>
          <option value="all">全部</option><option value="overview">整体统计</option>
          <option value="rhythm">节奏重复</option><option value="harmony">和弦候选</option>
        </select>
      </label>
      {findings.filter((finding) => category === "all" || finding.category === category).map((finding, index) => (
        <article key={index} className="finding">
          <div className="finding-head">
            <Tag tone="loc">{finding.location.bars_label}</Tag>
            <span className="muted">拍 {finding.location.start_beat}–{finding.location.end_beat} · {finding.location.track_ids.join(", ")}</span>
            <Confidence value={finding.confidence} />
            {onLocate ? <button className="btn" onClick={() => onLocate(finding)}>在卷帘中定位</button> : null}
          </div>
          <p className="finding-observation">{finding.observation}</p>
          <p className="finding-interpretation">{finding.interpretation}</p>
          {finding.alternatives.length > 0 ? (
            <ul className="alternatives">
              {finding.alternatives.map((alt, j) => (
                <li key={j}>替代解释:{alt}</li>
              ))}
            </ul>
          ) : null}
          <dl className="evidence">
            {finding.evidence.map((ev, j) => (
              <div key={j}>
                <dt>{ev.metric}</dt>
                <dd>{String(ev.value)}</dd>
              </div>
            ))}
          </dl>
        </article>
      ))}
    </div>
  );
}
