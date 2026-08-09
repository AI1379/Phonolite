// Thin fetch wrapper for the Domain API. Every call returns the parsed
// section-8.4 envelope, or throws ApiError when the request fails (the
// backend also returns an envelope on 4xx/5xx, with result.error set).

import type {
  Decision,
  Envelope,
  ExportResult,
  HealthResult,
  InspectResult,
  ProjectConfig,
  ProjectStatus,
  RenderResult,
  ScoreDiff,
  TransformRequestBody,
  TransformResult,
  VersionSummary,
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
): Promise<Envelope<T>> {
  const resp = await fetch(path, {
    method,
    headers: body !== undefined ? { "Content-Type": "application/json" } : undefined,
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

export const api = {
  health: () => call<HealthResult>("GET", "/api/health"),
  project: () => call<ProjectStatus>("GET", "/api/project"),

  importMidi: (
    midi_b64: string,
    opts?: { project_id?: string; title?: string },
  ) => call<{ version: VersionSummary }>("POST", "/api/score/import", {
    midi_b64,
    ...opts,
  }),

  inspect: (id: string, region?: InspectQuery) =>
    call<InspectResult>(
      "GET",
      withQuery(`/api/score/${id}/inspect`, region ?? {}),
    ),

  compare: (before_version_id: string, after_version_id: string) =>
    call<ScoreDiff>("POST", "/api/score/compare", {
      before_version_id,
      after_version_id,
    }),

  transform: (req: TransformRequestBody) =>
    call<TransformResult>("POST", "/api/score/transform", req),

  render: (id: string, backend: string) =>
    call<RenderResult>("POST", withQuery(`/api/score/${id}/render`, { backend })),

  exportMidi: (id: string) =>
    call<ExportResult>("POST", `/api/score/${id}/export`),

  updateGoal: (req: {
    description: string;
    bars?: [number, number];
    beats?: [number, number];
  }) => call<{ project: ProjectConfig }>("PATCH", "/api/project/goal", req),

  accept: (version_id: string) =>
    call<{ project: ProjectConfig; active_version: string }>(
      "POST",
      "/api/project/accept",
      { version_id },
    ),

  choose: (req: {
    chosen_version_id: string;
    reason?: string;
    tags?: string[];
  }) =>
    call<{ decision: Decision; project: ProjectConfig }>(
      "POST",
      "/api/project/choose",
      req,
    ),

  artifactUrl: (token: string) => `/api/artifact/${token}`,
};
