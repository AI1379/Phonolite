"""Meter-aware bar spans and tempo-aware beat conversion.

A meter change starts a new bar. A change inside an unfinished bar closes
that partial bar; bar labels never pretend that the first meter is global.
Missing meter and tempo default to 4/4 and 120 BPM respectively.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from music_core.ir import MeterEvent, Region, ScoreDocument, meter_beats_per_bar


@dataclass(frozen=True)
class BarSpan:
    number: int
    start: float
    end: float
    beats_per_bar: float

    @property
    def complete(self) -> bool:
        return math.isclose(self.end - self.start, self.beats_per_bar, abs_tol=1e-8)


def bar_spans(doc: ScoreDocument, end_beat: float) -> list[BarSpan]:
    """Return score-aligned bars intersecting [0, end_beat)."""
    if not math.isfinite(end_beat) or end_beat < 0 or end_beat > 100_000:
        raise ValueError("analysis span must be finite and at most 100000 beats")
    meters = {0.0: MeterEvent(0.0, 4, 4)}
    for meter in doc.meters:
        if not math.isfinite(meter.beat) or meter.beat < 0:
            raise ValueError("meter positions must be finite and non-negative")
        if meter.numerator <= 0 or meter.denominator <= 0:
            raise ValueError("meter components must be positive")
        meters[meter.beat] = meter
    changes = sorted(meters.items())
    spans: list[BarSpan] = []
    for index, (start, meter) in enumerate(changes):
        limit = min(end_beat, changes[index + 1][0]) if index + 1 < len(changes) else end_beat
        width = meter_beats_per_bar(meter)
        cursor = start
        while cursor < limit - 1e-9:
            if len(spans) >= 10_000:
                raise ValueError("analysis is limited to 10000 bars")
            end = min(cursor + width, limit)
            spans.append(BarSpan(len(spans) + 1, cursor, end, width))
            cursor = end
    return spans


def region_bars(doc: ScoreDocument, region: Region) -> list[BarSpan]:
    """Return intersections with actual bars, preserving global numbering."""
    return [BarSpan(bar.number, max(bar.start, region.start_beat), bar.end, bar.beats_per_bar)
            for bar in bar_spans(doc, region.end_beat) if bar.end > region.start_beat]


def beat_to_seconds(doc: ScoreDocument, beat: float) -> float:
    """Integrate the piecewise-constant tempo map in quarter-note beats."""
    if not math.isfinite(beat) or beat < 0:
        raise ValueError("beat must be finite and non-negative")
    tempos: dict[float, float] = {0.0: 120.0}
    for tempo in doc.tempos:
        if not math.isfinite(tempo.bpm) or not math.isfinite(tempo.beat) or tempo.bpm <= 0 or tempo.beat < 0:
            raise ValueError("tempo positions and BPM must be valid")
        tempos[tempo.beat] = tempo.bpm
    seconds, cursor, bpm = 0.0, 0.0, 120.0
    for position, value in sorted(tempos.items()):
        if position > beat:
            break
        seconds += (position - cursor) * 60.0 / bpm
        cursor, bpm = position, value
    return seconds + (beat - cursor) * 60.0 / bpm
