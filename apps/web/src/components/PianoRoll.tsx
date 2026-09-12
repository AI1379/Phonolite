import { useProjectApi } from "./ProjectApiContext";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { errMsg } from "../api";
import type { Note, RenderResult, ScorePage, ScoreRegion, VersionSummary } from "../types";
import { Button } from "./common";
import { beatSeconds, pitchLabel, rulerBars, secondsBeat } from "./pianoRollLayout";
import { NoteEditor } from "./NoteEditor";
import { pauseOtherMedia } from "./mediaPlayback";

const KEY_WIDTH = 62;
const RULER_HEIGHT = 42;
const COLORS = ["#58b9f3", "#e9b66c", "#b598f5", "#78cdaa", "#ef8eac", "#a9c96e"];
const BLACK_KEYS = new Set([1, 3, 6, 8, 10]);

export interface RollFocus { region: ScoreRegion; noteIds: string[] }

export function PianoRoll({ version, trackId, selection, focus, onRegion, onShift, onEdited, referenceCursor }: {
  version: VersionSummary;
  trackId: string;
  selection: ScoreRegion | null;
  focus: RollFocus | null;
  onRegion: (region: ScoreRegion | null) => void;
  onShift: (region: ScoreRegion, noteId: string) => void;
  onEdited: (versionId: string) => void;
  referenceCursor: number | null;
}) {
  const api = useProjectApi();
  const [notes, setNotes] = useState<Note[]>([]);
  const [canvasWidth, setCanvasWidth] = useState(960);
  const [viewStart, setViewStart] = useState(0);
  const [span, setSpan] = useState(Math.min(32, Math.max(8, Math.ceil(version.duration_beats))));
  const [snap, setSnap] = useState(0.25);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [chosen, setChosen] = useState<Note | null>(null);
  const [drag, setDrag] = useState<{ anchor: number; end: number } | null>(null);
  const dragRef = useRef<{ anchor: number; end: number } | null>(null);
  const [audio, setAudio] = useState<RenderResult | null>(null);
  const [rendering, setRendering] = useState(false);
  const [audioError, setAudioError] = useState<string | null>(null);
  const [playhead, setPlayhead] = useState<number | null>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const endPlayback = useRef<number | null>(null);
  const containerRef = useRef<HTMLDivElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const duration = Math.max(1, Math.ceil(version.duration_beats));
  const viewEnd = viewStart + span;
  const gridWidth = canvasWidth - KEY_WIDTH;

  useEffect(() => {
    if (referenceCursor === null) return;
    setPlayhead(referenceCursor);
    setViewStart((start) => referenceCursor < start || referenceCursor >= start + span
      ? Math.max(0, Math.floor(referenceCursor / span) * span) : start);
  }, [referenceCursor, span]);

  useEffect(() => {
    const target = scrollRef.current;
    if (!target) return;
    const observer = new ResizeObserver((entries) => {
      const width = entries[0]?.contentRect.width;
      if (width) setCanvasWidth(Math.max(680, width));
    });
    observer.observe(target);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true); setError(null); setNotes([]); setChosen(null);
    async function load() {
      const collected: Note[] = [];
      let offset: number | null = 0;
      while (offset !== null) {
        const page: ScorePage = (await api.score(version.version_id, {
          start_beat: viewStart, end_beat: viewEnd, track_ids: trackId || undefined,
        }, offset, 1024)).result;
        if (cancelled) return;
        collected.push(...page.notes);
        if (collected.length > 20000) throw new Error("当前窗口超过 20000 个音符，请缩小显示范围或选择单一音轨。");
        if (page.next_offset !== null && page.next_offset <= offset) throw new Error("音符分页未前进，请重新载入。");
        offset = page.next_offset;
      }
      if (!cancelled) setNotes(collected);
    }
    load().catch((e) => { if (!cancelled) setError(errMsg(e)); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [version.version_id, trackId, viewStart, viewEnd, retry]);

  useEffect(() => {
    if (!focus) return;
    setViewStart(Math.max(0, Math.floor(focus.region.start_beat)));
    setSpan(Math.min(512, Math.max(8, Math.ceil(focus.region.end_beat - Math.floor(focus.region.start_beat)))));
    containerRef.current?.scrollIntoView({ block: "center", behavior: "smooth" });
  }, [focus]);

  const bars = useMemo(() => rulerBars(version.meters, viewStart, viewEnd), [version.meters, viewStart, viewEnd]);
  const pitches = notes.map((note) => note.pitch);
  const low = Math.max(0, Math.min(48, ...pitches) - 2);
  const high = Math.min(127, Math.max(72, ...pitches) + 2);
  const rows = high - low + 1;
  const rowHeight = Math.max(8, Math.min(16, 460 / rows));
  const height = RULER_HEIGHT + rows * rowHeight;
  const x = (beat: number) => KEY_WIDTH + (beat - viewStart) / span * gridWidth;
  const highlightIds = new Set(focus?.noteIds ?? []);
  const scoped = (start: number, end: number): ScoreRegion => ({ start_beat: start, end_beat: end, track_ids: trackId ? [trackId] : undefined });

  function beatAt(event: PointerEvent<SVGSVGElement>): number {
    const rect = event.currentTarget.getBoundingClientRect();
    const offset = ((event.clientX - rect.left) / rect.width * canvasWidth - KEY_WIDTH) / gridWidth;
    const beat = viewStart + Math.max(0, Math.min(1, offset)) * span;
    return Math.max(0, Math.min(duration, Math.round(beat / snap) * snap));
  }

  function dragStart(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0 || loading || error) return;
    const rect = event.currentTarget.getBoundingClientRect();
    if ((event.clientX - rect.left) / rect.width * canvasWidth < KEY_WIDTH) return;
    const anchor = beatAt(event);
    dragRef.current = { anchor, end: anchor }; setDrag(dragRef.current);
    event.currentTarget.setPointerCapture(event.pointerId);
    setChosen(null); event.preventDefault();
  }

  function dragMove(event: PointerEvent<SVGSVGElement>) {
    if (!dragRef.current) return;
    dragRef.current = { ...dragRef.current, end: beatAt(event) }; setDrag(dragRef.current);
  }

  function dragEnd(event: PointerEvent<SVGSVGElement>) {
    const value = dragRef.current;
    if (!value) return;
    const end = beatAt(event);
    const startBeat = Math.min(value.anchor, end);
    const endBeat = Math.min(duration, Math.max(value.anchor, end, startBeat + snap));
    if (endBeat > startBeat) onRegion(scoped(startBeat, endBeat));
    dragRef.current = null; setDrag(null);
    event.currentTarget.releasePointerCapture(event.pointerId);
  }

  function selectNote(note: Note) {
    setChosen(note);
    onRegion(scoped(Math.floor(note.onset_beats), Math.max(Math.floor(note.onset_beats) + 1, Math.ceil(note.offset_beats))));
  }

  async function prepareAudio() {
    setRendering(true); setAudioError(null);
    try { setAudio((await api.render(version.version_id, "preview")).result); }
    catch (e) { setAudioError(errMsg(e)); }
    finally { setRendering(false); }
  }

  async function playSelection() {
    const player = audioRef.current;
    if (!player || !selection) return;
    player.currentTime = beatSeconds(version.tempos, selection.start_beat);
    endPlayback.current = beatSeconds(version.tempos, selection.end_beat);
    try { await player.play(); } catch (e) { setAudioError(errMsg(e)); }
  }

  const active = drag ? scoped(Math.min(drag.anchor, drag.end), Math.max(drag.anchor, drag.end)) : selection;
  const regionLeft = active ? Math.max(viewStart, active.start_beat) : 0;
  const regionRight = active ? Math.min(viewEnd, active.end_beat) : 0;
  const beatStep = span > 128 ? 16 : span > 48 ? 4 : 1;
  const beats = Array.from({ length: Math.floor(span / beatStep) + 1 }, (_, i) => Math.ceil(viewStart / beatStep) * beatStep + i * beatStep).filter((beat) => beat <= viewEnd);

  return <div className="piano-roll" ref={containerRef}>
    <div className="roll-heading"><h3>MIDI 钢琴卷帘</h3><span>{version.note_count} 个音符 · 当前窗口 {notes.length} 个</span></div>
    <div className="roll-toolbar">
      <Button disabled={viewStart === 0} onClick={() => setViewStart(Math.max(0, viewStart - span))}>← 前一段</Button>
      <Button disabled={viewEnd >= duration} onClick={() => setViewStart(viewEnd)}>后一段 →</Button>
      <label>显示拍数<select aria-label="卷帘显示拍数" value={span} onChange={(event) => setSpan(Number(event.target.value))}>
        {[...new Set([8, 16, 32, 64, 128, 512, span])].sort((a, b) => a - b).map((value) => <option value={value} key={value}>{value} 拍</option>)}
      </select></label>
      <Button onClick={() => { setViewStart(0); setSpan(Math.min(512, Math.max(8, duration))); }}>适合全曲</Button>
      <Button disabled={!selection} onClick={() => {
        if (!selection) return;
        setViewStart(Math.max(0, Math.floor(selection.start_beat)));
        setSpan(Math.min(512, Math.max(8, Math.ceil(selection.end_beat - Math.floor(selection.start_beat)))));
      }}>定位选区</Button>
      <label>选区吸附<select aria-label="选区吸附" value={snap} onChange={(event) => setSnap(Number(event.target.value))}>
        <option value={0.25}>¼ 拍</option><option value={0.5}>½ 拍</option><option value={1}>1 拍</option>
      </select></label>
      <Button onClick={() => { onRegion(null); setChosen(null); }}>清除选区</Button>
    </div>
    <p className="roll-help">在上方标尺或网格空白处拖选范围；点击音符查看详情。横向长度表示按键时值，颜色区分音轨。</p>
    <div className="roll-legend">{version.track_ids.map((id, index) => <span key={id} className={trackId && trackId !== id ? "dim" : ""}>
      <i style={{ background: COLORS[index % COLORS.length] }} />{id}</span>)}</div>
    <div className="roll-scroll" ref={scrollRef}>
      <svg className="roll-svg" style={{ height }} viewBox={`0 0 ${canvasWidth} ${height}`} role="group" aria-label="MIDI 钢琴卷帘时间线"
        onPointerDown={dragStart} onPointerMove={dragMove} onPointerUp={dragEnd}
        onPointerCancel={() => { dragRef.current = null; setDrag(null); }}>
        <rect width={canvasWidth} height={height} fill="#161c26" />
        {Array.from({ length: rows }, (_, index) => {
          const pitch = high - index; const y = RULER_HEIGHT + index * rowHeight;
          return <g key={pitch}>
            <rect x={KEY_WIDTH} y={y} width={gridWidth} height={rowHeight} fill={BLACK_KEYS.has(pitch % 12) ? "#171e29" : "#202a38"} />
            <rect x={0} y={y} width={KEY_WIDTH - 2} height={rowHeight - 0.6} fill={BLACK_KEYS.has(pitch % 12) ? "#293242" : "#d4dbe4"} />
            <text x={KEY_WIDTH - 9} y={y + rowHeight * 0.76} textAnchor="end" fontSize={Math.min(11, rowHeight - 1)} fill={BLACK_KEYS.has(pitch % 12) ? "#b9c5d5" : "#263143"}>{pitchLabel(pitch)}</text>
          </g>;
        })}
        {beats.map((beat) => <g key={beat} pointerEvents="none">
          <line x1={x(beat)} x2={x(beat)} y1={RULER_HEIGHT - 12} y2={height} stroke="#344155" strokeWidth={0.7} />
          <text x={x(beat) + 3} y={RULER_HEIGHT - 5} fill="#8e9eb4" fontSize={10}>{beat}</text>
        </g>)}
        {bars.map((bar) => <g key={bar.number} pointerEvents="none">
          <line x1={x(Math.max(viewStart, bar.start))} x2={x(Math.max(viewStart, bar.start))} y1={0} y2={height} stroke="#60738e" strokeWidth={1.2} />
          {x(bar.end) - x(Math.max(viewStart, bar.start)) > 24 ? <text x={x(Math.max(viewStart, bar.start)) + 5} y={16} fill="#d6e2f2" fontSize={12}>{bar.number}{span <= 64 ? ` · ${bar.meter}` : ""}</text> : null}
        </g>)}
        <text x={8} y={17} fontSize={11} fill="#9faec2">小节</text><text x={8} y={36} fontSize={11} fill="#9faec2">拍点</text>
        {regionRight > regionLeft ? <rect data-testid="roll-selection" x={x(regionLeft)} y={0} width={x(regionRight) - x(regionLeft)} height={height} fill="#77adff" fillOpacity={0.15} stroke="#8ec3ff" pointerEvents="none" /> : null}
        {notes.map((note) => {
          const left = x(Math.max(viewStart, note.onset_beats));
          const right = x(Math.min(viewEnd, Math.max(note.offset_beats, note.onset_beats + 0.04)));
          const chosenNote = chosen?.id === note.id;
          const related = highlightIds.has(note.id);
          const label = `${pitchLabel(note.pitch)} · ${note.track_id} · 起音 ${note.onset_beats} 拍 · 时值 ${note.duration_beats} 拍 · 力度 ${note.velocity}`;
          return <rect key={note.id} className="roll-note" data-note-id={note.id} x={left} y={RULER_HEIGHT + (high - note.pitch) * rowHeight + 1}
            width={Math.max(2, right - left - 1)} height={rowHeight - 2} rx={2}
            fill={COLORS[Math.max(0, version.track_ids.indexOf(note.track_id)) % COLORS.length]} fillOpacity={0.5 + note.velocity / 254}
            stroke={chosenNote ? "#fff" : related ? "#eff7ff" : "#0006"} strokeWidth={chosenNote ? 2.4 : related ? 1.6 : 0.5}
            strokeDasharray={note.transcription_status === "uncertain" ? "3 2" : undefined}
            tabIndex={0} role="button" aria-label={label} aria-pressed={chosenNote}
            onPointerDown={(event) => event.stopPropagation()} onClick={() => selectNote(note)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectNote(note); } }}>
            <title>{label}</title>
          </rect>;
        })}
        {playhead !== null && playhead >= viewStart && playhead <= viewEnd ? <line data-testid="roll-playhead" x1={x(playhead)} x2={x(playhead)} y1={0} y2={height} stroke="#ff737d" strokeWidth={2} pointerEvents="none" /> : null}
      </svg>
    </div>
    <div className="roll-status" aria-live="polite">
      <span>显示拍 {viewStart}–{viewEnd}{duration > 512 ? "（分段浏览）" : ""}</span>
      <strong>{active ? `选区：${active.start_beat}–${active.end_beat} 拍` : "尚未选择范围 · 默认分析全曲"}</strong>
    </div>
    {loading ? <p role="status">正在加载当前窗口全部音符…</p> : null}
    {!loading && !error && notes.length === 0 ? <p>{version.note_count === 0 ? "空白草稿已就绪，在下方记下第一个音符。" : "当前范围没有音符，请切换音轨或时间窗口。"}</p> : null}
    {error ? <p role="alert" className="error">{error} <Button onClick={() => setRetry((value) => value + 1)}>重新载入</Button></p> : null}
    {chosen ? <div className="roll-note-detail"><strong>{pitchLabel(chosen.pitch)}</strong><span>{chosen.track_id} · 起音 {chosen.onset_beats} 拍 · 时值 {chosen.duration_beats} 拍 · 力度 {chosen.velocity}</span>
      {chosen.transcription_status ? <span className="tag">{chosen.transcription_status === "confirmed" ? "已听辨确认" : "待核对"}</span> : null}
      <Button disabled={selection !== null && !(selection.start_beat <= chosen.onset_beats && chosen.onset_beats < selection.end_beat)}
        onClick={() => onShift({ start_beat: selection?.start_beat ?? viewStart, end_beat: selection?.end_beat ?? viewEnd, track_ids: [chosen.track_id] }, chosen.id)}>移动所选音符起音</Button></div> : null}
    <NoteEditor version={version} chosen={chosen} selection={selection} onSaved={onEdited} />
    <div className="roll-audio">
      {!audio ? <Button disabled={rendering} onClick={() => void prepareAudio()}>{rendering ? "正在生成 WAV…" : "准备当前版本试听"}</Button> : <>
        <audio ref={audioRef} aria-label="钢琴卷帘试听" controls src={api.artifactUrl(audio.artifact_token)}
          onPlay={() => { if(audioRef.current) pauseOtherMedia(audioRef.current); }}
          onTimeUpdate={() => {
            const player = audioRef.current; if (!player) return;
            setPlayhead(secondsBeat(version.tempos, player.currentTime));
            if (endPlayback.current !== null && player.currentTime >= endPlayback.current) { player.pause(); endPlayback.current = null; }
          }} onEnded={() => { endPlayback.current = null; }} />
        <Button disabled={!selection} onClick={() => void playSelection()}>试听选区</Button>
        <span className="muted">红线为播放位置 · 参考合成音色</span>
      </>}
    </div>
    {audioError ? <p role="alert" className="error">{audioError}</p> : null}
    {audio ? <details className="roll-audio-notes"><summary>预听说明</summary><ul>{audio.warnings.map((warning) => <li key={warning}>{warning}</li>)}</ul></details> : null}
  </div>;
}
