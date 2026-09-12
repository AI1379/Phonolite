import { useCallback, useEffect, useMemo, useState } from "react";

import { api as workspaceApi, createApi, errMsg } from "./api";
import type { HealthResult, ProjectCatalog, ProjectStatus, ScoreRegion } from "./types";
import { AgentPanel } from "./components/AgentPanel";
import { DiffView } from "./components/DiffView";
import { ImportBar } from "./components/ImportBar";
import { ProjectPanel } from "./components/ProjectPanel";
import { TransformForm } from "./components/TransformForm";
import { VersionDetail } from "./components/VersionDetail";
import { VersionTree } from "./components/VersionTree";
import { Empty, ErrorBanner, Section } from "./components/common";
import { ReferencePanel } from "./components/ReferencePanel";
import type { RollFocus } from "./components/PianoRoll";
import { ProjectApiContext, useProjectApi } from "./components/ProjectApiContext";
import { ProjectHub } from "./components/ProjectHub";

function ProjectWorkspace({ onCatalogChanged, revision }: { onCatalogChanged: () => void; revision: number }) {
  const api = useProjectApi();
  const [health, setHealth] = useState<HealthResult | null>(null);
  const [project, setProject] = useState<ProjectStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [compareA, setCompareA] = useState<string | null>(null);
  const [compareB, setCompareB] = useState<string | null>(null);
  const [showTransform, setShowTransform] = useState(false);
  const [transformRegion, setTransformRegion] = useState<ScoreRegion | undefined>();
  const [transformNoteId, setTransformNoteId] = useState<string | undefined>();
  const [transformWarnings, setTransformWarnings] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [scoreSelection, setScoreSelection] = useState<ScoreRegion | null>(null);
  const [referenceFocus, setReferenceFocus] = useState<RollFocus | null>(null);
  const [referenceCursor, setReferenceCursor] = useState<number | null>(null);

  const refresh = useCallback(async () => {
    try {
      setProject((await api.project()).result);
      onCatalogChanged();
    } catch (e) {
      setError(errMsg(e));
    }
  }, [api, onCatalogChanged]);

  const onError = useCallback((message: string) => setError(message), []);
  const onDraftSaved = useCallback((id: string) => {
    void refresh().then(() => { setSelectedId(id); setScoreSelection(null); setReferenceFocus(null); setShowTransform(false); });
  }, [refresh]);

  useEffect(() => {
    void refresh();
    api
      .health()
      .then((env) => setHealth(env.result))
      .catch((e) => setError(errMsg(e)));
  }, [refresh, api, revision]);

  // Keep the selection valid as the version list changes.
  useEffect(() => {
    if (!project) return;
    const ids = project.versions.map((v) => v.version_id);
    if (!selectedId || !ids.includes(selectedId)) {
      setSelectedId(project.working_version ?? project.active_version ?? ids[0] ?? null);
    }
  }, [project, selectedId]);

  const versions = project?.versions ?? [];
  const selected = versions.find((v) => v.version_id === selectedId) ?? null;

  return (
    <div className="project-workspace">
      <header className="app-header">
        <div>
          <h2>项目 · {project?.project.title ?? "加载中…"}</h2>
          <p className="subtitle">参考材料、草稿、版本和决策均属于这个项目</p>
        </div>
        <div className="health">
          {health ? (
            <span className="muted">
              {health.service} v{health.version} · music-core {health.music_core_version}
              {project?.storage === "sqlite" ? " · 已自动保存到本机" : ""}
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
          <Section title="加入当前项目">
            <ImportBar onImported={onDraftSaved} onError={onError} />
          </Section>
          <Section title={`本项目版本（${versions.length}）`}>
            <p className="muted version-help">这里是修改历史。换一首作品，请在上方新建项目。</p>
            <VersionTree
              versions={versions}
              activeId={project?.active_version ?? null}
              selectedId={selectedId}
              onSelect={(id) => { setSelectedId(id); setShowTransform(false); setScoreSelection(null); setReferenceFocus(null); }}
            />
          </Section>
        </aside>

        <section className="content">
          <ReferencePanel score={selected} selection={scoreSelection} onCreated={onDraftSaved}
            onCursor={setReferenceCursor}
            onReferencesChanged={onCatalogChanged}
            onLocate={(region) => setReferenceFocus({ region, noteIds: [] })} />
          {selected ? (
            <VersionDetail
              key={selected.version_id}
              version={selected}
              isActive={selected.version_id === (project?.active_version ?? "")}
              onError={onError}
              onChanged={refresh}
              onTransform={(region, noteId) => {
                setTransformRegion(region); setTransformNoteId(noteId); setShowTransform(true);
              }}
              onCompare={() => setCompareA(selected.version_id)}
              onEdited={onDraftSaved}
              onSelectionChange={setScoreSelection}
              externalFocus={referenceFocus}
              referenceCursor={referenceCursor}
            />
          ) : (
            <Empty>这个项目还没有谱稿。可以导入参考音视频并新建扒谱草稿，或将 MIDI 加入本项目。</Empty>
          )}

          {showTransform && selected ? (
            <TransformForm
              key={`${selected.version_id}:${JSON.stringify(transformRegion)}:${transformNoteId}`}
              source={selected}
              initialRegion={transformRegion}
              noteId={transformNoteId}
              onError={onError}
              onCancel={() => setShowTransform(false)}
              onDone={(newId, warnings) => {
                setShowTransform(false);
                setCompareA(selected.version_id); setCompareB(newId);
                setTransformWarnings(warnings);
                void refresh().then(() => setSelectedId(newId));
              }}
            />
          ) : null}

          {transformWarnings.length ? <details className="panel" open><summary>最近变换的校验提示</summary><ul>{transformWarnings.map((warning, i) => <li key={i}>{warning}</li>)}</ul></details> : null}

          <DiffView
            versions={versions}
            aId={compareA}
            bId={compareB}
            setAId={setCompareA}
            setBId={setCompareB}
            onError={onError}
            onChanged={refresh}
          />

          <AgentPanel enabled={versions.length > 0} onError={onError} onProjectChanged={refresh} />
          {project ? <ProjectPanel project={project.project} onError={onError} onChanged={refresh} /> : null}
        </section>
      </div>
    </div>
  );
}

function App() {
  const [catalog, setCatalog] = useState<ProjectCatalog>({projects: [], active_project_id: null});
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const api = useMemo(() => createApi(selectedId ?? undefined), [selectedId]);

  const refreshCatalog = useCallback(() => {
    void workspaceApi.catalog().then((env) => setCatalog(env.result)).catch((e) => setError(errMsg(e)));
  }, []);

  useEffect(() => {
    workspaceApi.catalog().then((env) => {setCatalog(env.result);setSelectedId(env.result.active_project_id);})
      .catch((e) => setError(errMsg(e))).finally(() => setLoading(false));
  }, []);

  async function openProject(id: string) {
    if (!id) return;
    setBusy(true);setError(null);
    try {await workspaceApi.openProject(id);setSelectedId(id);refreshCatalog();}
    catch (e) {setError(errMsg(e));} finally {setBusy(false);}
  }

  async function createProject(title: string, workflow: "composition" | "transcription"): Promise<boolean> {
    setBusy(true);setError(null);
    try {
      const created = (await workspaceApi.createProject(title, workflow)).result.project;
      setSelectedId(created.id);
      setCatalog((await workspaceApi.catalog()).result);
      return true;
    } catch (e) {setError(errMsg(e));return false;} finally {setBusy(false);}
  }

  async function renameProject(id: string, title: string): Promise<boolean> {
    setBusy(true);setError(null);
    try {await workspaceApi.renameProject(id,title);refreshCatalog();setRevision((value) => value+1);return true;}
    catch(e) {setError(errMsg(e));return false;} finally {setBusy(false);}
  }

  return <main className="app">
    <ProjectHub catalog={catalog} selectedId={selectedId} busy={busy || loading}
      onOpen={openProject} onCreate={createProject} onRename={renameProject} />
    {error ? <ErrorBanner message={error} /> : null}
    {loading ? <p>正在打开本机项目…</p> : selectedId ? <ProjectApiContext.Provider value={api}>
      <ProjectWorkspace key={selectedId} onCatalogChanged={refreshCatalog} revision={revision} />
    </ProjectApiContext.Provider> : <section className="panel project-empty"><h2>从一个新项目开始</h2><p>为一首原创作品或一次钢琴改编建立项目，之后的音视频、谱稿与修改历史都会保存在这里。</p></section>}
  </main>;
}

export default App;
