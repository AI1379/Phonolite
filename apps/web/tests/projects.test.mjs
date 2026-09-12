import assert from "node:assert/strict";
import test from "node:test";
import { createApi } from "../src/api.ts";

test("project clients keep their project when another client is opened", async () => {
  const previous = globalThis.fetch;
  const requests = [];
  globalThis.fetch = async (path, options) => {
    requests.push({ path, headers: options.headers });
    return new Response(JSON.stringify({ok:true,result:{},warnings:[],artifacts:[],provenance:{}}));
  };
  try {
    const oldProject = createApi("project-a");
    const newProject = createApi("project-b");
    await newProject.project();
    // Simulates an upload that finishes reading its file after a UI switch.
    await oldProject.importAudio("data", "source.wav");
    assert.equal(requests[0].headers["X-Workbench-Project"], "project-b");
    assert.equal(requests[1].headers["X-Workbench-Project"], "project-a");
  } finally { globalThis.fetch = previous; }
});

test("media and WebSocket URLs carry the captured project", () => {
  const previous = globalThis.window;
  globalThis.window = { location: { protocol: "http:", host: "localhost:5174" } };
  try {
    const api = createApi("piece-a");
    assert.equal(api.artifactUrl("token"), "/api/artifact/token?project_id=piece-a");
    assert.equal(api.agentSocketUrl("task-1"), "ws://localhost:5174/ws?task_id=task-1&project_id=piece-a");
  } finally {
    if (previous === undefined) delete globalThis.window;
    else globalThis.window = previous;
  }
});
