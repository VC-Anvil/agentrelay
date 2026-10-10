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
    openTicket,
    closeTicket,
    selectWorkspace,
    acceptanceContextToken,
    buildCompletionPayload,
    handleCompletionConflict,
    refreshCompletionContext,
    acceptanceRefreshConflict,
    captureDrawer,
    isCurrentDrawer,
    reviewDraftFor,
    submitActionForm,
    renderDrawer
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
    this.checked = false;
    this.listeners = new Map();
    this._fallbackLastChild = { textContent: "" };
  }
  append(...items) {
    items.forEach((item) => { if (item && typeof item === "object") item.parentNode = this; });
    this.children.push(...items);
  }
  replaceChildren(...items) {
    this.children.forEach((item) => { if (item && item.parentNode === this) item.parentNode = null; });
    this.children = [];
    this.append(...items);
  }
  get lastChild() { return this.children.at(-1) || this._fallbackLastChild; }
  setAttribute(name, value) { this.attributes.set(name, String(value)); }
  getAttribute(name) { return this.attributes.get(name) ?? null; }
  removeAttribute(name) { this.attributes.delete(name); }
  addEventListener(name, listener) {
    if (!this.listeners.has(name)) this.listeners.set(name, []);
    this.listeners.get(name).push(listener);
  }
  async dispatch(name, event = {}) {
    for (const listener of this.listeners.get(name) || []) await listener({ currentTarget: this, target: this, ...event });
  }
  remove() {
    if (!this.parentNode) return;
    this.parentNode.children = this.parentNode.children.filter((item) => item !== this);
    this.parentNode = null;
  }
  reset() { this.value = ""; }
  close() { this.open = false; }
  showModal() { this.open = true; }
  focus() {}
  closest() { return null; }
  matches(selector) {
    const value = selector.trim();
    if (/^[a-z]+$/i.test(value)) return this.tagName === value.toUpperCase();
    const data = value.match(/^\[data-([a-z0-9-]+)\]$/i);
    if (data) {
      const key = data[1].replace(/-([a-z])/g, (_, letter) => letter.toUpperCase());
      return Object.prototype.hasOwnProperty.call(this.dataset, key);
    }
    return false;
  }
  querySelector(selector) { return this.querySelectorAll(selector)[0] || null; }
  querySelectorAll(selector) {
    const selectors = selector.split(",").map((item) => item.trim());
    const matches = [];
    const visit = (element) => {
      for (const child of element.children || []) {
        if (selectors.some((item) => child.matches?.(item))) matches.push(child);
        visit(child);
      }
    };
    visit(this);
    return matches;
  }
  contains(candidate) {
    return candidate === this || this.children.some((child) => child?.contains?.(candidate));
  }
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

class FakeFormData {
  constructor(form) {
    this.values = new Map(form.formValues || []);
    const controls = form.querySelectorAll?.("input, textarea, select, button") || [];
    if (controls.length) {
      for (const name of this.values.keys()) {
        const named = controls.filter((control) => control.name === name);
        if (named.length && named.every((control) => control.disabled)) this.values.delete(name);
      }
    }
  }
  get(name) {
    const value = this.values.get(name);
    return Array.isArray(value) ? (value[0] ?? null) : (value ?? null);
  }
  getAll(name) {
    const value = this.values.get(name);
    if (value === undefined || value === null) return [];
    return Array.isArray(value) ? [...value] : [value];
  }
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

function treeText(element) {
  if (!element) return "";
  return [element.textContent || "", ...(element.children || []).map(treeText)].filter(Boolean).join(" ");
}

function findElement(element, predicate) {
  if (!element) return null;
  if (predicate(element)) return element;
  for (const child of element.children || []) {
    const match = findElement(child, predicate);
    if (match) return match;
  }
  return null;
}

async function waitForCalls(transport, count) {
  for (let attempt = 0; attempt < 20 && transport.calls.length < count; attempt += 1) {
    await new Promise((resolve) => setImmediate(resolve));
  }
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

const OLD_TOKEN = `sha256:${"a".repeat(64)}`;
const NEW_TOKEN = `sha256:${"b".repeat(64)}`;

function reviewContext(workspaceId, token = OLD_TOKEN) {
  const item = ticket("Revisión");
  item.status = "review";
  item.acceptance = ["Criterio A", "Criterio B"];
  return {
    workspace: { id: workspaceId },
    ticket: item,
    parent: null,
    dependencies: [],
    children: [],
    events: [],
    acceptance_context: token ? {
      schema_version: 1,
      token,
      children_count: 0,
      dependencies_count: 0,
      source_checks_count: 0
    } : undefined
  };
}

function completionForm(token = OLD_TOKEN, verification = "Revisión pendiente") {
  const form = new FakeElement("form");
  form.dataset.acceptanceContextToken = token;
  form.formValues = new Map([
    ["verification", verification],
    ["accepted_criteria", ["Criterio A"]]
  ]);
  return form;
}

function drawerActionForm(action) {
  const form = new FakeElement("form");
  const fields = {
    checkpoint: [["checkpoint", "Avance de A"]],
    submit: [["summary", "Entrega A"], ["evidence_kind", "test"], ["evidence_label", "Fixture A"], ["evidence_uri", "fixture://a"]],
    comment: [["body", "Comentario de A"]]
  };
  form.formValues = new Map(fields[action]);
  return form;
}

function definitionValues(title = "Título enviado") {
  return new Map([
    ["title", title], ["description", "Descripción"], ["type", "task"],
    ["priority", "normal"], ["parent_id", ""], ["profile_id", ""],
    ["depends_on", ""], ["acceptance", "Criterio A\nCriterio B"]
  ]);
}

function actionForm(body, action) {
  return findElement(body, (element) => element.dataset.actionPanel === action);
}

function editableControls(body) {
  return body.querySelectorAll("input, textarea, select, button");
}

function contextForTicket(id, title, status, token = OLD_TOKEN) {
  const value = reviewContext("a", token);
  value.ticket.id = id;
  value.ticket.title = title;
  value.ticket.status = status;
  value.ticket.assignee = status === "in_progress" ? "human" : "agent:author";
  if (status !== "review") value.acceptance_context = null;
  return value;
}

function loadHarness() {
  const source = fs.readFileSync(APP_PATH, "utf8");
  const occurrences = countOccurrences(source, BOOTSTRAP);
  assert.equal(occurrences, 1, "No se encontró exactamente una vez el bootstrap final esperado de app.js");
  const instrumented = source.replace(BOOTSTRAP, TEST_EXPORT);
  const { document, byId } = createDocument();
  const transport = controlledFetch();
  const confirmations = [];
  let confirmResponse = true;
  const sandbox = {
    console,
    document,
    window: { confirm: (message) => { confirmations.push(String(message)); return confirmResponse; } },
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
    FormData: FakeFormData,
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
  return { ...hooks, transport, byId, confirmations, setConfirmResponse(value) { confirmResponse = Boolean(value); } };
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

function completionUsesPresentedToken() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", NEW_TOKEN);
  const payload = h.buildCompletionPayload(h.app.context.ticket, {
    verification: "Comprobación conservada",
    acceptedCriteria: ["Criterio A"],
    acceptanceToken: OLD_TOKEN
  });
  assert.equal(payload.expected_acceptance_context_token, OLD_TOKEN, "se sustituyó silenciosamente el token presentado por el contexto más reciente");
  assert.equal(payload.verification, "Comprobación conservada");
}

async function staleApiConflictPreservesDraftAndLoadsFreshContext() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  h.app.drawerDirty = true;
  const ticketAtReview = h.app.context.ticket;
  const form = new FakeElement("form");
  form.dataset.acceptanceContextToken = OLD_TOKEN;
  form.formValues = new Map([
    ["verification", "Revisé la evidencia concreta"],
    ["accepted_criteria", ["Criterio B"]]
  ]);

  const submission = h.submitActionForm({ preventDefault() {}, currentTarget: form }, "complete", ticketAtReview);
  assert.equal(h.transport.calls.length, 1, "la aceptación no llegó a la API");
  const sent = JSON.parse(h.transport.calls[0].options.body);
  assert.equal(sent.data.expected_acceptance_context_token, OLD_TOKEN);
  h.transport.respond(0, { error: "acceptance context changed; reread ticket context before completing" }, 409);
  await waitForCalls(h.transport, 2);
  assert.equal(h.transport.calls.length, 2, "el conflicto no solicitó contexto actualizado");
  h.transport.respond(1, reviewContext("a", NEW_TOKEN));
  await submission;

  assert.equal(h.transport.calls.length, 2, "la aceptación se reenvió automáticamente tras recargar contexto");
  assert.equal(h.app.context.acceptance_context.token, NEW_TOKEN);
  const draft = h.reviewDraftFor(h.app.context.ticket);
  assert.equal(draft.verification, "Revisé la evidencia concreta");
  assert.deepEqual([...draft.acceptedCriteria], ["Criterio B"]);
  assert.equal(draft.needsConfirmation, true);
}

function refreshedContextRequiresExplicitConfirmation() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", NEW_TOKEN);
  h.app.reviewDraft = {
    workspaceId: "a",
    workspaceEpoch: h.app.workspaceEpoch,
    drawerEpoch: h.app.drawerEpoch,
    ticketId: "T-1",
    verification: "Borrador",
    acceptedCriteria: ["Criterio A"],
    needsConfirmation: true
  };
  const args = {
    verification: "Borrador",
    acceptedCriteria: ["Criterio A"],
    acceptanceToken: NEW_TOKEN
  };
  assert.throws(() => h.buildCompletionPayload(h.app.context.ticket, args), /confirma de nuevo/);
  const payload = h.buildCompletionPayload(h.app.context.ticket, { ...args, confirmed: true });
  assert.equal(payload.expected_acceptance_context_token, NEW_TOKEN);
}

async function workspaceChangeDiscardsConflictRefreshAndDraft() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  const payload = h.buildCompletionPayload(h.app.context.ticket, {
    verification: "Borrador de A",
    acceptedCriteria: ["Criterio A"],
    acceptanceToken: OLD_TOKEN
  });
  const refresh = h.handleCompletionConflict(h.app.context.ticket, payload);
  assert.equal(h.transport.calls.length, 1);

