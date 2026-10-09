"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const APP_PATH = path.resolve(__dirname, "../agentrelay/static/app.js");
const BOOTSTRAP = `  wireEvents();
  syncWorkspaceControls();
  boot();
  setInterval(() => { if (app.workspaceId) loadState({ quiet: true }); }, 15000);
})();`;
const TEST_EXPORT = `  globalThis.__agentRelayTest = {
    app,
    loadState,
    mutate,
    loadContext,
    closeTicket,
    selectWorkspace
  };
})();`;

class FakeClassList {
  constructor() { this.values = new Set(); }
  add(...names) { names.forEach((name) => this.values.add(name)); }
  remove(...names) { names.forEach((name) => this.values.delete(name)); }
  contains(name) { return this.values.has(name); }
  toggle(name, force) {
    const enabled = force === undefined ? !this.values.has(name) : Boolean(force);
    if (enabled) this.values.add(name);
    else this.values.delete(name);
    return enabled;
  }
}

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.children = [];
    this.dataset = {};
    this.style = {};
    this.attributes = new Map();
    this.classList = new FakeClassList();
    this.className = "";
    this.textContent = "";
    this.value = "";
    this.hidden = false;
    this.disabled = false;
    this.open = false;
    this.required = false;
    this.title = "";
    this._fallbackLastChild = { textContent: "" };
  }
  append(...items) { this.children.push(...items); }
  replaceChildren(...items) { this.children = [...items]; }
  get lastChild() { return this.children.at(-1) || this._fallbackLastChild; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  addEventListener() {}
  remove() {}
  reset() { this.value = ""; }
  close() { this.open = false; }
  showModal() { this.open = true; }
  focus() {}
  closest() { return null; }
  querySelector() { return null; }
  querySelectorAll() { return []; }
}

class FakeHeaders {
  constructor(initial = {}) {
    this.values = new Map();
    if (initial instanceof FakeHeaders) {
      initial.values.forEach((value, key) => this.values.set(key, value));
    } else if (initial && typeof initial.forEach === "function") {
      initial.forEach((value, key) => this.set(key, value));
    } else {
      Object.entries(initial || {}).forEach(([key, value]) => this.set(key, value));
    }
  }
  set(name, value) { this.values.set(String(name).toLowerCase(), String(value)); }
  get(name) { return this.values.get(String(name).toLowerCase()) ?? null; }
  forEach(callback) { this.values.forEach((value, key) => callback(value, key, this)); }
}

function countOccurrences(source, needle) {
  let count = 0;
  let offset = 0;
  while ((offset = source.indexOf(needle, offset)) !== -1) {
    count += 1;
    offset += needle.length;
  }
  return count;
}

function createDocument() {
  const elements = new Map();
  const composite = new Map();
  const pageViews = ["board", "executions", "profiles", "activity"].map((name) => new FakeElement("section", `${name}-view`));
  const byId = (id) => {
    if (!elements.has(id)) elements.set(id, new FakeElement("div", id));
    return elements.get(id);
  };
  const getComposite = (selector) => {
    if (!composite.has(selector)) composite.set(selector, new FakeElement("select"));
    return composite.get(selector);
  };
  const document = {
    title: "",
    body: new FakeElement("body"),
    createElement: (tag) => new FakeElement(tag),
    querySelector(selector) {
      if (selector === ".connection") return byId("connection");
      if (selector.includes(" ")) return getComposite(selector);
      if (selector.startsWith("#")) return byId(selector.slice(1));
      return getComposite(selector);
    },
    querySelectorAll(selector) {
      if (selector === ".page-view") return pageViews;
      return [];
    }
  };
  return { document, byId };
}

function createStorage() {
  const values = new Map();
  return {
    getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, String(value)),
    removeItem: (key) => values.delete(key)
  };
}

function controlledFetch() {
  const calls = [];
  const fetch = (url, options = {}) => new Promise((resolve, reject) => {
    calls.push({ url, options, resolve, reject });
  });
  const respond = (index, payload, status = 200) => {
    const call = calls[index];
    assert.ok(call, `No existe la solicitud controlada ${index}`);
    call.resolve({
      ok: status >= 200 && status < 300,
      status,
      headers: { get: (name) => String(name).toLowerCase() === "content-type" ? "application/json" : null },
      json: async () => payload
    });
  };
  return { fetch, calls, respond };
}

function state(workspaceId, marker, tickets = []) {
  return {
    workspace: { id: workspaceId, name: `Proyecto ${workspaceId.toUpperCase()}`, database: `${workspaceId}.sqlite`, demo: false },
    marker,
    tickets,
    profiles: [],
    events: [],
    execution: { enabled: false, workers: [], runs: [] }
  };
}

function ticket(title) {
  return {
    id: "T-1",
    revision: 1,
    title,
    description: "",
    type: "task",
    status: "done",
    priority: "normal",
    ready: false,
    blockers: [],
    depends_on: [],
    acceptance: [],
    evidence: []
  };
}

function context(workspaceId, title) {
  return {
    workspace: { id: workspaceId },
    ticket: ticket(title),
    parent: null,
    dependencies: [],
    children: [],
    events: []
  };
}

