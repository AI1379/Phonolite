// MIDI import: read a .mid file, base64-encode it, POST to /api/score/import.

import { useState } from "react";

import { api, ApiError } from "../api";
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
  onImported: () => void;
  onError: (message: string) => void;
}) {
  const [busy, setBusy] = useState(false);

  async function handleFile(file: File) {
    setBusy(true);
    try {
      const midiB64 = await fileToBase64(file);
      const title = file.name.replace(/\.midi?$/i, "");
      await api.importMidi(midiB64, { title });
      onImported();
    } catch (err) {
      onError(err instanceof ApiError ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="import-bar">
      <input
        type="file"
        accept=".mid,.midi,audio/midi"
        disabled={busy}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void handleFile(file);
          event.currentTarget.value = "";
        }}
      />
      <Button variant="primary" disabled={busy}>
        {busy ? "导入中…" : "选择 MIDI 导入"}
      </Button>
    </label>
  );
}