  const switchWorkspace = h.selectWorkspace("b");
  assert.equal(h.transport.calls.length, 2);
  h.transport.respond(1, state("b", "current-b"));
  await switchWorkspace;
  h.transport.respond(0, reviewContext("a", NEW_TOKEN));
  assert.equal(await refresh, false);

  assert.equal(h.app.workspaceId, "b");
  assert.equal(h.app.reviewDraft, null, "el borrador del proyecto anterior sobrevivió al cambio");
  assert.equal(h.app.context, null, "la recarga del conflicto anterior abrió contexto en el proyecto nuevo");
}

function legacyContextCannotBeAcceptedWithoutToken() {
  const h = loadHarness();
  h.app.legacyWorkspace = true;
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", null);
  assert.equal(h.acceptanceContextToken(), null);
  assert.throws(() => h.buildCompletionPayload(h.app.context.ticket, {
    verification: "No debe enviarse",
    acceptedCriteria: ["Criterio A"],
    acceptanceToken: ""
  }), /huella de aceptación requerida/);
}

async function unrelated409DoesNotResetReview() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  h.app.drawerDirty = true;
  const form = new FakeElement("form");
  form.dataset.acceptanceContextToken = OLD_TOKEN;
  form.formValues = new Map([
    ["verification", "Borrador intacto"],
    ["accepted_criteria", ["Criterio A"]]
  ]);
  const submission = h.submitActionForm({ preventDefault() {}, currentTarget: form }, "complete", h.app.context.ticket);
  h.transport.respond(0, { error: "assignee cannot review own work" }, 409);
  await submission;
  assert.equal(h.transport.calls.length, 1, "un 409 ajeno al contexto inició una recarga");
  assert.equal(h.app.reviewDraft, null, "un 409 ajeno al contexto creó un borrador de reconfirmación");
  assert.equal(h.app.drawerDirty, true, "un 409 ajeno al contexto descartó el formulario abierto");
  assert.equal(h.acceptanceRefreshConflict({ status: 409, message: "assignee cannot review own work" }), false);
}

async function failedConflictRefreshCanBeRetried() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  const payload = h.buildCompletionPayload(h.app.context.ticket, {
    verification: "Borrador recuperable",
    acceptedCriteria: ["Criterio B"],
    acceptanceToken: OLD_TOKEN
  });
  const firstRefresh = h.handleCompletionConflict(h.app.context.ticket, payload);
  h.transport.calls[0].reject(new Error("sin conexión"));
  assert.equal(await firstRefresh, false);
  assert.equal(h.app.reviewDraft.refreshRequired, true);
  const body = h.byId("drawer-body");
  assert.match(treeText(body), /Reintentar carga de contexto/);
  const verification = findElement(body, (element) => element.name === "verification");
  const criterionA = findElement(body, (element) => element.name === "accepted_criteria" && element.value === "Criterio A");
  const criterionB = findElement(body, (element) => element.name === "accepted_criteria" && element.value === "Criterio B");
  const retryButton = findElement(body, (element) => element.textContent === "Reintentar carga de contexto");
  verification.value = "Borrador editado antes del retry";
  criterionA.checked = true;
  criterionB.checked = false;

  const retry = retryButton.dispatch("click");
  assert.equal(h.transport.calls.length, 2);
  assert.equal(verification.disabled, true, "la verificación quedó editable durante el GET de retry");
  assert.equal(criterionA.disabled, true, "los criterios quedaron editables durante el GET de retry");
  h.transport.respond(1, reviewContext("a", NEW_TOKEN));
  await retry;
  assert.equal(h.app.reviewDraft.refreshRequired, false);
  assert.equal(h.app.reviewDraft.verification, "Borrador editado antes del retry");
  assert.deepEqual([...h.app.reviewDraft.acceptedCriteria], ["Criterio A"]);
  assert.match(treeText(h.byId("drawer-body")), /He revisado el contexto actualizado/);
  const refreshedVerification = findElement(h.byId("drawer-body"), (element) => element.name === "verification");
  assert.equal(refreshedVerification.value, "Borrador editado antes del retry");
}

