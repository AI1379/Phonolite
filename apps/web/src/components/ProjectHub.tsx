import { useState } from "react";
import type { ProjectCatalog } from "../types";
import { Button } from "./common";

export function ProjectHub({ catalog, selectedId, busy, onOpen, onCreate, onRename }: {
  catalog: ProjectCatalog; selectedId: string | null; busy: boolean;
  onOpen: (id: string) => Promise<void>;
  onCreate: (title: string, workflow: "composition" | "transcription") => Promise<boolean>;
  onRename: (id: string, title: string) => Promise<boolean>;
}) {
  const [form, setForm] = useState<"create" | "rename" | null>(null);
  const [title, setTitle] = useState("");
  const [workflow, setWorkflow] = useState<"composition" | "transcription">("transcription");
  const selected = catalog.projects.find((project) => project.id === selectedId);
  async function submit() {
    const success = form === "rename" && selectedId ? await onRename(selectedId, title.trim()) : await onCreate(title.trim(), workflow);
    if (success) { setForm(null); setTitle(""); }
  }
  return <section className="project-hub" aria-label="项目管理">
    <div className="project-hub-heading"><div><h1>Music Agent Workbench</h1><p>一个项目对应一首作品或一次改编任务；版本记录这个项目中的每次修改。</p></div>
      <Button variant="primary" disabled={busy} onClick={() => {setForm("create");setTitle("");}}>＋ 新建项目</Button></div>
    <div className="project-switcher">
      <label>当前项目<select aria-label="当前项目" disabled={busy || !catalog.projects.length} value={selectedId ?? ""} onChange={(event) => void onOpen(event.target.value)}>
        {!selectedId ? <option value="">选择一个项目</option> : null}
        {catalog.projects.map((project) => <option key={project.id} value={project.id}>{project.title} · {project.version_count} 个版本</option>)}
      </select></label>
      {selected ? <><span className="tag">{selected.workflow === "transcription" ? "扒谱与改编" : selected.workflow === "composition" ? "原创与学习" : "已有项目"}</span>
        <span className="muted">{selected.reference_count} 份参考材料 · {selected.version_count} 个版本</span>
        <Button disabled={busy} onClick={() => {setForm("rename");setTitle(selected.title);}}>重命名项目</Button></> : null}
    </div>
    {form ? <form className="project-create-form" onSubmit={(event) => {event.preventDefault();void submit();}}>
      <label>{form === "create" ? "新项目名称" : "项目名称"}<input aria-label={form === "create" ? "新项目名称" : "重命名项目名称"} autoFocus maxLength={160} value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如：某首曲子的钢琴改编" /></label>
      {form === "create" ? <label>工作方向<select aria-label="项目工作方向" value={workflow} onChange={(event) => setWorkflow(event.target.value as typeof workflow)}><option value="transcription">扒谱与钢琴改编</option><option value="composition">原创创作与学习</option></select></label> : null}
      <div className="action-row"><button className="btn primary" type="submit" disabled={busy || !title.trim()}>{busy ? "保存中…" : form === "create" ? "创建并打开空白项目" : "保存项目名称"}</button>
        <Button disabled={busy} onClick={() => setForm(null)}>取消</Button></div>
      {form === "create" ? <p className="muted">新项目从空白开始。当前项目的材料、版本和决策会完整保留。</p> : null}
    </form> : null}
  </section>;
}
