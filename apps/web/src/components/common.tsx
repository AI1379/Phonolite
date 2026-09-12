// Small shared presentational widgets used across the Workbench UI.

import type { ReactNode } from "react";

import { useProjectApi } from "./ProjectApiContext";
import { pauseOtherMedia } from "./mediaPlayback";

export function Section({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: ReactNode;
  children?: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel-head">
        <h2>{title}</h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </div>
      {children}
    </section>
  );
}

type ButtonVariant = "primary" | "ghost" | "danger";

export function Button({
  onClick,
  children,
  disabled,
  variant,
  title,
}: {
  onClick?: () => void;
  children: ReactNode;
  disabled?: boolean;
  variant?: ButtonVariant;
  title?: string;
}) {
  return (
    <button
      type="button"
      className={`btn ${variant ?? ""}`}
      onClick={onClick}
      disabled={disabled}
      title={title}
    >
      {children}
    </button>
  );
}

export function Tag({
  children,
  tone,
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`tag ${tone ?? ""}`}>{children}</span>;
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(Math.max(0, Math.min(1, value)) * 100);
  return (
    <span className="confidence" title={`confidence ${pct}%`}>
      <span className="confidence-bar" style={{ width: `${pct}%` }} />
      <span className="confidence-label">{pct}%</span>
    </span>
  );
}

export function ArtifactLink({
  token,
  filename,
  contentType,
  sizeBytes,
}: {
  token: string;
  filename: string;
  contentType: string;
  sizeBytes?: number;
}) {
  const api = useProjectApi();
  const url = api.artifactUrl(token);
  const kb = sizeBytes !== undefined ? `${(sizeBytes / 1024).toFixed(1)} KB` : null;
  const playable = contentType === "audio/wav";
  return (
    <span className="artifact">
      <a href={url} download={filename}>
        {filename}
      </a>
      {kb ? <span className="muted">{kb}</span> : null}
      {playable ? <audio controls src={url} onPlay={(event) => pauseOtherMedia(event.currentTarget)} /> : null}
    </span>
  );
}

export function ErrorBanner({ message }: { message: string }) {
  return <div className="error-banner">{message}</div>;
}

export function Empty({ children }: { children: ReactNode }) {
  return <p className="muted empty">{children}</p>;
}
