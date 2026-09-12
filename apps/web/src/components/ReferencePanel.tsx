import { useProjectApi } from "./ProjectApiContext";
import { useEffect, useMemo, useRef, useState, type PointerEvent } from "react";
import { errMsg } from "../api";
import type { AlignmentAnchor, ReferenceMedia, ScoreRegion, VersionSummary } from "../types";
import { Button, Section } from "./common";
import { alignedValue } from "./referenceAlignment";
import { pauseOtherMedia } from "./mediaPlayback";
import { ListeningEqPanel } from "./ListeningEqPanel";

function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result).split(",", 2)[1]);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

export function ReferencePanel({ score, selection, onLocate, onCreated, onCursor, onReferencesChanged }: {
  score: VersionSummary | null; selection: ScoreRegion | null;
  onLocate: (region: ScoreRegion) => void; onCreated: (id: string) => void;
  onCursor: (beat: number | null) => void;
  onReferencesChanged: () => void;
}) {
  const api = useProjectApi();
  const [references, setReferences] = useState<ReferenceMedia[]>([]);
  const [assetId, setAssetId] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [start, setStart] = useState("0");
  const [end, setEnd] = useState("20");
  const [rate, setRate] = useState(1);
  const [loop, setLoop] = useState(true);
  const [playing, setPlaying] = useState(false);
  const [followScore, setFollowScore] = useState(true);
  const [floatingVideo, setFloatingVideo] = useState(false);
  const [position, setPosition] = useState(0);
  const [anchors, setAnchors] = useState<AlignmentAnchor[]>([]);
  const [draftBeats, setDraftBeats] = useState("32");
  const [meter, setMeter] = useState("4/4");
  const mediaRef = useRef<HTMLMediaElement | null>(null);
  const [mediaReady, setMediaReady] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const videoFileRef = useRef<HTMLInputElement>(null);
  const dragRef = useRef<number | null>(null);
  const asset = references.find((item) => item.id === assetId) ?? null;
  const linked = score?.reference?.asset_id === assetId ? score.reference : null;
  const dirty = !!asset && JSON.stringify(anchors) !== JSON.stringify(asset.anchors);
  const validRange = !!asset && start.trim() !== "" && end.trim() !== "" && Number.isFinite(Number(start)) && Number.isFinite(Number(end))
    && Number(start) >= 0 && Number(end) > Number(start) && Number(end) <= asset.duration_seconds + 1e-6;

  useEffect(() => {
    let cancelled = false;
    api.references().then((env) => {
      if (cancelled) return;
      setReferences(env.result.references);
      setAssetId((current) => current || env.result.references[0]?.id || "");
    }).catch((e) => { if (!cancelled) setError(errMsg(e)); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => { if (score?.reference) setAssetId(score.reference.asset_id); }, [score?.reference?.asset_id]);
  useEffect(() => {
    if (!asset) return;
    setStart(String(asset.anchors[0]?.seconds ?? 0));
    setEnd(String(asset.anchors.at(-1)?.seconds ?? Math.min(20, asset.duration_seconds)));
    setAnchors(asset.anchors); setPosition(0); setNotice(""); setPlaying(false); setFloatingVideo(false);
    setMediaReady((mediaRef.current?.readyState ?? 0) >= 1);
    // Switching source material resets the local listening range; saved alignment stays intact.
  }, [asset?.id]);

  useEffect(() => {
    if (mediaRef.current) { mediaRef.current.playbackRate = rate; mediaRef.current.preservesPitch = true; }
  }, [rate, assetId]);

  useEffect(() => {
    if (!playing) return;
    let frame = 0;
    let lastDisplay = 0;
    function tick() {
      const player = mediaRef.current;
      if (player) {
        if (!player.paused && validRange && player.currentTime >= Number(end)) {
          if (loop) player.currentTime = Number(start);
          else player.pause();
        }
        const now = performance.now();
        if (now - lastDisplay >= 65) { setPosition(player.currentTime); lastDisplay = now; }
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, start, end, loop, validRange]);

  async function importFile(file: File, video = false) {
    setBusy(true); setError(null);
    try {
      const maxMB = video ? 256 : 64;
      if (file.size > maxMB * 1024 * 1024) throw new Error(`请选择不超过 ${maxMB} MB 的${video ? "视频" : "音频"}片段。`);
      setNotice(video ? "正在生成视频预览和波形，原视频会完整保留…" : "正在保存音频…");
      const record = (await (video ? api.importVideo(await fileBase64(file), file.name) : api.importAudio(await fileBase64(file), file.name))).result.reference;
      setReferences((items) => [...items.filter((item) => item.id !== record.id), record]); setAssetId(record.id);
      onReferencesChanged();
      setNotice("原件与播放副本已保存到本机。");
    } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  }

  async function playRange() {
    if (!validRange || !mediaRef.current) return;
    const player = mediaRef.current;
    player.currentTime = Number(start); player.playbackRate = rate; player.preservesPitch = true;
    try { await player.play(); } catch (e) { setError(errMsg(e)); }
  }

  function startMedia() {
    const player = mediaRef.current;
    if (player) { player.playbackRate=rate; player.preservesPitch=true; pauseOtherMedia(player); }
    setPlaying(true);
  }

  function loadedMedia() {
    setMediaReady(true);
    if (mediaRef.current) { mediaRef.current.playbackRate=rate; mediaRef.current.preservesPitch=true; }
  }

  function stepVideo(delta: number) {
    const player=mediaRef.current;
    if (!player || !asset) return;
    player.pause();
    player.currentTime=Math.max(0,Math.min(asset.duration_seconds-0.001,player.currentTime+delta));
    setPosition(player.currentTime);
  }

  async function saveAnchors() {
    if (!asset) return;
    setBusy(true); setError(null);
    try {
      const record = (await api.saveAlignment(asset.id, anchors)).result.reference;
      setReferences((items) => items.map((item) => item.id === record.id ? record : item));
      setNotice("对齐已保存。已有谱稿保留自己的对齐快照；可用下方按钮生成重新对齐的新稿。");
    } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  }

  async function draft(attach = false) {
    setBusy(true); setError(null);
    try {
      const [numerator, denominator] = meter.split("/").map(Number);
      const result = attach && score && asset
        ? await api.attachReference(score.version_id, asset.id)
        : await api.createDraft({ title: asset ? `${asset.filename} · 扒谱草稿` : "听辨草稿",
            reference_id: asset?.id, length_beats: Number(draftBeats), numerator, denominator });
      onCreated(result.result.version.version_id);
      setNotice("新稿已保存，可在卷帘下方开始记音。");
    } catch (e) { setError(errMsg(e)); } finally { setBusy(false); }
  }

  function timeAt(event: PointerEvent<SVGSVGElement>): number {
    if (!asset) return 0;
    const rect = event.currentTarget.getBoundingClientRect();
    return Math.round(Math.max(0, Math.min(1, (event.clientX - rect.left) / rect.width)) * asset.duration_seconds * 100) / 100;
  }

  const wave = useMemo(() => {
    if (!asset) return "";
    const peak = Math.max(0.01, ...asset.peaks.flatMap((pair) => pair.map(Math.abs)));
    return asset.peaks.map(([low, high], i) => {
      const x = i / asset.peaks.length * 1000;
      return `M${x.toFixed(2)},${(65 - high / peak * 52).toFixed(2)}V${(65 - low / peak * 52).toFixed(2)}`;
    }).join(" ");
  }, [asset]);
  const linkedStart = linked && selection ? alignedValue(linked.anchors, selection.start_beat, "beat") : null;
  const linkedEnd = linked && selection ? alignedValue(linked.anchors, selection.end_beat, "beat") : null;
  const beatStart = linked && validRange ? alignedValue(linked.anchors, Number(start), "seconds") : null;
  const beatEnd = linked && validRange ? alignedValue(linked.anchors, Number(end), "seconds") : null;
  const positionBeat = linked ? alignedValue(linked.anchors, position, "seconds") : null;
  const cursorBeat = followScore ? positionBeat : null;
  useEffect(() => { onCursor(cursorBeat); }, [cursorBeat, onCursor]);

  return <Section title="原曲音视频 · 听辨与扒谱">
    <div className="action-row">
      <input type="file" ref={fileRef} hidden accept=".wav,.flac,.ogg,.mp3,audio/*" onChange={(e) => { const file=e.target.files?.[0]; if (file) void importFile(file); e.target.value=""; }} />
      <Button disabled={busy} variant="primary" onClick={() => fileRef.current?.click()}>{busy ? "处理中…" : "导入原曲音频"}</Button>
      <input type="file" ref={videoFileRef} hidden accept=".mp4,.m4v,.webm,.mov,.mkv,.avi,video/*" onChange={(e) => {const file=e.target.files?.[0]; if(file) void importFile(file,true); e.target.value="";}} />
      <Button disabled={busy} onClick={() => videoFileRef.current?.click()}>导入参考视频</Button>
      {references.length ? <select aria-label="参考材料" className="reference-select" value={assetId} onChange={(e) => setAssetId(e.target.value)}>
        {references.map((item) => <option value={item.id} key={item.id}>{item.media_kind === "video" ? "视频 · " : "音频 · "}{item.filename}</option>)}
      </select> : <span className="muted">音频或本地演奏视频 · 原件保留</span>}
    </div>
    {error ? <p role="alert" className="error">{error}</p> : null}
    {notice ? <p role="status" className="saved-message">{notice}</p> : null}
    {asset ? <>
      <p className="muted">{asset.duration_seconds.toFixed(2)} 秒 · {asset.media_kind === "video"
        ? `${asset.video_width} × ${asset.video_height} · ${asset.has_audio ? "带声音" : "无音轨"}`
        : `${asset.channels} 声道 · ${asset.sample_rate} Hz`} · <a href={api.artifactUrl(asset.original_token)} download={asset.filename}>下载原件</a></p>
      {asset.media_kind === "video" && asset.video_token ? <div className="reference-video-stage">
        <div className={`reference-video-view${floatingVideo ? " is-floating" : ""}`}>
        <div className="reference-video-tools"><span>视频对照</span><Button onClick={() => setFloatingVideo((value) => !value)}>{floatingVideo ? "返回原位" : "悬浮对照"}</Button></div>
        <video aria-label="参考视频播放器" key={asset.id} ref={(node) => {mediaRef.current=node;}} controls playsInline preload="metadata"
          src={api.artifactUrl(asset.video_token)} onLoadedMetadata={loadedMedia} onPlay={startMedia}
          onPause={() => setPlaying(false)} onTimeUpdate={() => setPosition(mediaRef.current?.currentTime ?? 0)}
          onEnded={() => {if(loop && validRange) void playRange();}}
          onError={() => setError("视频预览无法播放，请重新导入或检查服务连接。")} />
        </div>
        <div className="action-row"><Button disabled={!mediaReady} onClick={() => stepVideo(-0.05)}>← 0.05 秒</Button>
          <Button disabled={!mediaReady} onClick={() => stepVideo(0.05)}>0.05 秒 →</Button>
          <Button disabled={!mediaReady} onClick={() => setStart(String(Number(position.toFixed(3))))}>当前位置设为片段起点</Button>
          <Button disabled={!mediaReady} onClick={() => setEnd(String(Number(position.toFixed(3))))}>当前位置设为片段终点</Button>
          <Button disabled={positionBeat === null || !linked || positionBeat >= (linked.anchors.at(-1)?.beat ?? 0)} onClick={() => {
            if(positionBeat === null || !linked) return;
            onLocate({start_beat:positionBeat,end_beat:Math.min(positionBeat+0.25,linked.anchors.at(-1)?.beat ?? positionBeat+0.25)});
          }}>在谱稿中定位当前画面</Button></div>
        <p className="muted">暂停后小步查看琴键、手部和光条；可用播放器全屏放大。微移按秒定位，不保证恰好移动原视频一帧。</p>
      </div> : null}
      {asset.media_kind === "video" && !asset.has_audio ? <p className="muted">此视频没有音轨，仍可依据画面建立拍点和谱稿。</p> : null}
      <svg className="reference-wave" viewBox="0 0 1000 140" role="group" aria-label="参考音频波形"
        onPointerDown={(e) => { if (e.button !== 0) return; dragRef.current=timeAt(e); e.currentTarget.setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => { if (dragRef.current === null) return; const t=timeAt(e); setStart(String(Math.min(t, dragRef.current))); setEnd(String(Math.min(asset.duration_seconds, Math.max(t, dragRef.current)))); }}
        onPointerUp={(e) => { if (dragRef.current === null) return; const t=timeAt(e); const first=Math.min(t,dragRef.current); setStart(String(first)); setEnd(String(Math.min(asset.duration_seconds,Math.max(t,dragRef.current,first+0.1)))); dragRef.current=null; e.currentTarget.releasePointerCapture(e.pointerId); }}
        onPointerCancel={() => { dragRef.current=null; }}>
        <rect width={1000} height={140} fill="#172132" /><path d={wave} stroke="#74c5d5" strokeWidth={0.8} />
        {validRange ? <rect data-testid="reference-selection" x={Number(start)/asset.duration_seconds*1000} width={(Number(end)-Number(start))/asset.duration_seconds*1000} height={140} fill="#e8b96c" fillOpacity={0.18} stroke="#e8b96c" /> : null}
        <line x1={position/asset.duration_seconds*1000} x2={position/asset.duration_seconds*1000} y1={0} y2={140} stroke="#ff737d" strokeWidth={2} />
        <text x={6} y={135} fill="#acbdd3" fontSize={12}>0 秒</text><text x={995} y={135} textAnchor="end" fill="#acbdd3" fontSize={12}>{asset.duration_seconds.toFixed(1)} 秒</text>
      </svg>
      <div className="reference-controls">
        <label>选段起点（秒）<input aria-label="原曲起始秒" type="number" min={0} step={0.01} value={start} onChange={(e) => setStart(e.target.value)} /></label>
        <label>选段终点（秒）<input aria-label="原曲结束秒" type="number" min={0} step={0.01} value={end} onChange={(e) => setEnd(e.target.value)} /></label>
        <label>播放速度<select aria-label="听辨速度" value={rate} onChange={(e) => setRate(Number(e.target.value))}><option value={0.25}>0.25×</option><option value={0.5}>0.5×</option><option value={0.75}>0.75×</option><option value={1}>1×</option></select></label>
        <label className="checkbox-label"><input type="checkbox" checked={loop} onChange={(e) => setLoop(e.target.checked)} />循环选段</label>
        <Button disabled={!validRange || !mediaReady} onClick={() => void playRange()}>播放原曲选段</Button>
      </div>
      {asset.media_kind !== "video" && asset.playback_token ? <audio aria-label="原曲播放器" key={asset.id} ref={(node) => {mediaRef.current=node;}} controls src={api.artifactUrl(asset.playback_token)}
        onLoadedMetadata={loadedMedia} onPlay={startMedia}
        onPause={() => setPlaying(false)} onTimeUpdate={() => setPosition(mediaRef.current?.currentTime ?? 0)}
        onEnded={() => { if (loop && validRange) void playRange(); }} /> : null}
      <span className="muted"> {position.toFixed(3)} 秒{asset.has_audio ? " · 降速保持音高" : ""}</span>
      {asset.has_audio ? <ListeningEqPanel key={`eq-${asset.id}`} mediaRef={mediaRef} /> : null}
      <label className="checkbox-label"><input type="checkbox" checked={followScore} onChange={(event) => setFollowScore(event.target.checked)} />同步谱稿播放线
        {cursorBeat !== null ? <span> · 谱稿第 {cursorBeat.toFixed(2)} 拍</span> : <span className="muted"> · 需关联谱稿且位于锚点范围内</span>}
      </label>
      <div className="action-row">
        <Button disabled={linkedStart === null || linkedEnd === null} onClick={() => {setStart(String(linkedStart));setEnd(String(linkedEnd));}}>用卷帘选区设置听辨范围</Button>
        <Button disabled={beatStart === null || beatEnd === null} onClick={() => {if(beatStart!==null && beatEnd!==null) onLocate({start_beat:beatStart,end_beat:beatEnd});}}>在谱稿中定位此片段</Button>
      </div>
      <details className="alignment-editor" open={asset.anchors.length < 2}>
        <summary>音视频 ↔ 乐谱对齐 · {asset.anchors.length >= 2 ? "已保存锚点" : "待标记"}{dirty ? " · 有未保存修改" : ""}</summary>
        <p className="muted">标记哪一秒对应哪一拍，第一拍从 0 开始。变速时可增加中间锚点。已有谱稿保留创建时的对齐。</p>
        <div className="action-row"><label>片段对应拍数<input aria-label="草稿拍数" type="number" value={draftBeats} onChange={(e) => setDraftBeats(e.target.value)} /></label>
          <Button disabled={!validRange} onClick={() => setAnchors([{seconds:Number(start),beat:0},{seconds:Number(end),beat:Number(draftBeats)}])}>用选段建立两点对齐</Button>
          <Button onClick={() => setAnchors((items) => [...items,{seconds:Number(position.toFixed(2)),beat:items.length?items[items.length-1].beat+4:0}])}>增加当前位置锚点</Button></div>
        {anchors.map((anchor,index) => <div className="anchor-row" key={index}>
          <label>素材秒数<input aria-label={`锚点 ${index+1} 秒数`} type="number" step={0.01} value={anchor.seconds} onChange={(e) => setAnchors((items) => items.map((item,i) => i===index?{...item,seconds:Number(e.target.value)}:item))} /></label>
          <span>↔</span><label>谱稿拍点<input aria-label={`锚点 ${index+1} 拍点`} type="number" step={0.25} value={anchor.beat} onChange={(e) => setAnchors((items) => items.map((item,i) => i===index?{...item,beat:Number(e.target.value)}:item))} /></label>
          <Button onClick={() => setAnchors((items) => items.filter((_,i) => i!==index))}>移除此锚点</Button>
        </div>)}
        <Button disabled={busy || anchors.length < 2} onClick={() => void saveAnchors()}>保存对齐锚点</Button>
      </details>
    </> : <p className="muted">先导入原曲，反复听辨一段，再建立旋律与低音草稿。也可以直接新建空白草稿。</p>}
    <div className="action-row">
      <label>草稿拍号<select aria-label="草稿拍号" value={meter} onChange={(e) => setMeter(e.target.value)}><option>4/4</option><option>3/4</option><option>6/8</option><option>9/8</option></select></label>
      <Button disabled={busy || (!!asset && (asset.anchors.length < 2 || dirty))} onClick={() => void draft()}>新建扒谱草稿</Button>
      {asset && score ? <Button disabled={busy || asset.anchors.length < 2 || dirty} onClick={() => void draft(true)}>按这些锚点对齐当前谱稿（新版本）</Button> : null}
    </div>
  </Section>;
}