function renderedReviewShowsCoveredMaterial() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  const value = reviewContext("a", OLD_TOKEN);
  const related = {
    ...ticket("Hija detallada"),
    id: "T-2",
    revision: 7,
    status: "done",
    description: "Descripción inspeccionable",
    acceptance: ["Criterio relacionado visible"],
    checkpoint: "Resumen relacionado visible",
    evidence: [{ kind: "informe", label: "Evidencia relacionada", uri: "fixture://evidencia" }]
  };
  value.children = [related];
  value.dependencies = [{ ...related, id: "T-3", title: "Dependencia detallada" }];
  value.acceptance_context.children_count = 1;
  value.acceptance_context.dependencies_count = 1;
  value.acceptance_context.source_checks_count = 4;
  value.source_checks = [1, 2, 3].map((id) => ({
    check_id: id,
    ticket_revision: 1,
    ticket_revision_matches_now: true,
    snapshot_id: `sha256:${String(id).repeat(64)}`,
    report_sha256: String(id + 3).repeat(64),
    summary: { total: 2, unchanged: 1, modified: 1, missing: 0, uncheckable: 0 },
    checked_at: "2026-10-10T10:00:00Z"
  }));
  value.source_checks_page = { total: 4, count: 3, limit: 3, next_before_id: 1 };
  h.app.context = value;
  h.renderDrawer();
  const text = treeText(h.byId("drawer-body"));
  for (const expected of [
    "T-2 · Hija detallada · Hecha · rev. 7",
    "Descripción inspeccionable",
    "Criterio relacionado visible",
    "Resumen relacionado visible",
    "Evidencia relacionada · informe · fixture://evidencia",
    "Mostrando 3 de 4 observaciones históricas",
    "Comprobación #1 · revisión observada 1",
    `Snapshot: sha256:${"3".repeat(64)}`,
    `SHA-256 del informe: ${"6".repeat(64)}`,
    "modificados: 1"
  ]) assert.ok(text.includes(expected), `no se renderizó material cubierto: ${expected}`);
}

async function completionSuccessCannotOverwriteAnotherDrawer() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  const submission = h.submitActionForm({ preventDefault() {}, currentTarget: completionForm() }, "complete", h.app.context.ticket);
  assert.equal(h.transport.calls.length, 1);

  h.openTicket("T-2");
  const contextB = reviewContext("a", NEW_TOKEN);
  contextB.ticket.id = "T-2";
  contextB.ticket.title = "Formulario B";
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  h.app.drawerDirty = true;
  const preserved = h.app.context;

  const doneA = { ...ticket("A completada"), status: "done", revision: 2 };
  const stateB = { ...contextB.ticket };
  h.transport.respond(0, { result: doneA, state: state("a", "completion-a", [doneA, stateB]) });
  await submission;

  assert.equal(h.transport.calls.length, 2, "la completión A recargó el drawer B");
  assert.equal(h.app.selectedId, "T-2");
  assert.equal(h.app.context, preserved, "la completión A sustituyó el contexto B");
  assert.equal(h.app.drawerDirty, true, "la completión A limpió el formulario B");
  assert.equal(h.app.reviewDraft, null);
  assert.equal(h.app.state.marker, "completion-a", "el tablero no adoptó el estado confirmado");
}

async function completion409CannotInstallDraftInAnotherDrawer() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  const submission = h.submitActionForm({ preventDefault() {}, currentTarget: completionForm() }, "complete", h.app.context.ticket);

  h.openTicket("T-2");
  const contextB = reviewContext("a", NEW_TOKEN);
  contextB.ticket.id = "T-2";
  contextB.ticket.title = "Formulario B tras conflicto";
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  h.app.drawerDirty = true;
  const preserved = h.app.context;

  h.transport.respond(0, { error: "acceptance context changed; reread ticket context before completing" }, 409);
  await submission;
  assert.equal(h.transport.calls.length, 2, "el 409 de A recargó el drawer B");
  assert.equal(h.app.context, preserved);
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.reviewDraft, null, "el 409 de A instaló un borrador en B");
}

async function completionCannotOverwriteReopenedSameTicket() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = reviewContext("a", OLD_TOKEN);
  const originalEpoch = h.app.drawerEpoch;
  const submission = h.submitActionForm({ preventDefault() {}, currentTarget: completionForm() }, "complete", h.app.context.ticket);

  h.closeTicket();
  h.openTicket("T-1");
  assert.notEqual(h.app.drawerEpoch, originalEpoch);
  const reopened = reviewContext("a", NEW_TOKEN);
  reopened.ticket.title = "A reabierta en otra instancia";
  h.transport.respond(1, reopened);
  await new Promise((resolve) => setImmediate(resolve));
  h.app.drawerDirty = true;
  const preserved = h.app.context;

  const doneA = { ...ticket("A completada"), status: "done", revision: 2 };
  h.transport.respond(0, { result: doneA, state: state("a", "completion-a", [doneA]) });
  await submission;
  assert.equal(h.transport.calls.length, 2, "la completión antigua recargó la nueva instancia de A");
  assert.equal(h.app.context, preserved);
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.reviewDraft, null);
}

async function updateSaveCannotOverwriteEditedDrawerB() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = contextForTicket("T-1", "Definición A", "queued");
  h.renderDrawer();
  const editA = findElement(h.byId("drawer-body"), (element) => element.dataset.form === "edit-ticket");
  editA.formValues = new Map([
    ["title", "A editada"], ["description", "Descripción A"], ["type", "task"],
    ["priority", "normal"], ["parent_id", ""], ["profile_id", ""],
    ["depends_on", ""], ["acceptance", "Criterio A"]
  ]);
  const pending = editA.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 1);

  h.openTicket("T-2");
  const contextB = contextForTicket("T-2", "Definición B", "review", NEW_TOKEN);
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  const titleB = findElement(h.byId("drawer-body"), (element) => element.name === "title");
  titleB.value = "B editada sin guardar";
  h.app.drawerDirty = true;

  const updatedA = { ...ticket("A editada"), status: "queued", revision: 2 };
  h.transport.respond(0, { result: updatedA, state: state("a", "update-a", [updatedA, contextB.ticket]) });
  await pending;
  assert.equal(h.transport.calls.length, 2, "update_ticket A forzó una recarga de B");
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "title"), titleB);
  assert.equal(titleB.value, "B editada sin guardar");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.state.marker, "update-a");
}

async function checkpointStillRefreshesItsOriginalDrawer() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = contextForTicket("T-1", "Avance A", "in_progress");
  h.app.drawerDirty = true;
  const pending = h.submitActionForm({ preventDefault() {}, currentTarget: drawerActionForm("checkpoint") }, "checkpoint", h.app.context.ticket);
  const updatedA = { ...h.app.context.ticket, revision: 2, checkpoint: "Avance de A" };
  h.transport.respond(0, { result: updatedA, state: state("a", "checkpoint-a", [updatedA]) });
  await waitForCalls(h.transport, 2);
  assert.equal(h.transport.calls[1].url, "/api/tickets/T-1/context");
  const fresh = contextForTicket("T-1", "A refrescada", "in_progress");
  fresh.ticket.revision = 2;
  fresh.ticket.checkpoint = "Avance de A";
  h.transport.respond(1, fresh);
  await pending;
  assert.equal(h.app.context.ticket.title, "A refrescada");
  assert.equal(h.app.drawerDirty, false);
  assert.equal(h.app.state.marker, "checkpoint-a");
}

async function submitCannotOverwriteReopenedSameTicket() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = contextForTicket("T-1", "Entrega A", "in_progress");
  const pending = h.submitActionForm({ preventDefault() {}, currentTarget: drawerActionForm("submit") }, "submit", h.app.context.ticket);

  h.closeTicket();
  h.openTicket("T-1");
  const reopened = contextForTicket("T-1", "A reabierta mientras entrega", "in_progress");
  h.transport.respond(1, reopened);
  await new Promise((resolve) => setImmediate(resolve));
  const summary = findElement(h.byId("drawer-body"), (element) => element.name === "summary");
  summary.value = "Edición de la nueva instancia";
  h.app.drawerDirty = true;

  const submittedA = { ...reopened.ticket, revision: 2, status: "review" };
  h.transport.respond(0, { result: submittedA, state: state("a", "submit-a", [submittedA]) });
  await pending;
  assert.equal(h.transport.calls.length, 2, "submit antiguo recargó A reabierta");
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "summary"), summary);
  assert.equal(summary.value, "Edición de la nueva instancia");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.state.marker, "submit-a");
}

