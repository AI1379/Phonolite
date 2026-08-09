import { useCallback, useEffect, useState } from "react";

import { api, errMsg } from "./api";
import type { HealthResult, ProjectStatus } from "./types";
import { DiffView } from "./components/DiffView";
import { ImportBar } from "./components/ImportBar";
import { ProjectPanel } from "./components/ProjectPanel";
import { TransformForm } from "./components/TransformForm";
import { VersionDetail } from "./components/VersionDetail";
import { VersionTree } from "./components/VersionTree";
import { Empty, ErrorBanner, Section } from "./components/common";

function App() {
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [project, setProject] = useState<ProjectStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);
  const [showTransform, setShowTransform] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProject((await api.project()).result);
    } catch (e) {
      setError(errMsg(e));
    }
  }, []);

  const onError = useCallback((message: string) => setError(message), []);

  useEffect(() => {
    void refresh();
    api
      .health()
      .then((env) => setHealth(env.result))
      .catch((e) => setError(errMsg(e)));
  }, [refresh]);

  // Keep the selection valid as the version list changes.
  useEffect(() => {
    if (!project) return;
    const ids = project.versions.map((v) => v.version_id);
    if (!selectedId || !ids.includes(selectedId)) {
      setSelectedId(project.active_version ?? ids[0] ?? null);
    }
  }, [project, selectedId]);

  const versions = project?.versions ?? [];
  const selected = versions.find((v) => v.version_id === selectedId) ?? null;

  return (
    <main className="app">
      <header className="app-header">
        <div>
          <h1>Music Agent Workbench</h1>
          <p className="subtitle">Composition IDE · 切片检查与受控实验</p>
        </div>
        <div className="health">
          {health ? (
            <span className="muted">
              {health.service} v{health.version} · music-core {health.music_core_version}
            </span>
          ) : (
            <span className="muted">连接服务中…</span>
          )}
        </div>
      </header>

      {error ? (
        <ErrorBanner
          message={error}
        />
      ) : null}

      <div className="layout">
        <aside className="sidebar">
          <Section title="导入">
            <ImportBar onImported={refresh} onError={onError} />
          </Section>
          <Section title={`版本（${versions.length}）`}>
            <VersionTree
              versions={versions}
              activeId={project?.active_version ?? null}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />
          </Section>
        </aside>

        <section className="content">
          {project ? (
            <ProjectPanel
              project={project.project}
              onError={onError}
              onChanged={refresh}
            />
          ) : null}

          {selected ? (
            <VersionDetail
              key={selected.version_id}
              version={selected}
              isActive={selected.version_id === (project?.active_version ?? "")}
              onError={onError}
              onChanged={refresh}
              onTransform={() => setShowTransform(true)}
              onCompare={() => setCompareA(selected.version_id)}
            />
          ) : (
            <Empty>选择左侧版本查看详情,或先导入一段 MIDI。</Empty>
          )}

          {showTransform && selected ? (
            <TransformForm
              key={selected.version_id}
              source={selected}
              onError={onError}
              onCancel={() => setShowTransform(false)}
              onDone={(newId) => {
                setShowTransform(false);
                void refresh().then(() => setSelectedId(newId));
              }}
            />
          ) : null}

          <DiffView
            versions={versions}
            aId={compareA}
            bId={compareB}
            setAId={setCompareA}
            setBId={setCompareB}
            onError={onError}
            onChanged={refresh}
          />
        </section>
      </div>
    </main>
  );
}

export default App;
