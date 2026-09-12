import { useProjectApi } from "./ProjectApiContext";
// MIDI import: read a .mid file, base64-encode it, POST to /api/score/import.

import { useRef, useState } from "react";

import { ApiError } from "../api";
import { Button } from "./common";

function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result as string;
      const comma = dataUrl.indexOf(",");
      resolve(comma >= 0 ? dataUrl.slice(comma + 1) : dataUrl);
    };
    reader.onerror = () => reject(reader.error ?? new Error("read failed"));
    reader.readAsDataURL(file);
  });
}

export function ImportBar({
  onImported,
  onError,
}: {
  onImported: (versionId: string) => void;
  onError: (message: string) => void;
}) {
  const api = useProjectApi();
  const [busy, setBusy] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  async function handleFile(file: File) {
    setBusy(true);
    try {
      const midiB64 = await fileToBase64(file);
      const title = file.name.replace(/\.midi?$/i, "");
      const result = await api.importMidi(midiB64, { title });
      onImported(result.result.version.version_id);
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="import-bar">
      <input
        ref={inputRef}
        type="file"
        accept=".mid,.midi,audio/midi"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
          event.currentTarget.value = "";
        }}
      />
      <Button variant="primary" disabled={busy} onClick={() => inputRef.current?.click()}>
        {busy ? "导入中…" : "将 MIDI 加入本项目"}
      </Button>
    </div>
  );
}
