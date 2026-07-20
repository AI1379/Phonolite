# Phonolite

Real-time microphone spectrum analysis and pitch exploration — a tuner-like
tool for *natural* sounds (voice, bird calls, resonant bodies like bells and
bowls, ambient/drone sounds, percussion).

> **Name.** Phonolite (响岩) is a real volcanic rock that rings like a bell
> when struck — *phonos* (sound) + *lithos* (stone). The chemical/mineral
> name fits the team's naming style and the tool's focus on resonant,
> sometimes inharmonic, sound sources.

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
- [ ] Overlapping STFT (currently one block == one window)
- [ ] Real pitch detection: YIN, Harmonic Product Spectrum
- [ ] Spectral features on the UI: centroid, flatness, inharmonicity
- [ ] Multi-algorithm pitch confidence indicator

### Roadmap

- **Phase 3** — harmonic-series template fit ("find the fundamental that
  best explains these peaks"), neural pitch detection (CREPE), sound-type
  classifier, recording + A/B comparison.
- **Phase 4** — pitch trend / statistics, optional C++ audio core via
  nanobind for the low-level infra enthusiasts.

## Quick start

```powershell
uv sync                 # create venv and install deps
uv run phonolite        # launch the app
# or: uv run python -m phonolite
```

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

```
src/phonolite/
├── audio/
│   ├── input_stream.py     microphone capture (QSignal + sounddevice)
│   ├── file_player.py      file playback (QSignal + soundfile + sounddevice)
│   └── ring_buffer.py      (placeholder for Phase 2 overlap)
├── dsp/
│   ├── stft.py             Hann-windowed magnitude spectrum
│   ├── peaks.py            peak find + parabolic refinement
│   ├── pitch/
│   │   ├── peak_fundamental.py   MVP heuristic
│   │   ├── yin.py                (Phase 2)
│   │   └── hps.py                (Phase 2)
│   ├── harmonic_fit.py     (Phase 3)
│   └── features.py         spectral centroid / flatness (Phase 2)
├── music/
│   └── naming.py           freq ↔ note / cents / interval
└── ui/
    ├── main_window.py            source switching + transport
    └── widgets/
        ├── spectrum_plot.py      live + max-hold + peak markers
        └── spectrogram_view.py   rolling waterfall
```

## Dependencies

| Package       | Why                                              |
|---------------|--------------------------------------------------|
| PySide6       | Qt GUI                                           |
| numpy         | FFT, vector math                                 |
| scipy         | `signal.windows`, `signal.find_peaks`            |
| sounddevice   | cross-platform microphone input (PortAudio)      |
| pyqtgraph     | fast real-time plotting                          |