async function commentConflictCannotOverwriteEditedDrawerB() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = contextForTicket("T-1", "Comentario A", "review");
  const pending = h.submitActionForm({ preventDefault() {}, currentTarget: drawerActionForm("comment") }, "comment", h.app.context.ticket);

  h.openTicket("T-2");
  const contextB = contextForTicket("T-2", "Comentario B", "review", NEW_TOKEN);
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  const bodyB = findElement(h.byId("drawer-body"), (element) => element.name === "body");
  bodyB.value = "Comentario B sin guardar";
  h.app.drawerDirty = true;

  h.transport.respond(0, { error: "revision conflict for T-1: expected 1, current 2" }, 409);
  await pending;
  assert.equal(h.transport.calls.length, 2, "conflicto comment A inició recarga sobre B");
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "body"), bodyB);
  assert.equal(bodyB.value, "Comentario B sin guardar");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.state.marker, "initial", "un conflicto sin estado confirmado alteró el tablero");
}

async function conflictStateReloadCannotFollowNewDrawer() {
  const h = loadHarness();
  h.app.selectedId = "T-1";
  h.app.context = contextForTicket("T-1", "Comentario A", "review");
  const pending = h.submitActionForm({ preventDefault() {}, currentTarget: drawerActionForm("comment") }, "comment", h.app.context.ticket);

  h.transport.respond(0, { error: "revision conflict for T-1: expected 1, current 2" }, 409);
  await waitForCalls(h.transport, 2);
  assert.equal(h.transport.calls[1].url, "/api/state", "el conflicto no inició su recarga de estado esperada");

  h.openTicket("T-2");
  const contextB = contextForTicket("T-2", "Drawer B durante state GET", "review", NEW_TOKEN);
  h.transport.respond(2, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  const verificationB = findElement(h.byId("drawer-body"), (element) => element.name === "verification");
  const renderedContextB = h.app.context;

  const newerB = { ...contextB.ticket, revision: 2 };
  h.transport.respond(1, state("a", "conflict-refresh", [newerB]));
  await waitForCalls(h.transport, 4);
  if (h.transport.calls[3]) {
    const unexpectedRefresh = contextForTicket("T-2", "B refrescada indebidamente", "review", NEW_TOKEN);
    unexpectedRefresh.ticket.revision = 2;
    h.transport.respond(3, unexpectedRefresh);
  }
  await pending;
  assert.equal(h.transport.calls.length, 3, "la recarga de estado de A siguió con un GET de contexto para B");
  assert.equal(h.app.context, renderedContextB);
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "verification"), verificationB);
  assert.equal(h.app.state.marker, "conflict-refresh", "la recarga confirmada no actualizó el tablero");
}

async function startRunCannotOverwriteEditedDrawerB() {
  const h = loadHarness();
  const queuedA = contextForTicket("T-1", "Ejecución A", "queued");
  queuedA.ticket.ready = true;
  h.app.selectedId = "T-1";
  h.app.context = queuedA;
  h.app.state = state("a", "initial", [queuedA.ticket]);
  h.app.state.execution = {
    enabled: true,
    workers: [{ id: "worker-1", name: "Worker local", model: "fixture", effort: "low", profile_ids: [], timeout_seconds: 30 }],
    runs: []
  };
  h.renderDrawer();
  const executionForm = findElement(h.byId("drawer-body"), (element) => element.className.includes("execution-form"));
  assert.ok(executionForm, "no se renderizó el formulario real de ejecución");
  const pending = executionForm.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 1);
  assert.equal(JSON.parse(h.transport.calls[0].options.body).data.worker_id, "worker-1", "start_run leyó el worker después de deshabilitarlo");

  h.openTicket("T-2");
  const contextB = contextForTicket("T-2", "Drawer B durante start", "review", NEW_TOKEN);
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  const verificationB = findElement(h.byId("drawer-body"), (element) => element.name === "verification");
  verificationB.value = "Verificación B sin guardar";
  h.app.drawerDirty = true;

  const runningA = { ...queuedA.ticket, revision: 2, status: "in_progress", assignee: "agent:worker-1" };
  const nextState = state("a", "start-a", [runningA, contextB.ticket]);
  nextState.execution = { ...h.app.state.execution, runs: [{ id: "run-1", ticket_id: "T-1", status: "running" }] };
  h.transport.respond(0, { result: { id: "run-1" }, state: nextState });
  await pending;
  assert.equal(h.transport.calls.length, 2, "start_run A forzó una recarga de B");
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "verification"), verificationB);
  assert.equal(verificationB.value, "Verificación B sin guardar");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.app.state.marker, "start-a");
}

async function definitionLocksAfterCapturingPayloadUntilContextArrives() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Título inicial", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const form = findElement(body, (element) => element.dataset.form === "edit-ticket");
  form.formValues = definitionValues("V1 enviada");
  const originalControls = editableControls(body);

  const pending = form.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 1, "Guardar no emitió el POST");
  const sent = JSON.parse(h.transport.calls[0].options.body);
  assert.equal(sent.data.title, "V1 enviada", "FormData no se capturó antes del bloqueo");
  assert.ok(originalControls.length > 5, "el harness no encontró los controles reales del drawer");
  assert.ok(originalControls.every((control) => control.disabled), "quedaron controles editables durante el POST");
  assert.equal(new FakeFormData(form).get("title"), null, "el adaptador FormData incluyó un control ya deshabilitado");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true");

  const updated = { ...contextA.ticket, title: "V1 enviada", revision: 2 };
  h.transport.respond(0, { result: updated, state: state("a", "saved", [updated]) });
  await waitForCalls(h.transport, 2);
  assert.ok(originalControls.every((control) => control.disabled), "se habilitaron controles durante el GET de contexto");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true");

  const fresh = contextForTicket("T-1", "V1 enviada", "in_progress");
  fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  const finalTitle = findElement(body, (element) => element.name === "title");
  assert.equal(finalTitle.value, "V1 enviada");
  assert.equal(finalTitle.disabled, false);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
  assert.equal(h.app.drawerDirty, false);
}

async function checkpointLocksRealControlsAfterPayloadCapture() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Avance A", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const form = actionForm(body, "checkpoint");
  form.formValues = new Map([["checkpoint", "V1 avance"]]);
  const checkpointControl = findElement(form, (element) => element.name === "checkpoint");
  const pending = form.dispatch("submit", { preventDefault() {} });
  assert.equal(JSON.parse(h.transport.calls[0].options.body).data.checkpoint, "V1 avance");
  assert.equal(checkpointControl.disabled, true);

  const updated = { ...contextA.ticket, checkpoint: "V1 avance", revision: 2 };
  h.transport.respond(0, { result: updated, state: state("a", "checkpoint", [updated]) });
  await waitForCalls(h.transport, 2);
  assert.equal(checkpointControl.disabled, true);
  const fresh = contextForTicket("T-1", "Avance A", "in_progress");
  fresh.ticket.checkpoint = "V1 avance";
  fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  assert.equal(findElement(body, (element) => element.name === "checkpoint").value, "V1 avance");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
}