function loadHarness() {
  const source = fs.readFileSync(APP_PATH, "utf8");
  const occurrences = countOccurrences(source, BOOTSTRAP);
  assert.equal(occurrences, 1, "No se encontró exactamente una vez el bootstrap final esperado de app.js");
  const instrumented = source.replace(BOOTSTRAP, TEST_EXPORT);
  const { document } = createDocument();
  const transport = controlledFetch();
  const sandbox = {
    console,
    document,
    window: { confirm: () => true },
    localStorage: createStorage(),
    sessionStorage: createStorage(),
    fetch: transport.fetch,
    Headers: FakeHeaders,
    setTimeout: () => 1,
    clearTimeout: () => {},
    setInterval: () => { throw new Error("El bootstrap real no debía ejecutarse en el arnés"); },
    clearInterval: () => {},
    URL,
    Blob,
    Intl,
    Date,
    JSON,
    encodeURIComponent
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(instrumented, sandbox, { filename: APP_PATH });
  const hooks = sandbox.__agentRelayTest;
  assert.ok(hooks, "app.js no expuso los hooks de prueba");
  hooks.app.workspaces = [
    { id: "a", name: "Proyecto A", database: "a.sqlite", demo: false },
    { id: "b", name: "Proyecto B", database: "b.sqlite", demo: false }
  ];
  hooks.app.workspaceId = "a";
  hooks.app.workspaceEpoch = 1;
  hooks.app.legacyWorkspace = false;
  hooks.app.state = state("a", "initial");
  return { ...hooks, transport };
}

async function oldGetCannotOverwriteMutation() {
  const h = loadHarness();
  const oldLoad = h.loadState({ quiet: true });
  assert.equal(h.transport.calls.length, 1);

  const mutation = h.mutate("create_ticket", { title: "Nueva" }, null);
  assert.equal(h.transport.calls.length, 2);
  h.transport.respond(1, { result: { id: "T-2" }, state: state("a", "mutation") });
  await mutation;

  h.transport.respond(0, state("a", "stale-get"));
  await oldLoad;
  assert.equal(h.app.state.marker, "mutation", "un GET anterior a la mutación sobrescribió el estado confirmado");
}

async function closeAndReopenRejectsOldContext() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  const oldContext = h.loadContext("T-1");
  assert.equal(h.transport.calls.length, 1);

  h.closeTicket();
  h.app.selectedId = "T-1";
  h.app.drawerDirty = false;
  const newContext = h.loadContext("T-1");
  assert.equal(h.transport.calls.length, 2);

  h.transport.respond(1, context("a", "Contexto nuevo"));
  await newContext;
  assert.equal(h.app.context.ticket.title, "Contexto nuevo");

  h.transport.respond(0, context("a", "Contexto antiguo"));
  await oldContext;
  assert.equal(h.app.context.ticket.title, "Contexto nuevo", "el contexto anterior al cierre reemplazó el de la reapertura");
}

async function workspaceChangeRejectsOldResponses() {
  const h = loadHarness();
  const oldState = h.loadState({ quiet: true });
  h.app.selectedId = "T-1";
  const oldContext = h.loadContext("T-1");
  assert.equal(h.transport.calls.length, 2);

  const switchWorkspace = h.selectWorkspace("b");
  assert.equal(h.app.workspaceId, "b");
  assert.equal(h.transport.calls.length, 3);
  assert.equal(h.transport.calls[2].options.headers.get("X-AgentRelay-Workspace"), "b");

  h.transport.respond(2, state("b", "current-b"));
  await switchWorkspace;
  h.transport.respond(0, state("a", "late-a"));
  h.transport.respond(1, context("a", "Contexto tardío A"));
  await Promise.all([oldState, oldContext]);

  assert.equal(h.app.workspaceId, "b");
  assert.equal(h.app.state.marker, "current-b", "una respuesta del proyecto anterior sustituyó el estado actual");
  assert.equal(h.app.context, null, "un contexto del proyecto anterior volvió a abrir datos cerrados");
}

async function mutationCapturesHeaderAndBlocksSwitch() {
  const h = loadHarness();
  const mutation = h.mutate("create_ticket", { title: "Nueva" }, null);
  assert.equal(h.transport.calls.length, 1);
  const request = h.transport.calls[0];
  assert.equal(request.options.headers.get("X-AgentRelay-Workspace"), "a", "la mutación no capturó el proyecto inicial");
  assert.equal(h.app.mutationCount, 1);

  await h.selectWorkspace("b");
  assert.equal(h.app.workspaceId, "a", "se permitió cambiar de proyecto durante una mutación");
  assert.equal(h.transport.calls.length, 1, "el cambio bloqueado inició una carga de estado");

  await assert.rejects(
    h.mutate("create_ticket", { title: "Concurrente" }, null),
    /operación en curso/,
    "una segunda escritura debía rechazarse mientras la primera seguía pendiente"
  );
  assert.equal(h.transport.calls.length, 1, "la escritura concurrente llegó a fetch");
  assert.equal(request.options.headers.get("X-AgentRelay-Workspace"), "a", "la cabecera capturada cambió durante la operación");

  h.transport.respond(0, { result: { id: "T-2" }, state: state("a", "written-a") });
  await mutation;
  assert.equal(h.app.mutationCount, 0);
  assert.equal(h.app.state.marker, "written-a");
}

const tests = [
  ["GET antiguo no sobrescribe una mutación", oldGetCannotOverwriteMutation],
  ["cerrar y reabrir descarta contexto antiguo", closeAndReopenRejectsOldContext],
  ["cambiar de proyecto descarta respuestas antiguas", workspaceChangeRejectsOldResponses],
  ["mutación captura cabecera y bloquea cambio", mutationCapturesHeaderAndBlocksSwitch]
];

(async () => {
  for (const [name, test] of tests) {
    await test();
    process.stdout.write(`ok - ${name}\n`);
  }
  process.stdout.write(`${tests.length} pruebas de carreras UI superadas\n`);
})().catch((error) => {
  console.error(error && error.stack ? error.stack : error);
  process.exitCode = 1;
});
