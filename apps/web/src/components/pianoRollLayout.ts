// Rendering coordinates derived from the score's existing conductor maps.
// No musical analysis or score mutation belongs in this module.
import type { Meter, Tempo } from "../types";

export function pitchLabel(pitch: number): string {
  const names = ["C", "C♯", "D", "E♭", "E", "F", "F♯", "G", "A♭", "A", "B♭", "B"];
  return `${names[pitch % 12]}${Math.floor(pitch / 12) - 1}`;
}

export interface RulerBar { number: number; start: number; end: number; meter: string }

export function rulerBars(meters: Meter[], start: number, end: number): RulerBar[] {
  const map = new Map<number, Meter>([[0, { beat: 0, numerator: 4, denominator: 4 }]]);
  for (const meter of meters) {
    if (Number.isFinite(meter.beat) && meter.beat >= 0 && meter.numerator > 0 && meter.denominator > 0) map.set(meter.beat, meter);
  }
  const changes = [...map.values()].sort((a, b) => a.beat - b.beat);
  const result: RulerBar[] = [];
  let number = 1;
  for (let i = 0; i < changes.length; i++) {
    const meter = changes[i];
    if (meter.beat >= end) break;
    const limit = Math.min(changes[i + 1]?.beat ?? end, end);
    const width = meter.numerator * 4 / meter.denominator;
    const count = Math.ceil((limit - meter.beat) / width - 1e-10);
    const firstVisible = Math.max(0, Math.floor((start - meter.beat) / width));
    for (let j = firstVisible; j < count && result.length < 2048; j++) {
      result.push({ number: number + j, start: meter.beat + j * width,
        end: Math.min(meter.beat + (j + 1) * width, limit), meter: `${meter.numerator}/${meter.denominator}` });
    }
    number += count;
  }
  return result;
}

function tempoMap(tempos: Tempo[]): Tempo[] {
  const map = new Map<number, Tempo>([[0, { beat: 0, bpm: 120 }]]);
  for (const tempo of tempos) if (tempo.beat >= 0 && Number.isFinite(tempo.bpm) && tempo.bpm > 0) map.set(tempo.beat, tempo);
  return [...map.values()].sort((a, b) => a.beat - b.beat);
}

export function beatSeconds(tempos: Tempo[], beat: number): number {
  const changes = tempoMap(tempos);
  let seconds = 0;
  for (let i = 0; i < changes.length; i++) {
    if (changes[i].beat >= beat) break;
    seconds += (Math.min(changes[i + 1]?.beat ?? beat, beat) - changes[i].beat) * 60 / changes[i].bpm;
  }
  return seconds;
}

export function secondsBeat(tempos: Tempo[], seconds: number): number {
  const changes = tempoMap(tempos);
  let elapsed = 0;
  for (let i = 0; i < changes.length; i++) {
    const tempo = changes[i];
    const span = ((changes[i + 1]?.beat ?? Infinity) - tempo.beat) * 60 / tempo.bpm;
    if (seconds < elapsed + span) return tempo.beat + (seconds - elapsed) * tempo.bpm / 60;
    elapsed += span;
  }
  return 0;
}