async function knownRejectionRestoresValuesAndPriorRestrictions() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Revisión heredada", "review", null);
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const completion = actionForm(body, "complete");
  const completionSubmit = findElement(completion, (element) => element.type === "submit");
  assert.equal(completionSubmit.disabled, true, "la aceptación sin token empezó habilitada");
  const comment = actionForm(body, "comment");
  const commentBody = findElement(comment, (element) => element.name === "body");
  const commentSubmit = findElement(comment, (element) => element.type === "submit");
  commentBody.value = "Texto rechazado";
  comment.formValues = new Map([["body", "Texto rechazado"]]);

  const pending = comment.dispatch("submit", { preventDefault() {} });
  assert.equal(commentBody.disabled, true);
  assert.equal(commentSubmit.disabled, true);
  h.transport.respond(0, { error: "comentario rechazado" }, 400);
  await pending;
  assert.equal(findElement(body, (element) => element.name === "body"), commentBody, "el rechazo reconstruyó el formulario");
  assert.equal(commentBody.value, "Texto rechazado");
  assert.equal(commentBody.disabled, false);
  assert.equal(commentSubmit.disabled, false);
  assert.equal(completionSubmit.disabled, true, "el rechazo habilitó una aceptación inválida");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
}

async function revisionConflictKeepsRejectedFormThroughStateReload() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Comentario A", "review", NEW_TOKEN);
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const comment = actionForm(body, "comment");
  const commentBody = findElement(comment, (element) => element.name === "body");
  commentBody.value = "Comentario V1";
  comment.formValues = new Map([["body", "Comentario V1"]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });

  h.transport.respond(0, { error: "revision conflict for T-1: expected 1, current 2" }, 409);
  await waitForCalls(h.transport, 2);
  assert.equal(h.transport.calls[1].url, "/api/state");
  assert.equal(commentBody.disabled, true, "el conflicto habilitó el formulario antes del reload de estado");
  const newer = { ...contextA.ticket, revision: 2 };
  h.transport.respond(1, state("a", "conflict", [newer]));
  await pending;
  assert.equal(findElement(body, (element) => element.name === "body"), commentBody);
  assert.equal(commentBody.value, "Comentario V1");
  assert.equal(commentBody.disabled, false);
  assert.equal(h.app.context.ticket.revision, 1, "el reload sustituyó el contexto rechazado");
  assert.equal(h.app.state.tickets[0].revision, 2, "el tablero no adoptó la revisión confirmada");
  assert.equal(h.app.drawerDirty, true);
}

async function completionConflictStaysLockedUntilFreshContext() {
  const h = loadHarness();
  const contextA = reviewContext("a", OLD_TOKEN);
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const complete = actionForm(body, "complete");
  complete.formValues = new Map([
    ["verification", "Verificación V1"],
    ["accepted_criteria", ["Criterio A", "Criterio B"]]
  ]);
  const oldVerification = findElement(complete, (element) => element.name === "verification");
  const pending = complete.dispatch("submit", { preventDefault() {} });
  assert.equal(oldVerification.disabled, true);
  h.transport.respond(0, { error: "acceptance context changed; reread ticket context before completing" }, 409);
  await waitForCalls(h.transport, 2);
  assert.equal(oldVerification.disabled, true, "el 409 habilitó la revisión durante su GET");
  const fresh = reviewContext("a", NEW_TOKEN);
  fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;

  const currentComplete = actionForm(body, "complete");
  const confirmation = findElement(currentComplete, (element) => element.name === "confirm_updated_context");
  const submit = findElement(currentComplete, (element) => element.type === "submit");
  assert.ok(confirmation, "el contexto nuevo no exige reconfirmación");
  assert.equal(submit.disabled, true, "la aceptación se habilitó antes de reconfirmar");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
}

async function confirmedPostFailedContextAllowsOnlyReadRetry() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Padre", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const child = actionForm(body, "child");
  child.formValues = new Map([
    ["title", "Hija única"], ["description", "Descripción"], ["acceptance", "Criterio hija"]
  ]);
  const childTitle = findElement(child, (element) => element.name === "title");
  const childSubmit = findElement(child, (element) => element.type === "submit");
  childTitle.value = "Hija única";
  const pending = child.dispatch("submit", { preventDefault() {} });
  const created = { ...ticket("Hija única"), id: "T-2", parent_id: "T-1", status: "queued" };
  h.transport.respond(0, { result: created, state: state("a", "child-created", [contextA.ticket, created]) });
  await waitForCalls(h.transport, 2);
  h.transport.calls[1].reject(new Error("context offline"));
  await pending;

  assert.equal(childTitle.value, "Hija única", "el control real no conservó el texto del formulario");
  assert.equal(childTitle.disabled, false, "el texto confirmado no quedó disponible para copiar");
  assert.equal(childTitle.readOnly, true, "el formulario confirmado permite editar antes de leer contexto");
  assert.equal(childSubmit.disabled, true, "la hija confirmada se puede duplicar");
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null, "la recuperación ociosa quedó marcada como ocupada");
  const notice = findElement(body, (element) => element.dataset.drawerMutationNotice === "true");
  assert.match(treeText(notice), /Acción guardada/);
  const retry = findElement(notice, (element) => element.tagName === "BUTTON");
  const retrying = retry.dispatch("click");
  assert.equal(h.transport.calls.length, 3);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true", "el GET de retry no marcó busy");
  assert.equal(h.transport.calls[2].options.method, undefined, "el retry repitió la mutación");
  h.transport.calls[2].reject(new Error("still offline"));
  await retrying;
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null, "un retry fallido dejó busy activo");
  assert.equal(retry.disabled, false, "un retry de lectura fallido no se puede volver a intentar");
  const retryingAgain = retry.dispatch("click");
  assert.equal(h.transport.calls.length, 4);
  const fresh = contextForTicket("T-1", "Padre actualizado", "in_progress");
  h.transport.respond(3, fresh);
  await retryingAgain;
  assert.equal(h.transport.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
  assert.equal(findElement(body, (element) => element.name === "title").disabled, false);
}

async function uncertainPostRequiresReadWithoutClaimingOutcome() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Título inicial", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const edit = findElement(body, (element) => element.dataset.form === "edit-ticket");
  edit.formValues = definitionValues("Resultado incierto");
  const titleControl = findElement(edit, (element) => element.name === "title");
  titleControl.value = "Resultado incierto";
  const pending = edit.dispatch("submit", { preventDefault() {} });
  h.transport.calls[0].reject(new Error("network lost"));
  await pending;

  const notice = findElement(body, (element) => element.dataset.drawerMutationNotice === "true");
  assert.match(treeText(notice), /Resultado sin confirmar/);
  assert.equal(titleControl.value, "Resultado incierto");
  assert.equal(titleControl.readOnly, true);
  assert.equal(findElement(edit, (element) => element.type === "submit").disabled, true);
  assert.equal(h.transport.calls.length, 1, "el fallo de red provocó un retry automático");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null, "la recuperación incierta ociosa quedó marcada como ocupada");

  const retry = findElement(notice, (element) => element.tagName === "BUTTON");
  const retrying = retry.dispatch("click");
  assert.equal(h.transport.calls.length, 2);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true");
  h.transport.respond(1, contextA);
  await retrying;
  assert.equal(h.transport.calls.filter((call) => call.options.method === "POST").length, 1);
  assert.match(treeText(h.byId("toast-region")), /sigue con resultado incierto/);
  const warning = findElement(h.byId("drawer-body"), (element) => element.dataset.uncertainMutation === "true");
  assert.match(treeText(warning), /auditoría antes de repetirla/);
  const poll = h.loadState({ quiet: true });
  assert.equal(h.transport.calls.length, 3);
  const newer = { ...contextA.ticket, revision: 2, title: "Contexto posterior" };
  h.transport.respond(2, state("a", "later-poll", [newer]));
  await waitForCalls(h.transport, 4);
  const laterContext = contextForTicket("T-1", "Contexto posterior", "in_progress");
  laterContext.ticket.revision = 2;
  h.transport.respond(3, laterContext);
  await poll;
  const warningAfterPoll = findElement(h.byId("drawer-body"), (element) => element.dataset.uncertainMutation === "true");
  assert.match(treeText(warningAfterPoll), /resultado incierto/);
  assert.match(treeText(warningAfterPoll), /lectura posterior no demuestra/);
  assert.equal(h.transport.calls.filter((call) => call.options.method === "POST").length, 1);
}

