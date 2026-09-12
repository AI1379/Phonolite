// Thin fetch wrapper for the Domain API. Every call returns the parsed
// section-8.4 envelope, or throws ApiError when the request fails (the
// backend also returns an envelope on 4xx/5xx, with result.error set).

import type {
  AgentMode,
  AgentTask,
  Decision,
  Envelope,
  ExportResult,
  HealthResult,
  InspectResult,
  ProjectConfig,
  ProjectStatus,
  RenderResult,
  ScoreDiff,
  ScorePage,
  TransformRequestBody,
  TransformResult,
  VersionSummary,
  ReferenceMedia,
  AlignmentAnchor,
  NoteInput,
  ValidationReport,
  ProjectCatalog,
} from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

/** Reduce any thrown value to a user-readable string (ApiError keeps message). */
export function errMsg(e: unknown): string {
  if (e instanceof ApiError) return e.message;
  if (e instanceof Error) return e.message;
  return String(e);
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function asError(result: unknown): string | null {
  return isObject(result) && typeof result.error === "string" ? result.error : null;
}

async function call<T>(
  method: string,
  path: string,
  body?: unknown,
  projectId?: string,
): Promise<Envelope<T>> {
  const resp = await fetch(path, {
    method,
    headers: { ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(projectId ? { "X-Workbench-Project": projectId } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  const text = await resp.text();
  let payload: Envelope<T> | null = null;
  if (text) {
    try {
      payload = JSON.parse(text) as Envelope<T>;
    } catch {
      payload = null;
    }
  }
  const failed = !resp.ok || (payload !== null && payload.ok === false);
  if (failed) {
    const error =
      asError(payload !== null ? payload.result : undefined) ?? `HTTP ${resp.status}`;
    throw new ApiError(error, resp.status);
  }
  if (payload === null) {
    throw new ApiError(`HTTP ${resp.status}: empty response body`, resp.status);
  }
  return payload;
}

function withQuery(
  base: string,
  params: Record<string, string | number | undefined>,
): string {
  const entries = Object.entries(params).filter(
    ([, value]) => value !== undefined && value !== "",
  );
  if (entries.length === 0) return base;
  const query = entries
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`)
    .join("&");
  return `${base}?${query}`;
}

export interface InspectQuery {
  start_beat?: number;
  end_beat?: number;
  track_ids?: string;
  [key: string]: string | number | undefined;
}

export function createApi(projectId?: string) {
  const request = <T>(method: string, path: string, body?: unknown) => call<T>(method, path, body, projectId);
  return {
  catalog: () => request<ProjectCatalog>("GET", "/api/projects"),
  createProject: (title: string, workflow: "composition" | "transcription") => request<{project: ProjectConfig}>("POST", "/api/projects", {title,workflow}),
  openProject: (id: string) => request<{project: ProjectConfig}>("POST", `/api/projects/${encodeURIComponent(id)}/open`),
  renameProject: (id: string, title: string) => request<{project: ProjectConfig}>("PATCH", `/api/projects/${encodeURIComponent(id)}`, {title}),

  health: () => request<HealthResult>("GET", "/api/health"),
  project: () => request<ProjectStatus>("GET", "/api/project"),
  references: () => request<{ references: ReferenceMedia[] }>("GET", "/api/references"),
  importAudio: (audio_b64: string, filename: string) =>
    request<{ reference: ReferenceMedia }>("POST", "/api/references/import", { audio_b64, filename }),
  importVideo: (video_b64: string, filename: string) =>
    request<{ reference: ReferenceMedia }>("POST", "/api/references/import-video", { video_b64, filename }),
  saveAlignment: (id: string, anchors: AlignmentAnchor[]) =>
    request<{ reference: ReferenceMedia }>("PUT", `/api/references/${id}/alignment`, { anchors }),
  createDraft: (body: { title: string; reference_id?: string; length_beats?: number; bpm?: number; numerator?: number; denominator?: number }) =>
    request<{ version: VersionSummary }>("POST", "/api/score/draft", body),
  attachReference: (id: string, reference_id: string) =>
    request<{ version: VersionSummary }>("POST", `/api/score/${id}/reference`, { reference_id }),
  editNote: (body: { source_version_id: string; action: "add" | "update" | "remove"; note_id?: string; note?: NoteInput }) =>
    request<{ version: VersionSummary; validation: ValidationReport }>("POST", "/api/score/edit", body),

  createAgentTask: (prompt: string, mode: AgentMode, session_id?: string) =>
    request<{ task: AgentTask }>("POST", "/api/agent/tasks", {
      prompt,
      mode,
      session_id,
    }),

  agentTask: (task_id: string) =>
    request<{ task: AgentTask }>("GET", `/api/agent/tasks/${task_id}`),
  latestAgentTask: () => request<{ task: AgentTask | null }>("GET", "/api/agent/tasks"),

  cancelAgentTask: (task_id: string) =>
    request<{ task: AgentTask }>("POST", `/api/agent/tasks/${task_id}/cancel`),

  resumeAgentSession: (session_id: string, prompt: string, mode: AgentMode) =>
    request<{ task: AgentTask }>(
      "POST",
      `/api/agent/sessions/${encodeURIComponent(session_id)}/resume`,
      { prompt, mode },
    ),

  importMidi: (
    midi_b64: string,
    opts?: { project_id?: string; title?: string },
  ) => request<{ version: VersionSummary }>("POST", "/api/score/import", {
    midi_b64,
    ...opts,
  }),

  inspect: (id: string, region?: InspectQuery) =>
    request<InspectResult>(
      "GET",
      withQuery(`/api/score/${id}/inspect`, region ?? {}),
    ),

  score: (id: string, region?: InspectQuery, offset = 0, limit = 64) =>
    request<ScorePage>("GET", withQuery(`/api/score/${id}`, { ...region, offset, limit })),

  compare: (before_version_id: string, after_version_id: string) =>
    request<ScoreDiff>("POST", "/api/score/compare", {
      before_version_id,
      after_version_id,
    }),

  transform: (req: TransformRequestBody) =>
    request<TransformResult>("POST", "/api/score/transform", req),

  render: (id: string, backend: string) =>
    request<RenderResult>("POST", withQuery(`/api/score/${id}/render`, { backend })),

  exportMidi: (id: string) =>
    request<ExportResult>("POST", `/api/score/${id}/export`),

  updateGoal: (req: {
    description: string;
    bars?: [number, number];
    beats?: [number, number];
  }) => request<{ project: ProjectConfig }>("PATCH", "/api/project/goal", req),

  accept: (version_id: string) =>
    request<{ project: ProjectConfig; active_version: string }>(
      "POST",
      "/api/project/accept",
      { version_id },
    ),

  choose: (req: {
    chosen_version_id: string;
    reason?: string;
    tags?: string[];
  }) =>
    request<{ decision: Decision; project: ProjectConfig }>(
      "POST",
      "/api/project/choose",
      req,
    ),

  artifactUrl: (token: string) => withQuery(`/api/artifact/${token}`, { project_id: projectId }),

  agentSocketUrl: (task_id: string) => {
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    return withQuery(`${protocol}//${window.location.host}/ws`, { task_id, project_id: projectId });
  },
  };
}

export type ProjectApi = ReturnType<typeof createApi>;
export const api = createApi();
