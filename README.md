# Phonolite

Real-time microphone spectrum analysis and pitch exploration — a tuner-like
tool for *natural* sounds (voice, bird calls, resonant bodies like bells and
bowls, ambient/drone sounds, percussion).

> **Name.** Phonolite (响岩) is a real volcanic rock that rings like a bell
> when struck — *phonos* (sound) + *lithos* (stone). The chemical/mineral
> name fits the team's naming style and the tool's focus on resonant,
> sometimes inharmonic, sound sources.

> **This repo hosts two projects.** Besides the Phonolite desktop app
> documented below, it is also home to the **Music Agent Workbench** — a
> composition-learning agent system under construction (`packages/music-core`,
> `apps/server`, `apps/web`). See `music_agent_workbench_design.md` (Chinese)
> for the architecture and `AGENTS.md` for the repo workflow. Phonolite's
> algorithmic core lives in `packages/audio-core` and doubles as the
> Workbench's future audio-analysis (MIR) backend.

> **Maintenance status.** The Qt desktop app is frozen and receives only
> critical fixes. All new product work uses the browser-based Workbench
> (`apps/web` + `apps/server`); reusable audio algorithms remain active in
> `packages/audio-core`.

The Workbench has completed its offline music core, browser/server vertical
slice, MVP-2 event-sourced memory layer, and its OpenCode-first Agent Runtime.
`packages/agent-runtime` streams OpenCode CLI events and preserves sessions;
`packages/music-mcp` exposes the existing Domain API as local stdio MCP tools.
Analyze, Learn, and Experiment are available in the web UI with separate
permissions. `packages/memory-core` keeps
immutable raw events in SQLite and rebuildable Observation, Claim, Project
State, Learning State, and channel-aware Recall projections. The next
Workbench priority is musical analysis and the FastAPI + Web workflow; DAW bridges
are deferred while the Qt application remains frozen.

The product has two primary workflows: original composition/learning, and
transcribing reference recordings into playable piano arrangements. R1 now
supports source-audio listening, manual correction of score drafts and project
recovery. Candidate transcription models, source separation and piano reduction
remain future work. Original audio, transcription uncertainty and deliberate
arrangement decisions remain separate (design document section 24).

Use **导入原曲音频** for WAV/FLAC/OGG/MP3, select a loop and adjust playback speed
without changing pitch. Mark at least two audio-seconds/score-beats anchors,
save them, then select **新建扒谱草稿**. The note form below the piano roll adds,
corrects and removes notes in new versions, with melody/bass/inner roles and
uncertain/confirmed status. Reference audio and the score region can locate
each other using the draft's saved alignment.

All project scores, versions, references, original bytes and generated artifacts
are now stored in SQLite (`project.db`, or `WORKBENCH_DB_PATH`). Restarting the
server restores the latest working draft; accepting a formal version remains
explicit. Projects are independent local workspaces. MIDI export does not carry
native alignment or confirmation metadata; those remain in the project database.

Use **＋ 新建项目** at the top for another piece or arrangement, then choose a
name and workflow. **当前项目** opens an existing project; **重命名项目** changes
its name. The left-hand **本项目版本** list contains only that project's revision
history. Importing a MIDI/audio/video file adds material to the selected project
and never renames it. Old single-project databases migrate automatically, retaining
all versions, assets and IDs. Project deletion and copying are not implemented.

Each project's goal, reference media, alignment, draft, decisions and formal main
version are separate. The latest open project and working draft survive restart.
In-flight uploads and renders retain their original project even after a UI switch.
API clients may bind a project with `X-Workbench-Project`; media and WebSocket URLs
use `project_id`. Workbench Agent tasks bind MCP via `WORKBENCH_PROJECT_ID` and
reject cross-project sessions. Project-bound tasks require a dedicated OpenCode
CLI process; `WORKBENCH_OPENCODE_ATTACH` must be unset for those tasks.

For a reproducible audio example, run `uv run python examples/reference_audio_demo.py`.
The generated WAV has a one-second lead-in: audio 1–7 seconds corresponds to
score beats 0–8. It is synthetic acceptance material, not automatic transcription.

**Video references:** use **导入参考视频** for a local MP4/MOV/MKV/WebM clip.
The original is retained while FFmpeg creates a browser-playable MP4 and an
aligned waveform. Video import requires `ffmpeg` and `ffprobe` on PATH (or
`WORKBENCH_FFMPEG` / `WORKBENCH_FFPROBE`), up to 256 MB and ten minutes. Audio-only
workflows do not need FFmpeg. The preview is capped at 1920×1080; keep the original
for full-resolution inspection.