async function serverErrorAfterPostIsAlsoUncertain() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Título inicial", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const edit = findElement(body, (element) => element.dataset.form === "edit-ticket");
  edit.formValues = definitionValues("Posible commit con 500");
  const titleControl = findElement(edit, (element) => element.name === "title");
  titleControl.value = "Posible commit con 500";
  const pending = edit.dispatch("submit", { preventDefault() {} });
  h.transport.respond(0, { error: "falló la captura de estado posterior" }, 500);
  await pending;

  const notice = findElement(body, (element) => element.dataset.drawerMutationNotice === "true");
  assert.match(treeText(notice), /Resultado sin confirmar/);
  assert.equal(titleControl.value, "Posible commit con 500");
  assert.equal(titleControl.readOnly, true);
  assert.equal(findElement(edit, (element) => element.type === "submit").disabled, true);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
  assert.equal(h.transport.calls.length, 1, "el 500 provocó un retry automático");
}

async function pendingMutationDoesNotLockNewDrawerInstance() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "A", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const checkpoint = actionForm(h.byId("drawer-body"), "checkpoint");
  checkpoint.formValues = new Map([["checkpoint", "Pendiente A"]]);
  const pending = checkpoint.dispatch("submit", { preventDefault() {} });
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true");

  h.openTicket("T-2");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null, "B heredó aria-busy de A");
  const contextB = contextForTicket("T-2", "B", "review", NEW_TOKEN);
  h.transport.respond(1, contextB);
  await new Promise((resolve) => setImmediate(resolve));
  const verificationB = findElement(h.byId("drawer-body"), (element) => element.name === "verification");
  assert.equal(verificationB.disabled, false, "B heredó controles bloqueados de A");
  verificationB.value = "Edición B";
  h.app.drawerDirty = true;

  const updatedA = { ...contextA.ticket, checkpoint: "Pendiente A", revision: 2 };
  h.transport.respond(0, { result: updatedA, state: state("a", "checkpoint-a", [updatedA, contextB.ticket]) });
  await pending;
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "verification"), verificationB);
  assert.equal(verificationB.value, "Edición B");
  assert.equal(verificationB.disabled, false);
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
}

async function pendingMutationDoesNotLockReopenedSameTicket() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "A inicial", "in_progress");
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.renderDrawer();
  const originalForm = findElement(h.byId("drawer-body"), (element) => element.dataset.form === "edit-ticket");
  originalForm.formValues = definitionValues("A V1");
  const pending = originalForm.dispatch("submit", { preventDefault() {} });
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), "true");

  h.closeTicket();
  h.openTicket("T-1");
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null, "A reabierta heredó aria-busy");
  const reopened = contextForTicket("T-1", "A reabierta", "in_progress");
  h.transport.respond(1, reopened);
  await new Promise((resolve) => setImmediate(resolve));
  const reopenedTitle = findElement(h.byId("drawer-body"), (element) => element.name === "title");
  assert.equal(reopenedTitle.disabled, false);
  reopenedTitle.value = "V2 de la nueva instancia";
  h.app.drawerDirty = true;

  const updated = { ...contextA.ticket, title: "A V1", revision: 2 };
  h.transport.respond(0, { result: updated, state: state("a", "saved-old-a", [updated]) });
  await pending;
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "title"), reopenedTitle);
  assert.equal(reopenedTitle.value, "V2 de la nueva instancia");
  assert.equal(reopenedTitle.disabled, false);
  assert.equal(h.app.drawerDirty, true);
  assert.equal(h.byId("ticket-drawer").getAttribute("aria-busy"), null);
}

async function previouslyDisabledExecutionControlsStayDisabledAfterError() {
  const h = loadHarness();
  const contextA = contextForTicket("T-1", "Lista con run activo", "queued");
  contextA.ticket.ready = true;
  h.app.selectedId = "T-1";
  h.app.context = contextA;
  h.app.state = state("a", "initial", [contextA.ticket]);
  h.app.state.execution = {
    enabled: true,
    workers: [{ id: "worker-1", name: "Worker", model: "fixture", effort: "low", profile_ids: [] }],
    runs: [{ id: "run-active", ticket_id: "T-9", status: "running" }]
  };
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const execution = findElement(body, (element) => element.className.includes("execution-form"));
  const start = findElement(execution, (element) => element.type === "submit");
  const worker = findElement(execution, (element) => element.name === "worker_id");
  assert.equal(start.disabled, true);
  assert.equal(worker.disabled, true);
  const comment = actionForm(body, "comment");
  comment.formValues = new Map([["body", "Rechazo"]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });
  h.transport.respond(0, { error: "rechazado" }, 400);
  await pending;
  assert.equal(start.disabled, true, "se habilitó start_run previamente bloqueado");
  assert.equal(worker.disabled, true, "se habilitó worker previamente bloqueado");
}

function setControl(form, name, value, eventName = "input") {
  const control = findElement(form, (element) => element.name === name);
  assert.ok(control, `No se encontró el control ${name}`);
  control.value = value;
  control.dispatch(eventName);
  return control;
}

function renderedHarness(status = "in_progress") {
  const h = loadHarness();
  const ctx = contextForTicket("T-1", "Original", status);
  h.app.selectedId = "T-1";
  h.app.context = ctx;
  h.app.state = state("a", "initial", [ctx.ticket]);
  h.renderDrawer();
  return { h, ctx, body: h.byId("drawer-body") };
}

async function cancelCrossFormDiscardKeepsEveryDraft() {
  const { h, body } = renderedHarness();
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const comment = actionForm(body, "comment");
  const title = setControl(definition, "title", "Borrador V2");
  const commentBody = setControl(comment, "body", "Comentario pendiente");
  comment.formValues = new Map([["body", commentBody.value]]);
  h.setConfirmResponse(false);
  const cancelled = comment.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 0);
  assert.equal(title.value, "Borrador V2");
  assert.equal(commentBody.value, "Comentario pendiente");
  assert.equal(h.app.drawerDirty, true);
  assert.match(h.confirmations[0], /Definición/);
  assert.match(h.confirmations[0], /descartará esos borradores/);
  await cancelled;
}

async function consentDiscardsOtherDraftOnlyAfterFreshContext() {
  const { h, ctx, body } = renderedHarness();
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const comment = actionForm(body, "comment");
  const oldTitle = setControl(definition, "title", "Borrador V2");
  const commentBody = setControl(comment, "body", "Comentario enviado");
  comment.formValues = new Map([["body", commentBody.value]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });
  assert.equal(JSON.parse(h.transport.calls[0].options.body).action, "add_comment");
  const saved = { ...ctx.ticket, revision: 2 };
  h.transport.respond(0, { result: saved, state: state("a", "saved", [saved]) });
  await waitForCalls(h.transport, 2);
  assert.equal(oldTitle.value, "Borrador V2", "el POST por sí solo descartó el borrador ajeno");
  const fresh = contextForTicket("T-1", "Original", "in_progress"); fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  const newTitle = findElement(h.byId("drawer-body"), (element) => element.name === "title");
  assert.notEqual(newTitle, oldTitle);
  assert.equal(newTitle.value, "Original");
  assert.equal(h.app.drawerDirty, false);
}

