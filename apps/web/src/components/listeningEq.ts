// Playback-only equalization. Settings never change reference assets or score evidence.
export type EqBand = { type: BiquadFilterType; frequency: number; gain: number; Q: number };
export const eqPresets: Record<string, { label: string; gains: number[] }> = {
  low: { label: "突出低频", gains: [0, -8, -22] },
  mid: { label: "突出中频", gains: [-18, 0, -18] },
  high: { label: "突出高频", gains: [-22, -8, 0] },
};
export function defaultBands(): EqBand[] {
  return [
    { type: "lowshelf", frequency: 300, gain: 0, Q: 0.7 },
    { type: "peaking", frequency: 900, gain: 0, Q: 0.7 },
    { type: "highshelf", frequency: 2000, gain: 0, Q: 0.7 },
  ];
}

export class ListeningEq {
  readonly context: AudioContext;
  private readonly source: MediaElementAudioSourceNode;
  private readonly filters: BiquadFilterNode[];
  private readonly resumeOnPlay: () => void;
  private readonly media: HTMLMediaElement;

  constructor(media: HTMLMediaElement, onError: (message: string) => void) {
    this.media = media;
    this.context = new AudioContext();
    this.filters = defaultBands().map((band) => {
      const filter = this.context.createBiquadFilter();
      filter.type = band.type;
      filter.frequency.value = band.frequency;
      filter.Q.value = band.Q;
      return filter;
    });
    try { this.source = this.context.createMediaElementSource(media); }
    catch (error) { void this.context.close(); throw error; }
    this.source.connect(this.filters[0]);
    this.filters.forEach((filter, index) => filter.connect(this.filters[index + 1] ?? this.context.destination));
    this.resumeOnPlay = () => { void this.context.resume().catch(() => onError("听辨音频未能恢复，请再次点击原声或听辨预设。")); };
    media.addEventListener("play", this.resumeOnPlay);
  }

  async resume(): Promise<void> { await this.context.resume(); }

  apply(bands: EqBand[], bypass: boolean): number[] {
    const frequencies = Float32Array.from({ length: 241 }, (_, i) => 20 * 1000 ** (i / 240));
    const response = Array<number>(frequencies.length).fill(0);
    const magnitude = new Float32Array(frequencies.length);
    const phase = new Float32Array(frequencies.length);
    this.filters.forEach((filter, index) => {
      const band = bands[index];
      const frequency = Math.min(band.frequency, this.context.sampleRate * 0.49);
      // Smooth audible changes; a disconnected probe reports the settled response curve.
      filter.frequency.setTargetAtTime(frequency, this.context.currentTime, 0.015);
      filter.gain.setTargetAtTime(bypass ? 0 : band.gain, this.context.currentTime, 0.015);
      filter.Q.setTargetAtTime(band.Q, this.context.currentTime, 0.015);
      const probe = this.context.createBiquadFilter();
      probe.type = filter.type; probe.frequency.value = frequency;
      probe.gain.value = bypass ? 0 : band.gain; probe.Q.value = band.Q;
      probe.getFrequencyResponse(frequencies, magnitude, phase);
      magnitude.forEach((value, i) => { response[i] += Number.isFinite(value) ? 20 * Math.log10(Math.max(1e-6, value)) : 0; });
    });
    return response;
  }

  dispose(): void {
    this.media.pause();
    this.media.removeEventListener("play", this.resumeOnPlay);
    this.source.disconnect();
    this.filters.forEach((filter) => filter.disconnect());
    void this.context.close().catch(() => undefined);
  }
}