Pause, loop, slow down, or step by 0.05 seconds to inspect keys and visual effects.
**在谱稿中定位当前画面** maps the current video time through the draft's anchors;
**悬浮对照** keeps the video visible while editing below. The score playhead can
follow reference playback. These are manual visual aids, not automatic visual
MIDI transcription or website video downloading. Run
`uv run python examples/reference_video_demo.py` for a synthetic example.

The music workflow now includes meter-aware region analysis, adjacent-bar rhythm
comparison, per-bar chord candidates, actual note inspection, and single-note
attack experiments. MIDI sustain/controllers, programs, pitch bend and pressure
survive import/export. Built-in reference-tone WAV preview supports tempo,
velocity and sustain without an external synthesizer. A/B comparison uses the
same timbre and fixed gain, supports seeking/switching, and records an explicit
choice of either version.

Run `uv run python examples/music_lab_demo.py`, import `examples/music_lab_demo.mid`
in the web UI, click **分析选区**, inspect a chord candidate's notes, and use
**移动起音** on one melody note. Applying the transform automatically prepares
the two A/B audio files. No model provider is needed for these deterministic
tools; OpenCode is needed only for the Agent panel.

The current MIDI is visible in a piano roll at the top of the page. Track colors,
pitch rows, note lengths and a meter-aware ruler show the material directly.
Drag on the ruler or empty grid to select a region, click a note for its details,
or use **在卷帘中定位** on an analysis finding. **准备当前版本试听** enables a
tempo-aware playhead and **试听选区**. The numeric note table is collapsed below
the roll. This view selects material for controlled experiments; staff notation
and direct note dragging/editing are not implemented.

Run `pnpm test` in `apps/web` (Node 22.6+) for ruler and playback-coordinate tests,
in addition to `pnpm build` and the workspace Python checks.

Preview is a reference timbre, not sampled piano, and ignores expression other
than velocity/CC64 (MIDI export retains it). Analysis uses key-held durations,
and chord templates do not establish key or harmonic function. Set
`WORKBENCH_SOUNDFONT` to use FluidSynth in `auto` rendering; unavailable or failing
external renderers fall back to playable WAV. Project scores, versions, artifacts
and the independent memory ledger persist in the local project database.

## Status

### Phase 1 (MVP) — done

- [x] Microphone capture via `sounddevice` with a Qt-signal bridge across threads
- [x] Real-time magnitude spectrum (log-frequency, pyqtgraph)
- [x] Spectral peak detection with parabolic sub-bin frequency refinement
- [x] Frequency → note name + cents readout (12-TET, configurable A4)
- [x] Top-N peak list with per-peak note labels

### Phase 2 — in progress

- [x] **Rolling spectrogram (waterfall)** — log-frequency × time, dB as colour.
  Adds the second dimension that lets the eye tell signal (horizontal stripes)
  from noise (scattered specks).
- [x] **Decaying max-hold trace** on the spectrum — peaks are tracked with a
  slow decay (default 6 dB/s). Peak detection now runs against the max-hold
  buffer, so transient noise spikes no longer produce spurious notes.
- [x] **Reset button** to clear max-hold + waterfall history without
  restarting the audio stream.
- [x] **Audio file playback** — open any libsndfile-supported format (WAV,
  FLAC, OGG, MP3, Opus, AIFF, …) via `Open File…`. The file plays through
  the speakers while the same live pipeline (spectrum + waterfall + peaks)
  visualises it. Transport bar with Play/Pause, Stop, seekable slider, and
  time display. Mic and file sources are mutually exclusive; switching
  sources rebuilds the STFT at the new sample rate.
- [x] **Chroma / pitch-class display** — 12-bar histogram collapses the
  spectrum to "which notes are sounding", regardless of octave. Reads
  from the same max-hold buffer as the peak detector, so transient noise
  doesn't pollute it. Top-3 pitch classes are highlighted in orange and
  also summarised in the text panel. Designed for dense polyphony
  (orchestral, chords) where per-peak readouts become unreadable.
- [x] **Piano-roll waterfall (MIDI-resolution)** — semitone-spaced
  watermark with note names on the y-axis (C2 … C6). Preserves octave
  information for transcription. Per-frame normalised.
- [x] **Active-notes text readout** — top-N strongest MIDI notes (with
  octave) printed in the peak panel.
- [x] **2x2 panel grid + maximise** — panels are arranged in a resizable
  grid (Spectrum | Spectrogram over Piano Roll | Chroma). Each panel has
  a ``Max`` / ``Restore`` button that expands it to fill the full grid
  area, hiding the other three — ideal for focusing on one view while
  transcribing.
- [x] **Click-to-seek on piano-roll** — click any column of the waterfall
  to seek the audio file to that point (and auto-play if paused). Lets
  you scrub back to a point of interest without touching the slider.
