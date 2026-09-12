import { useProjectApi } from "./ProjectApiContext";
import { useEffect, useRef, useState } from "react";

import { errMsg } from "../api";
import type { RenderResult } from "../types";
import { Button } from "./common";
import { pauseOtherMedia } from "./mediaPlayback";

export function ABPlayer({ aId, bId }: { aId: string; bId: string }) {
  const api = useProjectApi();
  const [pair, setPair] = useState<[RenderResult, RenderResult] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);
  const aRef = useRef<HTMLAudioElement>(null);
  const bRef = useRef<HTMLAudioElement>(null);

  useEffect(() => {
    let cancelled = false;
    setPair(null);
    setError(null);
    Promise.all([api.render(aId, "preview"), api.render(bId, "preview")])
      .then(([a, b]) => { if (!cancelled) setPair([a.result, b.result]); })
      .catch((e) => { if (!cancelled) setError(errMsg(e)); });
    return () => { cancelled = true; };
  }, [aId, bId, attempt]);

  async function play(side: "a" | "b", restart = false) {
    const target = side === "a" ? aRef.current : bRef.current;
    const other = side === "a" ? bRef.current : aRef.current;
    if (!target || !other) return;
    const position = restart ? 0 : !other.paused ? other.currentTime : target.currentTime;
    other.pause();
    target.currentTime = Number.isFinite(target.duration) ? Math.min(position, Math.max(0, target.duration - 0.01)) : position;
    try { await target.play(); } catch (e) { setError(errMsg(e)); }
  }

  return <div className="ab-player">
    <h4>A/B 合成预听</h4>
    <p className="muted">两版使用相同音色与固定增益，保留速度、力度和踏板。切换时沿用播放秒数；节奏缩放后建议从头比较。</p>
    {error ? <p role="alert">{error} <Button onClick={() => setAttempt((value) => value + 1)}>重试试听</Button></p> : null}
    {!pair && !error ? <p role="status">正在准备两版 WAV…</p> : null}
    {pair ? <>
      <div className="ab-columns">
        <div><strong>A · 基线</strong>
          <audio aria-label="版本 A 音频" ref={aRef} controls preload="auto" src={api.artifactUrl(pair[0].artifact_token)} onPlay={() => {if(aRef.current) pauseOtherMedia(aRef.current);}} />
          <Button onClick={() => void play("a")}>播放 / 切换 A</Button>
          <Button onClick={() => void play("a", true)}>从头播放 A</Button>
        </div>
        <div><strong>B · 候选</strong>
          <audio aria-label="版本 B 音频" ref={bRef} controls preload="auto" src={api.artifactUrl(pair[1].artifact_token)} onPlay={() => {if(bRef.current) pauseOtherMedia(bRef.current);}} />
          <Button onClick={() => void play("b")}>播放 / 切换 B</Button>
          <Button onClick={() => void play("b", true)}>从头播放 B</Button>
        </div>
      </div>
      <details><summary>预听说明</summary><ul>{[...new Set(pair.flatMap((result) => result.warnings))].map((warning) => <li key={warning}>{warning}</li>)}</ul></details>
    </> : null}
  </div>;
}
