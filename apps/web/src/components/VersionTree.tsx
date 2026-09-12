// The version tree: every stored version with its origin, branch, and a
// short id. Clicking selects it so the detail / inspect / compare / transform
// panels operate on it.

import type { VersionSummary } from "../types";

export function VersionTree({
  versions,
  activeId,
  selectedId,
  onSelect,
}: {
  versions: VersionSummary[];
  activeId: string | null;
  selectedId: string | null;
  onSelect: (versionId: string) => void;
}) {
  if (versions.length === 0) {
    return <p className="muted empty">本项目尚无版本。新建草稿或导入 MIDI 后，修改历史会显示在这里。</p>;
  }
  return (
    <ul className="version-tree">
      {versions.map((version) => {
        const isActive = version.version_id === activeId;
        const isSelected = version.version_id === selectedId;
        return (
          <li key={version.version_id}>
            <button
              type="button"
              className={`version-row${isSelected ? " selected" : ""}`}
              onClick={() => onSelect(version.version_id)}
            >
              <span className="version-branch">{version.branch}</span>
              <span className="version-id" title={version.version_id}>
                {version.version_id.slice(0, 12)}
              </span>
              <span className="row-tags">
                <span className={`tag origin ${version.origin}`}>
                  {({import:"导入",transform:"变换",draft:"草稿",edit:"校正"} as Record<string,string>)[version.origin] ?? version.origin}
                </span>
                {isActive ? <span className="tag active">主版本</span> : null}
              </span>
              <span className="version-meta muted">
                {version.note_count} notes · {version.duration_beats.toFixed(1)} beats
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
