import { useProjectApi } from "./ProjectApiContext";
import { useEffect, useState } from "react";
import { errMsg, type InspectQuery } from "../api";
import type { Note, ScorePage } from "../types";
import { Button } from "./common";

function noteName(pitch: number): string {
  return `${["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"][pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

export function ScoreNotes({ versionId, query, onShift }: {
  versionId: string; query: InspectQuery; onShift: (note: Note) => void;
}) {
  const api = useProjectApi();
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<ScorePage | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setPage(null);
    setError(null);
    api.score(versionId, query, offset).then((env) => {
      if (!cancelled) setPage(env.result);
    }).catch((e) => { if (!cancelled) setError(errMsg(e)); });
    return () => { cancelled = true; };
  }, [versionId, query, offset]);
  return <details className="score-notes">
    <summary>音符数值明细 {page ? `· ${page.total_notes} 个` : ""}</summary>
    <p className="muted">拍点从 0 开始，以四分音符为一拍。选择一个音符，可只移动它的起音来比较节奏变化。</p>
    {error ? <p role="alert">{error}</p> : null}
    {!page && !error ? <p>加载音符…</p> : null}
    {page ? <>
      <div className="table-scroll"><table>
        <thead><tr><th>音轨</th><th>音高</th><th>起音（拍）</th><th>时值（拍）</th><th>力度</th><th>实验</th></tr></thead>
        <tbody>{page.notes.map((note) => <tr key={note.id} title={note.id}>
          <td>{note.track_id}</td><td>{noteName(note.pitch)} ({note.pitch})</td>
          <td>{Number(note.onset_beats.toFixed(3))}</td><td>{Number(note.duration_beats.toFixed(3))}</td>
          <td>{note.velocity}</td><td><Button onClick={() => onShift(note)}>移动起音</Button></td>
        </tr>)}</tbody>
      </table></div>
      {page.notes.length === 0 ? <p>此范围没有音符。</p> : null}
      <div className="action-row">
        <Button disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 64))}>上一页</Button>
        <span>{page.total_notes ? offset + 1 : 0}–{offset + page.notes.length} / {page.total_notes}</span>
        <Button disabled={page.next_offset === null} onClick={() => setOffset(page.next_offset ?? offset)}>下一页</Button>
      </div>
    </> : null}
  </details>;
}