- [ ] Overlapping STFT (currently one block == one window)
- [ ] Real pitch detection: YIN, Harmonic Product Spectrum
- [ ] Multi-F0 estimation (Klapuri iterative harmonic subtraction)
- [ ] Spectral features on the UI: centroid, flatness, inharmonicity
- [ ] Chord recognition on top of chroma
- [ ] Multi-algorithm pitch confidence indicator

### Roadmap

- **Phase 3** — harmonic-series template fit ("find the fundamental that
  best explains these peaks"), neural pitch detection (CREPE), sound-type
  classifier, recording + A/B comparison.
- **Phase 4** — pitch trend / statistics, optional C++ audio core via
  nanobind for the low-level infra enthusiasts.

## Quick start

```powershell
uv sync --all-packages  # create venv and install all workspace members
uv run phonolite        # launch the app
# or: uv run python -m phonolite
```

To run the Music Agent Workbench, install OpenCode, configure a model provider,
then start the backend and frontend in separate terminals:

```powershell
opencode mcp list       # project music MCP should report connected
uv run workbench-server

cd apps/web
pnpm install
pnpm dev
```

Open the Vite URL and use the **OpenCode Agent** panel. Analyze is read-only;
Experiment may create, render, and compare branches but cannot accept one;
Learn records outcomes only when the user provides explicit evidence.

Click **Start**, allow microphone access if prompted, and the spectrum plus
the dominant peak's note should update in real time.

## Architecture

```
                    ┌─────────────────────┐
                    │   AudioSource       │
                    │   (frame_ready)     │
                    └──────────┬──────────┘
            ┌──────────────────┴──────────────────┐
            ▼                                     ▼
   AudioInputStream (mic, 44.1k)       AudioFilePlayer (file, native rate)
            │                                     │
            └──────────────────┬──────────────────┘
                               ▼ (auto-queued, GUI thread)
                      MainWindow._on_frame
                               │
                               ├─ STFT.analyze (rebuilt when sample rate changes)
                               │
                               ├─ SpectrumPlot.update_spectrum
                               │     └─▶ (decaying max-hold buffer)
                               │
                               ├─ SpectrogramView.add_spectrum  (rolling waterfall)
                               │
                               └─ detect_peaks on max-hold ─▶ describe_frequency
```

Mic and file sources are mutually exclusive. Opening a file stops the mic,
rebuilds the STFT at the file's native sample rate, and resets max-hold +
waterfall; closing the file reverts to the mic sample rate.

Phase 2 (next): replace the simple "one block == one window" hop with a
`RingBuffer`-driven overlapping STFT, and swap the peak-based fundamental
heuristic for YIN / HPS.

## Project layout

The repo is a uv workspace: `packages/` holds host-independent libraries,
`apps/` holds applications (see `AGENTS.md` for the full picture).

```
packages/audio-core/            pure numpy/scipy — no Qt, no audio I/O
└── src/audio_core/
    ├── dsp/
    │   ├── stft.py             Hann-windowed magnitude spectrum
    │   ├── peaks.py            peak find + parabolic refinement
    │   ├── chroma.py           12-bin pitch-class projection (octave-folded)
    │   ├── pitch_grid.py       MIDI-resolution projection (octave-preserving)
    │   ├── ring_buffer.py      (placeholder for Phase 2 overlap)
    │   ├── pitch/
    │   │   ├── peak_fundamental.py   MVP heuristic
    │   │   ├── yin.py                (Phase 2)
    │   │   └── hps.py                (Phase 2)
    │   ├── harmonic_fit.py     (Phase 3)
    │   └── features.py         spectral centroid / flatness (Phase 2)
    └── music/
        └── naming.py           freq ↔ note / cents / interval

apps/phonolite/                 PySide6 desktop app (uv run phonolite)
└── src/phonolite/
    ├── audio/
    │   ├── input_stream.py     microphone capture (QSignal + sounddevice)
    │   └── file_player.py      file playback (QSignal + soundfile + sounddevice)
    └── ui/
        ├── main_window.py            source switching + transport
        └── widgets/
            ├── spectrum_plot.py      live + max-hold + peak markers
            ├── spectrogram_view.py   Hz waterfall (diagnostic)
            ├── piano_roll_view.py    MIDI waterfall (transcription)
            └── chroma_view.py        12-bar pitch-class histogram
```

## Dependencies

| Package       | Why                                              |
|---------------|--------------------------------------------------|
| PySide6       | Qt GUI                                           |
| numpy         | FFT, vector math                                 |
| scipy         | `signal.windows`, `signal.find_peaks`            |
| sounddevice   | cross-platform microphone input (PortAudio)      |
| pyqtgraph     | fast real-time plotting                          |
