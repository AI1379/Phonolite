// Renders stage-1 analysis findings as locatable, confidence-bearing cards
// (observation vs. interpretation split, per design doc section 7.2).

import type { Finding } from "../types";
import { Confidence, Empty, Tag } from "./common";

export function Findings({ findings }: { findings: Finding[] }) {
  if (findings.length === 0) {
    return <Empty>该选区未产生分析结论。</Empty>;
  }
  return (
    <div className="findings">
      {findings.map((finding, index) => (
        <article key={index} className="finding">
          <div className="finding-head">
            <Tag tone="loc">{finding.location.bars_label}</Tag>
            <Confidence value={finding.confidence} />
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
