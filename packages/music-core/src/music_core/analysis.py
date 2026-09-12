"""Music analysis producing locatable, confidence-bearing findings.

Implements design doc issue #4 (``analysis: register, density and bass
contour``) and backs the ``inspect_score`` step of the first vertical slice.

Design red lines enforced here:

  - **Findings are locatable**: every finding carries a beat span (and the
    corresponding bar numbers when a meter is known) plus the tracks it came
    from, so the UI/agent can highlight exactly where it applies.
  - **Observation vs. interpretation are separated**: the ``observation``
    field states a measured fact; ``interpretation`` is a hypothesis with a
    ``confidence`` in [0, 1] and explicit ``alternatives``.
  - **Deterministic metrics first**: range in semitones, note counts, and
    bass-pitch sequences are computed exactly; only the *meaning* of those
    numbers (e.g. "this feels repetitive") carries sub-1.0 confidence.
  - **No file modification**: analysis is read-only.

Bar numbers are 1-indexed; beat 0 is the start of bar 1. When the document
has no meter, bars default to 4/4 (4 beats per bar) purely so locations stay
human-readable — the beat span is always authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass

from music_core.ir import (
    NoteEvent,
    ScoreDocument,
    Region,
)
from music_core.timing import region_bars

# Octave used to normalise pitch-distance similarities into [0, 1].
_PITCH_NORMALISER = 12.0


@dataclass(frozen=True)
class Location:
    """Where a finding applies, in beats and (best-effort) bar numbers."""

    start_beat: float
    end_beat: float
    bars: tuple[int, int] | None
    track_ids: tuple[str, ...]

    def render_bars(self) -> str:
        """Human-readable bar span, e.g. ``"bars 9-16"`` or ``"beats 2.0-6.0"``."""
        if self.bars is not None:
            lo, hi = self.bars
            return f"bars {lo}-{hi}" if hi != lo else f"bar {lo}"
        return f"beats {self.start_beat:g}-{self.end_beat:g}"


@dataclass(frozen=True)
class Evidence:
    """One measured metric supporting a finding."""

    metric: str
    value: str | int | float


@dataclass(frozen=True)
class Finding:
    """A locatable, confidence-bearing analytical conclusion.

    ``observation`` is factual (backed by ``evidence``); ``interpretation``
    is the hypothesis the agent/UI may act on, hedged by ``confidence`` and
    ``alternatives``.
    """

    observation: str
    location: Location
    evidence: list[Evidence]
    interpretation: str
    confidence: float
    alternatives: list[str]
    category: str = "overview"
    note_ids: tuple[str, ...] = ()


def _effective_region(doc: ScoreDocument, region: Region | None) -> Region:
    """The region to analyse: the given one, or the whole document span."""
    if region is not None:
        return region
    end = doc.duration_beats
    return Region(0.0, end if end > 0.0 else 0.0)


def _location(
    region: Region, doc: ScoreDocument, notes: list[NoteEvent]
) -> Location:
    """Build a Location, attaching bar numbers when a meter is known."""
    has_meter = bool(doc.meters)
    bars: tuple[int, int] | None = None
    spans = region_bars(doc, region)
    if has_meter and spans:
        bars = (spans[0].number, spans[-1].number)
    track_ids = tuple(sorted({n.track_id for n in notes})) if notes else tuple()
    if region.track_ids is not None:
        track_ids = region.track_ids
    return Location(
        start_beat=region.start_beat,
        end_beat=region.end_beat,
        bars=bars,
        track_ids=track_ids,
    )


def _notes_in(doc: ScoreDocument, region: Region | None) -> list[NoteEvent]:
    """Notes overlapping the effective region, sorted by (onset, pitch)."""
    return doc.select_region(_effective_region(doc, region))


def _bass_pitch_at(beat: float, notes: list[NoteEvent]) -> int | None:
    """Lowest pitch sounding at ``beat`` (note onset <= beat < offset).

    Zero-duration notes never count as a sounding bass.
    """
    sounding = [
        n.pitch
        for n in notes
        if n.duration_beats > 0.0 and n.onset_beats <= beat < n.offset_beats
    ]
    return min(sounding) if sounding else None


def _bass_pitches_per_bar(
    notes: list[NoteEvent], region: Region, doc: ScoreDocument
) -> list[int]:
    """Lowest pitch at each selected bar start, or its first non-silent attack.

    Empty bars are omitted. A partial first bar is sampled at the selection
    start; this is a representative pitch sequence, not full voice extraction.
    """
    bass: list[int] = []
    for bar in region_bars(doc, region):
        pitch = _bass_pitch_at(bar.start, notes)
        if pitch is None:
            attacks = [n.onset_beats for n in notes
                       if bar.start <= n.onset_beats < bar.end and n.duration_beats > 0]
            if attacks:
                pitch = _bass_pitch_at(min(attacks), notes)
        if pitch is not None:
            bass.append(pitch)
    return bass


def _sequence_similarity(a: list[int], b: list[int]) -> float | None:
    """Pitch-sequence similarity in [0, 1] for equal-length int sequences.

    Returns ``None`` when the sequences differ in length or are empty. Uses a
    normalised mean absolute difference (one octave = full distance), which is
    deterministic and easy to explain.
    """
    if not a or not b or len(a) != len(b):
        return None
    mean_abs_diff = sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    return max(0.0, min(1.0, 1.0 - mean_abs_diff / _PITCH_NORMALISER))


def _directions(seq: list[int]) -> list[int]:
    """Stepwise pitch deltas between consecutive samples (sign = direction)."""
    return [seq[i + 1] - seq[i] for i in range(len(seq) - 1)]


def analyze_register(
    doc: ScoreDocument, region: Region | None = None
) -> list[Finding]:
    """Register / range analysis: overall span and per-bar register stability."""
    notes = _notes_in(doc, region)
    eff = _effective_region(doc, region)
    if not notes:
        return []
    loc = _location(eff, doc, notes)
    pitches = [n.pitch for n in notes]
    lo, hi = min(pitches), max(pitches)
    span = hi - lo

    findings: list[Finding] = [
        Finding(
            observation=(
                f"Register spans {span} semitones (MIDI {lo}-{hi}) "
                f"across {loc.render_bars()}."
            ),
            location=loc,
            evidence=[
                Evidence("register_range_semitones", span),
                Evidence("min_pitch", lo),
                Evidence("max_pitch", hi),
            ],
            interpretation=(
                f"The material stays within a {'narrow' if span <= 7 else 'wide'} "
                f"register."
            ),
            confidence=1.0,
            alternatives=[],
        )
    ]

    # Per-bar register: detect bars that share the exact same min/max, which
    # is one dimension of the "static/repetitive" feeling the slice targets.
    per_bar: list[tuple[int, int, int]] = []  # (bar, min, max)
    for bar in region_bars(doc, eff):
        bar_notes = [
            n.pitch for n in notes if n.onset_beats < bar.end and n.offset_beats > bar.start
        ]
        if bar_notes:
            per_bar.append((bar.number, min(bar_notes), max(bar_notes)))
    if len(per_bar) >= 2:
        same_min = sum(1 for i in range(1, len(per_bar)) if per_bar[i][1] == per_bar[0][1])
        same_max = sum(1 for i in range(1, len(per_bar)) if per_bar[i][2] == per_bar[0][2])
        if same_min + same_max >= len(per_bar):  # most bars match the first
            findings.append(
                Finding(
                    observation=(
                        f"Per-bar register is static: {same_min}/{len(per_bar) - 1} "
                        f"bars share the minimum and {same_max}/{len(per_bar) - 1} "
                        f"the maximum of bar {per_bar[0][0]}."
                    ),
                    location=loc,
                    evidence=[
                        Evidence("bars_sharing_min_pitch", same_min),
                        Evidence("bars_sharing_max_pitch", same_max),
                        Evidence("bar_count", len(per_bar)),
                    ],
                    interpretation=(
                        "Register contributes to a sense of repetition: the "
                        "high and low extremes do not move across bars."
                    ),
                    confidence=0.8,
                    alternatives=[
                        "Register stability may be intentional grounding rather "
                        "than unwanted repetition."
                    ],
                )
            )
    return findings


def analyze_density(
    doc: ScoreDocument, region: Region | None = None
) -> list[Finding]:
    """Density analysis: notes per beat and average simultaneous notes."""
    notes = _notes_in(doc, region)
    eff = _effective_region(doc, region)
    if not notes or eff.end_beat <= eff.start_beat:
        return []
    loc = _location(eff, doc, notes)
    span = eff.end_beat - eff.start_beat
    attacks = [n for n in notes if eff.start_beat <= n.onset_beats < eff.end_beat]
    note_rate = len(attacks) / span

    # Average simultaneous notes: sweep weighted by time.
    events: list[tuple[float, int]] = []
    for n in notes:
        end = n.offset_beats if n.duration_beats > 0.0 else n.onset_beats
        if end > n.onset_beats:
            events.append((max(n.onset_beats, eff.start_beat), 1))
            events.append((min(end, eff.end_beat), -1))
    events.sort()
    active = 0
    last_t = events[0][0] if events else eff.start_beat
    integral = 0.0
    for t, delta in events:
        if t > last_t:
            integral += active * (t - last_t)
        active += delta
        last_t = t
    avg_simultaneity = integral / span if span > 0 else 0.0

    return [
        Finding(
            observation=(
                f"Density is {note_rate:.2f} notes/beat "
                f"({len(attacks)} attacks over {span:.1f} beats) "
                f"with {avg_simultaneity:.2f} keys held on average (pedal excluded)."
            ),
            location=loc,
            evidence=[
                Evidence("notes_per_beat", round(note_rate, 3)),
                Evidence("note_count", len(notes)),
                Evidence("attack_count", len(attacks)),
                Evidence("average_simultaneous_notes", round(avg_simultaneity, 3)),
            ],
            interpretation=(
                f"{'Sparse' if avg_simultaneity < 2.0 else 'Dense'} "
                f"texture in {loc.render_bars()}."
            ),
            confidence=0.85,
            alternatives=["Pedal, articulation and instrumentation can change perceived density."],
        )
    ]


def analyze_bass_contour(
    doc: ScoreDocument, region: Region | None = None
) -> list[Finding]:
    """Bass-line contour: direction and first/second-half similarity."""
    notes = _notes_in(doc, region)
    eff = _effective_region(doc, region)
    if not notes:
        return []
    loc = _location(eff, doc, notes)
    bass = _bass_pitches_per_bar(notes, eff, doc)
    if len(bass) < 2:
        return [
            Finding(
                observation=(
                    f"Bass line has fewer than 2 sampled notes "
                    f"({len(bass)}); contour not measured."
                ),
                location=loc,
                evidence=[Evidence("bass_samples", len(bass))],
                interpretation="Bass contour is inconclusive in this region.",
                confidence=1.0,
                alternatives=[],
            )
        ]

    dirs = _directions(bass)
    rising = sum(1 for d in dirs if d > 0)
    falling = sum(1 for d in dirs if d < 0)
    static = sum(1 for d in dirs if d == 0)
    if rising > falling and rising >= static:
        contour_word = "rising"
    elif falling > rising and falling >= static:
        contour_word = "falling"
    elif static > 0 and static >= max(rising, falling):
        contour_word = "static"
    else:
        contour_word = "mixed"

    evidence: list[Evidence] = [
        Evidence("bass_direction_steps_rising", rising),
        Evidence("bass_direction_steps_falling", falling),
        Evidence("bass_direction_steps_static", static),
        Evidence("bass_net_semitones", bass[-1] - bass[0]),
    ]

    # First vs. second half similarity — the design example's
    # bass_contour_similarity metric.
    mid = len(bass) // 2
    similarity: float | None = None
    if mid > 0:
        similarity = _sequence_similarity(bass[:mid], bass[mid:])
        if similarity is not None:
            evidence.append(Evidence("bass_contour_similarity", round(similarity, 3)))

    interpretation = f"Sampled bass movement is predominantly {contour_word}; net pitch change is {bass[-1] - bass[0]:+d} semitones."
    confidence = 1.0
    alternatives: list[str] = []
    if similarity is not None and similarity >= 0.75:
        interpretation = (
            f"Bass contour is {contour_word} and the second half closely "
            f"echoes the first (similarity {similarity:.2f}), reinforcing "
            f"repetition."
        )
        confidence = max(0.5, similarity)
        alternatives = [
            "Similarity may come from a deliberate ostinato rather than "
            "unintended repetition."
        ]
    return [
        Finding(
            observation=(
                f"Bass contour samples (per bar): {bass}; common movement {contour_word} "
                f"({rising} up, {falling} down, {static} static)."
            ),
            location=loc,
            evidence=evidence,
            interpretation=interpretation,
            confidence=confidence,
            alternatives=alternatives,
        )
    ]


def inspect(doc: ScoreDocument, region: Region | None = None) -> list[Finding]:
    """Run bounded, deterministic register, density, bass, rhythm and harmony analysis."""
    if len(region_bars(doc, _effective_region(doc, region))) > 256:
        raise ValueError("Select at most 256 bars for detailed musical analysis")
    return [
        *analyze_register(doc, region),
        *analyze_density(doc, region),
        *analyze_bass_contour(doc, region),
        *analyze_rhythm(doc, region),
        *analyze_harmony(doc, region),
    ]


def analyze_rhythm(doc: ScoreDocument, region: Region | None = None) -> list[Finding]:
    """Compare adjacent full bars by attack positions on a sixteenth-note grid.

    Simultaneous chord notes count as one attack. Durations, pitch and velocity
    are deliberately excluded, so repeating attacks never imply identical music.
    """
    eff = _effective_region(doc, region)
    notes = _notes_in(doc, region)
    bars = region_bars(doc, eff)
    findings: list[Finding] = []
    for before, after in zip(bars, bars[1:]):
        if not before.complete or not after.complete or before.beats_per_bar != after.beats_per_bar:
            continue
        left = {round((n.onset_beats - before.start) * 4) for n in notes
                if before.start <= n.onset_beats < before.end}
        right = {round((n.onset_beats - after.start) * 4) for n in notes
                 if after.start <= n.onset_beats < after.end}
        if not left or not right:
            continue
        similarity = len(left & right) / len(left | right)
        if similarity < 0.75:
            continue
        selected = [n for n in notes if before.start <= n.onset_beats < after.end]
        location = _location(Region(before.start, after.end, eff.track_ids), doc, selected)
        findings.append(Finding(
            observation=f"Bars {before.number} and {after.number} share {similarity:.0%} of attack positions on a sixteenth-note grid.",
            location=location,
            evidence=[Evidence("attack_pattern_similarity", round(similarity, 3)),
                      Evidence("grid_quarter_beats", 0.25),
                      Evidence("first_bar_attack_offsets", ", ".join(f"{x / 4:g}" for x in sorted(left))),
                      Evidence("second_bar_attack_offsets", ", ".join(f"{x / 4:g}" for x in sorted(right)))],
            interpretation="Repeated attack placement may contribute to rhythmic predictability. Try changing one attack while preserving pitches.",
            confidence=0.8,
            alternatives=["A recurring rhythmic pattern may provide intentional cohesion.",
                          "Durations, accents and microtiming can distinguish these bars despite matching attack positions."],
            category="rhythm", note_ids=tuple(n.id for n in selected),
        ))
    return findings


_PITCH_CLASSES = ("C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B")
_CHORD_SHAPES: tuple[tuple[str, tuple[int, ...]], ...] = (
    ("major", (0, 4, 7)), ("minor", (0, 3, 7)),
    ("diminished", (0, 3, 6)), ("augmented", (0, 4, 8)),
    ("7", (0, 4, 7, 10)), ("maj7", (0, 4, 7, 11)), ("m7", (0, 3, 7, 10)),
)


def analyze_harmony(doc: ScoreDocument, region: Region | None = None) -> list[Finding]:
    """Offer up to three complete chord templates per bar using duration coverage.

    This is pitch-class aggregation, not key, Roman-numeral or cadence analysis.
    Each template must contain only observed classes; missing chord tones are
    never invented. All durations are clipped to the selected bar.
    """
    eff = _effective_region(doc, region)
    notes = _notes_in(doc, region)
    findings: list[Finding] = []
    for bar in region_bars(doc, eff):
        selected = [n for n in notes if n.onset_beats < bar.end and n.offset_beats > bar.start]
        weights: dict[int, float] = {}
        for note in selected:
            duration = min(bar.end, note.offset_beats) - max(bar.start, note.onset_beats)
            weights[note.pitch % 12] = weights.get(note.pitch % 12, 0.0) + duration
        if len(weights) < 3:
            continue
        total = sum(weights.values())
        candidates: list[tuple[float, int, str]] = []
        for root in range(12):
            for name, intervals in _CHORD_SHAPES:
                classes = {(root + interval) % 12 for interval in intervals}
                if not classes <= weights.keys():
                    continue
                coverage = sum(weights[pc] for pc in classes) / total
                if coverage >= 0.7:
                    candidates.append((coverage, len(classes), f"{_PITCH_CLASSES[root]} {name}"))
        candidates.sort(key=lambda candidate: (-candidate[0], -candidate[1], candidate[2]))
        labels = [name for _, _, name in candidates[:3]]
        observed = ", ".join(_PITCH_CLASSES[pc] for pc in sorted(weights))
        loc = _location(Region(bar.start, bar.end, eff.track_ids), doc, selected)
        findings.append(Finding(
            observation=f"Bar {bar.number} contains pitch classes {observed} (key-held durations, pedal excluded).",
            location=loc,
            evidence=[Evidence("pitch_classes", observed),
                      Evidence("chord_candidates", "; ".join(labels) or "No complete template covers 70%"),
                      Evidence("best_duration_coverage", round(candidates[0][0], 3) if candidates else 0.0)],
            interpretation=(f"Possible chord collections: {' / '.join(labels)}. Check the bass and phrase context before assigning a harmonic function."
                            if labels else "This bar does not fit a single supported chord template; inspect shorter regions or separate voices."),
            confidence=min(0.85, candidates[0][0] * (0.85 if len(labels) == 1 else 0.7)) if candidates else 0.5,
            alternatives=["Several harmonies, passing tones or arpeggios may occur within one bar.",
                          "Pitch-class matching does not establish a key, spelling, inversion or resolution."],
            category="harmony", note_ids=tuple(n.id for n in selected),
        ))
    return findings
