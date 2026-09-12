import { useEffect, useRef, useState, type RefObject } from "react";
import { defaultBands, eqPresets, ListeningEq, type EqBand } from "./listeningEq";

const names = ["低频", "中频", "高频"];
const bounds = [[80, 800], [200, 4000], [500, 8000]];

export function ListeningEqPanel({ mediaRef }: { mediaRef: RefObject<HTMLMediaElement | null> }) {
  const graph = useRef<ListeningEq | null>(null);
  const [bands, setBands] = useState(defaultBands);
  const [bypass, setBypass] = useState(true);
  const [response, setResponse] = useState<number[]>(Array<number>(241).fill(0));
  const [error, setError] = useState("");
  useEffect(() => () => { graph.current?.dispose(); graph.current = null; }, []);

  function change(next: EqBand[], off: boolean) {
    const media = mediaRef.current;
    if (!media) return;
    try {
      graph.current ??= new ListeningEq(media, setError);
      setResponse(graph.current.apply(next, off));
      setBands(next); setBypass(off); setError("");
      void graph.current.resume().catch(() => setError("浏览器未能启动听辨音频，请再次点击预设或原声。"));
    } catch { setError("当前浏览器无法启用频段听辨，请使用支持 Web Audio 的浏览器。原件仍可下载核对。"); }
  }

  const path = response.map((db, i) => `${i ? "L" : "M"}${45 + i / 240 * 690},${20 - Math.max(-48, Math.min(0, db)) / 48 * 130}`).join(" ");
  return <div className="listening-eq">
    <h3>频段辅助听辨</h3>
    <p className="muted">压低抢耳的频段，逐音核对伴奏。频段不等于声部：泛音和重叠音仍会混在一起，听不清的音请标为待核对。</p>
    <div className="action-row">
      <button type="button" className="btn" aria-pressed={bypass} onClick={() => change(bands, true)}>原声</button>
      {Object.entries(eqPresets).map(([id, preset]) => <button type="button" className="btn" key={id}
        aria-pressed={!bypass && bands.every((band, i) => band.gain === preset.gains[i] && band.frequency === defaultBands()[i].frequency)}
        onClick={() => change(defaultBands().map((band, i) => ({ ...band, gain: preset.gains[i] })), false)}>{preset.label}</button>)}
      <button type="button" className="btn" aria-pressed={!bypass} onClick={() => change(bands, false)}>使用当前曲线</button>
    </div>
    <p role="status">{bypass ? "正在听原声" : "正在听 EQ 处理后的参考音频"} · 切换保留播放位置 · 仅本次听辨生效</p>
    <svg className="eq-curve" viewBox="0 0 760 182" role="img" aria-label="EQ 频率响应曲线，横轴频率 Hz，纵轴增益 dB">
      {[0, -12, -24, -36, -48].map((db) => <g key={db}><line x1={45} x2={735} y1={20 - db / 48 * 130} y2={20 - db / 48 * 130} stroke="#35435a" /><text x={38} y={24 - db / 48 * 130} textAnchor="end">{db}</text></g>)}
      {[20, 100, 300, 1000, 3000, 10000, 20000].map((hz) => {
        const x = 45 + Math.log10(hz / 20) / 3 * 690;
        return <g key={hz}><line x1={x} x2={x} y1={20} y2={150} stroke="#35435a" /><text x={x} y={174} textAnchor="middle">{hz >= 1000 ? `${hz / 1000}k` : hz}</text></g>;
      })}
      <path d={path} fill="none" stroke="#e8b96c" strokeWidth={3} />
    </svg>
    <div className="eq-bands">{bands.map((band, index) => <fieldset key={band.type}>
      <legend>{names[index]}{index === 1 ? " · 钟形" : " · 搁架"}</legend>
      <label>{index === 1 ? "中心" : "转折"}频率 · {band.frequency} Hz
        <input aria-label={`${names[index]}频率`} type="range" min={bounds[index][0]} max={bounds[index][1]} step={10} value={band.frequency}
          onChange={(e) => change(bands.map((item, i) => i === index ? { ...item, frequency: Number(e.target.value) } : item), false)} /></label>
      <label>增益 · {band.gain} dB
        <input aria-label={`${names[index]}增益`} type="range" min={-24} max={0} step={1} value={band.gain}
          onChange={(e) => change(bands.map((item, i) => i === index ? { ...item, gain: Number(e.target.value) } : item), false)} /></label>
    </fieldset>)}</div>
    <p className="muted">曲线表示频率增益，不是音符轨迹。通过衰减其他频段相对突出目标；先试“突出低频”，再调整高频转折点。原声核对后再确认音符。</p>
    {error ? <p role="alert" className="error">{error}</p> : null}
  </div>;
}