async function ownSaveAndRevertedDraftDoNotPrompt() {
  const { h, ctx, body } = renderedHarness();
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const title = setControl(definition, "title", "Temporal");
  title.value = "Original"; await title.dispatch("input");
  assert.equal(h.app.drawerDirty, false);
  title.value = "Guardado"; await title.dispatch("input");
  definition.formValues = definitionValues("Guardado");
  const pending = definition.dispatch("submit", { preventDefault() {} });
  assert.equal(h.confirmations.length, 0);
  const saved = { ...ctx.ticket, title: "Guardado", revision: 2 };
  h.transport.respond(0, { result: saved, state: state("a", "saved", [saved]) });
  await waitForCalls(h.transport, 2);
  const fresh = contextForTicket("T-1", "Guardado", "in_progress"); fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
}

async function knownRejectionKeepsConsentedSemanticReview() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.app.reviewDraft = { workspaceId: "a", workspaceEpoch: 1, drawerEpoch: 0, ticketId: "T-1", verification: "V", acceptedCriteria: ["Criterio A"], needsConfirmation: true, refreshRequired: false };
  h.renderDrawer();
  const comment = actionForm(h.byId("drawer-body"), "comment");
  const bodyControl = setControl(comment, "body", "Comentario");
  comment.formValues = new Map([["body", bodyControl.value]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });
  assert.match(h.confirmations[0], /Revisión pendiente/);
  h.transport.respond(0, { error: "rechazado" }, 400);
  await pending;
  assert.equal(bodyControl.value, "Comentario");
  assert.equal(h.app.reviewDraft.needsConfirmation, true);
  assert.equal(h.app.drawerDirty, true);
}

async function completionConflictUsesPriorDiscardConsent() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  setControl(findElement(body, (element) => element.dataset.form === "edit-ticket"), "title", "Definición sin guardar");
  const complete = actionForm(body, "complete");
  complete.formValues = new Map([["verification", "Verificado"], ["accepted_criteria", ["Criterio A"]]]);
  const pending = complete.dispatch("submit", { preventDefault() {} });
  assert.match(h.confirmations[0], /conflicto al completar/);
  h.transport.respond(0, { error: "acceptance context changed; reread ticket context before completing" }, 409);
  await waitForCalls(h.transport, 2);
  const fresh = reviewContext("a", NEW_TOKEN); fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  assert.equal(h.app.reviewDraft.needsConfirmation, true);
  assert.equal(findElement(h.byId("drawer-body"), (element) => element.name === "title").value, "Revisión");
}

async function startRunWarnsThatPersistedDefinitionIsUsed() {
  const { h, ctx, body } = renderedHarness("queued");
  ctx.ticket.ready = true;
  h.app.state.tickets[0].ready = true;
  h.app.state.execution = { enabled: true, workers: [{ id: "w", name: "Worker", model: "fixture", effort: "low", profile_ids: [] }], runs: [] };
  h.renderDrawer();
  const currentBody = h.byId("drawer-body");
  setControl(findElement(currentBody, (element) => element.dataset.form === "edit-ticket"), "description", "Sólo en pantalla");
  const execution = findElement(currentBody, (element) => element.className.includes("execution-form"));
  h.setConfirmResponse(false);
  const cancelled = execution.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 0);
  assert.equal(findElement(currentBody, (element) => element.name === "description").value, "Sólo en pantalla");
  assert.match(h.confirmations[0], /definición ya guardada/);
  await cancelled;
}

async function malformedContextCannotDiscardConsentedDraft() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.app.reviewDraft = { workspaceId: "a", workspaceEpoch: 1, drawerEpoch: 0, ticketId: "T-1", verification: "V", acceptedCriteria: ["Criterio A"], needsConfirmation: true, refreshRequired: false };
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const comment = actionForm(body, "comment");
  const title = setControl(definition, "title", "Borrador conservado");
  const commentBody = setControl(comment, "body", "Comentario");
  comment.formValues = new Map([["body", commentBody.value]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });
  const saved = { ...ctx.ticket, revision: 2 };
  h.transport.respond(0, { result: saved, state: state("a", "saved", [saved]) });
  await waitForCalls(h.transport, 2);
  h.transport.respond(1, { workspace: { id: "a" }, ticket: { id: "OTRA" } });
  await pending;
  assert.equal(title.value, "Borrador conservado");
  assert.ok(h.app.reviewDraft, "el contexto malformado borró la revisión semántica");
  assert.equal(h.app.drawerDirty, true);
  assert.ok(h.app.drawerMutation, "el 200 malformado no exigió reintentar la lectura");
}

async function failedCompletionRefreshKeepsOtherDraftUntilRetrySucceeds() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const title = setControl(definition, "title", "Definición V2");
  const complete = actionForm(body, "complete");
  complete.formValues = new Map([["verification", "Verificado"], ["accepted_criteria", ["Criterio A"]]]);
  const pending = complete.dispatch("submit", { preventDefault() {} });
  h.transport.respond(0, { error: "acceptance context changed; reread ticket context before completing" }, 409);
  await waitForCalls(h.transport, 2);
  h.transport.calls[1].reject(new Error("sin conexión"));
  await pending;
  assert.equal(findElement(body, (element) => element.name === "title"), title);
  assert.equal(title.value, "Definición V2");
  assert.equal(h.app.reviewDraft.refreshRequired, true);
  const retryButton = findElement(body, (element) => element.textContent === "Reintentar carga de contexto");
  assert.ok(retryButton);
  const retry = retryButton.dispatch("click");
  await waitForCalls(h.transport, 3);
  assert.equal(title.disabled, true, "otro borrador quedó editable durante el GET de retry");
  assert.equal(h.transport.calls.filter((call) => call.url === "/api/actions").length, 1);
  const fresh = reviewContext("a", NEW_TOKEN); fresh.ticket.revision = 2;
  h.transport.respond(2, fresh);
  await retry;
  assert.notEqual(findElement(body, (element) => element.name === "title"), title);
  assert.equal(h.app.reviewDraft.needsConfirmation, true);
  assert.match(treeText(body), /He revisado el contexto actualizado/);
}

async function definitionSaveWithCommentDraftRequiresConsent() {
  const { h, ctx, body } = renderedHarness();
  const definition = findElement(body, (element) => element.dataset.form === "edit-ticket");
  const comment = actionForm(body, "comment");
  setControl(definition, "title", "Definición guardada");
  definition.formValues = definitionValues("Definición guardada");
  const commentBody = setControl(comment, "body", "Comentario no enviado");
  comment.formValues = new Map([["body", commentBody.value]]);
  h.setConfirmResponse(false);
  const cancelled = definition.dispatch("submit", { preventDefault() {} });
  assert.equal(h.transport.calls.length, 0);
  assert.equal(commentBody.value, "Comentario no enviado");
  await cancelled;
  h.setConfirmResponse(true);
  const pending = definition.dispatch("submit", { preventDefault() {} });
  const envelope = JSON.parse(h.transport.calls[0].options.body);
  assert.equal(envelope.action, "update_ticket");
  assert.equal(envelope.data.title, "Definición guardada");
  assert.equal(Object.prototype.hasOwnProperty.call(envelope.data, "body"), false);
  const saved = { ...ctx.ticket, title: "Definición guardada", revision: 2 };
  h.transport.respond(0, { result: saved, state: state("a", "saved", [saved]) });
  await waitForCalls(h.transport, 2);
  const fresh = contextForTicket("T-1", "Definición guardada", "in_progress"); fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  assert.equal(h.transport.calls.filter((call) => call.url === "/api/actions").length, 1);
}

