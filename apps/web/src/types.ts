// Types mirroring the Workbench Domain API envelopes (design doc 8.4).
// The backend serialises music-core dataclasses via serialization.py; these
// interfaces describe the JSON shapes the UI consumes.

export interface Envelope<T> {
  ok: boolean;
  result: T;
  warnings: string[];
  artifacts: string[];
  provenance: { tool: string; version: string; inputs: string[] };
}

export interface HealthResult {
  service: string;
  version: string;
  music_core_version: string;
}

export interface Meter {
  beat: number;
  numerator: number;
  denominator: number;
}

export interface Tempo {
  beat: number;
  bpm: number;
}

export interface VersionSummary {
  version_id: string;
  ppq: number;
  duration_beats: number;
  note_count: number;
  track_ids: string[];
  meters: Meter[];
  tempos: Tempo[];
  branch?: string;
  parent_version?: string;
  parent_id?: string | null;
  origin: string;
  created_at: string;
  description: string;
  import_warnings?: string[];
}

export interface RegionBrief {
  start_beat: number;
  end_beat: number;
  scope: string;
  track_ids?: string[];
}

export interface Location {
  start_beat: number;
  end_beat: number;
  track_ids: string[];
  bars?: [number, number];
  bars_label: string;
}

export interface Evidence {
  metric: string;
  value: string | number;
}

export interface Finding {
  observation: string;
  location: Location;
  evidence: Evidence[];
  interpretation: string;
  confidence: number;
  alternatives: string[];
}

export interface InspectResult {
  version_id: string;
  region: RegionBrief;
  findings: Finding[];
}

export interface Note {
  id: string;
  track_id: string;
  pitch: number;
  onset_beats: number;
  duration_beats: number;
  offset_beats: number;
  velocity: number;
  voice_id?: string;
  channel?: number;
}

export type FieldValue = string | number | null;

export interface NoteChange {
  note_id: string;
  kind: string;
  before: Note | null;
  after: Note | null;
  field_changes: Record<string, [FieldValue, FieldValue]>;
}

export interface ScoreDiff {
  is_empty: boolean;
  summary: string;
  added: NoteChange[];
  removed: NoteChange[];
  modified: NoteChange[];
  unchanged_count: number;
}

export interface ValidationReport {
  ok: boolean;
  errors: string[];
  warnings: string[];
}

export interface TransformResult {
  version: VersionSummary;
  branch: string;
  operation: string;
  description: string;
  changed_event_ids: string[];
  validation: ValidationReport;
}

export interface RenderResult {
  backend: string;
  warnings: string[];
  artifact_token: string;
  filename: string;
  size_bytes: number;
}

export interface ExportResult {
  filename: string;
  size_bytes: number;
  artifact_token: string;
}

export interface GoalRegion {
  bars?: [number, number];
  beats?: [number, number];
}

export interface ProjectGoal {
  description: string;
  region?: GoalRegion;
}

export interface MusicalContext {
  meter?: string;
  tempo_bpm?: number;
  tonal_center?: string;
}

export interface Decision {
  id: string;
  at: string;
  summary: string;
  chosen_version_id?: string;
  reason?: string;
  tags?: string[];
}

export interface ProjectConfig {
  id: string;
  title: string;
  active_version?: string;
  current_goal?: ProjectGoal;
  musical_context?: MusicalContext;
  preserve?: string[];
  avoid?: string[];
  learning_focus?: string[];
  decisions?: Decision[];
  [key: string]: unknown;
}

export interface ProjectStatus {
  project: ProjectConfig;
  active_version: string | null;
  versions: VersionSummary[];
}

export interface TransformRequestBody {
  source_version_id: string;
  region: { start_beat: number; end_beat: number; track_ids?: string[] };
  operation: string;
  parameters: Record<string, string | number | boolean>;
  output_branch?: string;
  preserve?: string[];
  vary?: string[];
}
