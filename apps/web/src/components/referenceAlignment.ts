// UI coordinate conversion only; server validates and snapshots authoritative anchors.
import type { AlignmentAnchor } from "../types";

export function alignedValue(anchors: AlignmentAnchor[], value: number, from: "beat" | "seconds"): number | null {
  const to = from === "beat" ? "seconds" : "beat";
  for (let i = 0; i + 1 < anchors.length; i++) {
    const a = anchors[i], b = anchors[i + 1];
    if (a[from] <= value && value <= b[from] && b[from] > a[from]) {
      return a[to] + (value - a[from]) * (b[to] - a[to]) / (b[from] - a[from]);
    }
  }
  return null;
}