async function checkboxDraftPromptsButDisabledControlsDoNot() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.renderDrawer();
  const body = h.byId("drawer-body");
  const complete = actionForm(body, "complete");
  const criterion = findElement(complete, (element) => element.name === "accepted_criteria");
  criterion.checked = true; await criterion.dispatch("change");
  const comment = actionForm(body, "comment");
  const commentBody = setControl(comment, "body", "Comentario");
  comment.formValues = new Map([["body", commentBody.value]]);
  h.setConfirmResponse(false);
  const cancelled = comment.dispatch("submit", { preventDefault() {} });
  assert.match(h.confirmations[0], /Revisar y cerrar/);
  assert.equal(h.transport.calls.length, 0);
  assert.equal(criterion.checked, true);
  await cancelled;

  const done = contextForTicket("T-1", "Cerrada", "done");
  h.app.context = done; h.app.state = state("a", "done", [done.ticket]); h.renderDrawer();
  const doneBody = h.byId("drawer-body");
  const disabledTitle = findElement(doneBody, (element) => element.name === "title");
  assert.equal(disabledTitle.disabled, true);
  disabledTitle.value = "Cambio programático ignorado";
  const doneComment = actionForm(doneBody, "comment");
  const doneCommentBody = setControl(doneComment, "body", "Comentario válido");
  doneComment.formValues = new Map([["body", doneCommentBody.value]]);
  h.setConfirmResponse(true);
  const pending = doneComment.dispatch("submit", { preventDefault() {} });
  assert.equal(h.confirmations.length, 1, "un control inicialmente deshabilitado produjo otro aviso");
  h.transport.respond(0, { error: "rechazado" }, 400);
  await pending;
}

async function semanticReviewDraftClearsOnlyAfterSuccessfulContext() {
  const h = loadHarness();
  const ctx = reviewContext("a");
  h.app.selectedId = "T-1"; h.app.context = ctx; h.app.state = state("a", "initial", [ctx.ticket]);
  h.app.reviewDraft = { workspaceId: "a", workspaceEpoch: 1, drawerEpoch: 0, ticketId: "T-1", verification: "V", acceptedCriteria: ["Criterio A"], needsConfirmation: true, refreshRequired: false };
  h.renderDrawer();
  const comment = actionForm(h.byId("drawer-body"), "comment");
  const commentBody = setControl(comment, "body", "Comentario");
  comment.formValues = new Map([["body", commentBody.value]]);
  const pending = comment.dispatch("submit", { preventDefault() {} });
  const saved = { ...ctx.ticket, revision: 2 };
  h.transport.respond(0, { result: saved, state: state("a", "saved", [saved]) });
  await waitForCalls(h.transport, 2);
  assert.ok(h.app.reviewDraft, "el POST borró el borrador de revisión antes del GET");
  const fresh = reviewContext("a", NEW_TOKEN); fresh.ticket.revision = 2;
  h.transport.respond(1, fresh);
  await pending;
  assert.equal(h.app.reviewDraft, null);
  assert.equal(h.app.drawerDirty, false);
}

const tests = [
  ["GET antiguo no sobrescribe una mutación", oldGetCannotOverwriteMutation],
  ["cerrar y reabrir descarta contexto antiguo", closeAndReopenRejectsOldContext],
  ["cambiar de proyecto descarta respuestas antiguas", workspaceChangeRejectsOldResponses],
  ["mutación captura cabecera y bloquea cambio", mutationCapturesHeaderAndBlocksSwitch],
  ["la aceptación usa el token presentado", completionUsesPresentedToken],
  ["el conflicto API conserva borrador y carga contexto", staleApiConflictPreservesDraftAndLoadsFreshContext],
  ["el contexto renovado exige reconfirmación", refreshedContextRequiresExplicitConfirmation],
  ["cambiar proyecto descarta recarga y borrador de conflicto", workspaceChangeDiscardsConflictRefreshAndDraft],
  ["un contexto heredado sin token no se puede aceptar", legacyContextCannotBeAcceptedWithoutToken],
  ["un 409 ajeno al contexto conserva el formulario", unrelated409DoesNotResetReview],
  ["una recarga fallida de contexto se puede reintentar", failedConflictRefreshCanBeRetried],
  ["la revisión muestra relaciones y source checks cubiertos", renderedReviewShowsCoveredMaterial],
  ["el éxito de A no sobrescribe el drawer B", completionSuccessCannotOverwriteAnotherDrawer],
  ["el 409 de A no instala borrador en B", completion409CannotInstallDraftInAnotherDrawer],
  ["una completión antigua no sobrescribe A reabierta", completionCannotOverwriteReopenedSameTicket],
  ["guardar A no sobrescribe controles editados de B", updateSaveCannotOverwriteEditedDrawerB],
  ["checkpoint actual refresca su drawer original", checkpointStillRefreshesItsOriginalDrawer],
  ["submit antiguo no sobrescribe A reabierta", submitCannotOverwriteReopenedSameTicket],
  ["conflicto comment A no sobrescribe controles de B", commentConflictCannotOverwriteEditedDrawerB],
  ["recarga de conflicto A no sigue al drawer B", conflictStateReloadCannotFollowNewDrawer],
  ["start_run A no sobrescribe controles de B", startRunCannotOverwriteEditedDrawerB],
  ["guardar bloquea tras capturar payload hasta recibir contexto", definitionLocksAfterCapturingPayloadUntilContextArrives],
  ["checkpoint bloquea controles reales tras capturar payload", checkpointLocksRealControlsAfterPayloadCapture],
  ["rechazo conocido restaura valores y restricciones previas", knownRejectionRestoresValuesAndPriorRestrictions],
  ["conflicto conserva formulario durante reload de estado", revisionConflictKeepsRejectedFormThroughStateReload],
  ["409 de aceptación bloquea hasta contexto nuevo", completionConflictStaysLockedUntilFreshContext],
  ["POST confirmado y GET fallido permite sólo retry de lectura", confirmedPostFailedContextAllowsOnlyReadRetry],
  ["POST incierto exige lectura sin afirmar resultado", uncertainPostRequiresReadWithoutClaimingOutcome],
  ["un error 500 tras el POST también queda incierto", serverErrorAfterPostIsAlsoUncertain],
  ["mutación pendiente no bloquea nueva instancia de drawer", pendingMutationDoesNotLockNewDrawerInstance],
  ["mutación pendiente no bloquea el mismo ticket reabierto", pendingMutationDoesNotLockReopenedSameTicket],
  ["error conserva controles de ejecución previamente bloqueados", previouslyDisabledExecutionControlsStayDisabledAfterError],
  ["cancelar conserva borradores cruzados", cancelCrossFormDiscardKeepsEveryDraft],
  ["el descarte consentido espera contexto nuevo", consentDiscardsOtherDraftOnlyAfterFreshContext],
  ["guardar el propio formulario y revertir no preguntan", ownSaveAndRevertedDraftDoNotPrompt],
  ["un rechazo conocido conserva la revisión semántica", knownRejectionKeepsConsentedSemanticReview],
  ["el 409 de aceptación usa consentimiento previo", completionConflictUsesPriorDiscardConsent],
  ["start_run advierte sobre definición persistida", startRunWarnsThatPersistedDefinitionIsUsed],
  ["un contexto malformado no descarta borradores", malformedContextCannotDiscardConsentedDraft],
  ["el 409 con GET fallido conserva otro borrador hasta retry", failedCompletionRefreshKeepsOtherDraftUntilRetrySucceeds],
  ["guardar definición con comentario exige consentimiento", definitionSaveWithCommentDraftRequiresConsent],
  ["checkbox cuenta y controles deshabilitados no", checkboxDraftPromptsButDisabledControlsDoNot],
  ["la revisión semántica sólo se descarta tras GET válido", semanticReviewDraftClearsOnlyAfterSuccessfulContext]
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
