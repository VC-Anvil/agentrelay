(() => {
  "use strict";

  const STATUS = {
    backlog: "Propuesta",
    queued: "En cola",
    in_progress: "En curso",
    blocked: "Bloqueada",
    review: "En revisión",
    done: "Hecha",
    cancelled: "Cancelada"
  };
  const PRIORITY = { urgent: "Urgente", high: "Alta", normal: "Normal", low: "Baja" };
  const TYPE = { objective: "Objetivo", task: "Tarea", bug: "Error", research: "Investigación", review: "Revisión", help: "Ayuda" };
  const ACTION = {
    create_plan: "Plan importado",
    create_plan_ticket: "Propuesta del plan creada",
    create_ticket: "Tarea creada",
    update_ticket: "Tarea actualizada",
    transition: "Estado cambiado",
    claim_ticket: "Tarea tomada",
    checkpoint: "Avance registrado",
    submit_ticket: "Enviada a revisión",
    complete_ticket: "Tarea completada",
    request_help: "Ayuda solicitada",
    split_ticket: "Tarea dividida",
    add_comment: "Comentario añadido",
    create_profile: "Perfil creado",
    update_profile: "Perfil actualizado",
    start_run: "Ejecución iniciada",
    cancel_run: "Ejecución cancelada"
  };
  const RUN_STATUS = {
    running: "En ejecución",
    submitted: "En revisión",
    help_requested: "Ayuda solicitada",
    split: "Dividida",
    blocked: "Bloqueada",
    failed: "Fallida",
    cancelled: "Cancelada",
    interrupted: "Interrumpida",
    conflict: "Conflicto"
  };
  const FIELD = {
    title: "título", description: "descripción", type: "tipo", status: "estado",
    priority: "prioridad", parent_id: "tarea padre", depends_on: "dependencias",
    profile_id: "perfil recomendado", acceptance: "aceptación", checkpoint: "avance",
    evidence: "evidencia", assignee: "responsable", actual_model: "modelo usado",
    actual_effort: "esfuerzo usado", blocked_reason: "motivo de bloqueo"
  };
  const COLUMNS = ["backlog", "queued", "in_progress", "blocked", "review", "done"];
  const WORKSPACE_SESSION_KEY = "agentrelay-workspace-id";
  class ApiError extends Error {
    constructor(message, status) {
      super(message);
      this.name = "ApiError";
      this.status = status;
    }
  }
  const app = {
    state: null,
    workspaces: [],
    workspaceId: null,
    workspaceEpoch: 0,
    dataEpoch: 0,
    contextRequest: 0,
    legacyWorkspace: false,
    section: "board",
    display: localStorage.getItem("agentrelay-view") || "board",
    selectedId: null,
    context: null,
    reviewDraft: null,
    drawerEpoch: 0,
    drawerDirty: false,
    dialogDirty: false,
    loadingEpoch: null,
    mutationCount: 0
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const node = (tag, className, text) => {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  };
  const clear = (element) => element.replaceChildren();
  const option = (value, label) => {
    const item = document.createElement("option");
    item.value = value;
    item.textContent = label;
    return item;
  };
  const values = (text, separator = /[\n,]/) => String(text || "").split(separator).map((part) => part.trim()).filter(Boolean);
  const initials = (name) => String(name || "?").split(/\s+/).slice(0, 2).map((word) => word[0]).join("").toUpperCase();
  const fileSlug = (value) => String(value || "proyecto").normalize("NFD").replace(/[\u0300-\u036f]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "") || "proyecto";
  const activeWorkspace = () => app.workspaces.find((workspace) => workspace.id === app.workspaceId) || app.state?.workspace || null;
  const captureWorkspace = () => ({ id: app.workspaceId, epoch: app.workspaceEpoch, legacy: app.legacyWorkspace });
  const isCurrentWorkspace = (scope) => Boolean(scope && scope.epoch === app.workspaceEpoch && scope.id === app.workspaceId && scope.legacy === app.legacyWorkspace);
  const captureDrawer = (ticketId = app.selectedId) => ({ ...captureWorkspace(), ticketId, drawerEpoch: app.drawerEpoch });
  const isCurrentDrawer = (scope) => Boolean(scope && isCurrentWorkspace(scope) && scope.ticketId === app.selectedId && scope.drawerEpoch === app.drawerEpoch);
  const hasDirtyEdits = () => app.drawerDirty || app.dialogDirty;
  const storedWorkspace = () => {
    try { return sessionStorage.getItem(WORKSPACE_SESSION_KEY); } catch (_) { return null; }
  };
  const rememberWorkspace = (id) => {
    try { sessionStorage.setItem(WORKSPACE_SESSION_KEY, id); } catch (_) { /* storage may be unavailable */ }
  };
  // Keep the revision represented by the open form. Background polling may refresh
  // the board, but must not silently turn a stale edit into a last-write-wins edit.
  const currentTicket = () => app.context?.ticket || app.state?.tickets?.find((ticket) => ticket.id === app.selectedId) || null;
  const ACCEPTANCE_CONTEXT_TOKEN = /^sha256:[0-9a-f]{64}$/;
  const ACCEPTANCE_CONTEXT_CHANGED = "acceptance context changed; reread ticket context before completing";
  const acceptanceContextToken = (context = app.context) => {
    const acceptanceContext = context?.acceptance_context;
    if (context?.ticket?.status !== "review" || acceptanceContext?.schema_version !== 1) return null;
    return typeof acceptanceContext.token === "string" && ACCEPTANCE_CONTEXT_TOKEN.test(acceptanceContext.token) ? acceptanceContext.token : null;
  };
  const reviewDraftFor = (ticket) => {
    const draft = app.reviewDraft;
    return draft && ticket && draft.workspaceId === app.workspaceId && draft.workspaceEpoch === app.workspaceEpoch && draft.drawerEpoch === app.drawerEpoch && draft.ticketId === ticket.id ? draft : null;
  };
  const acceptanceRefreshConflict = (error) => Boolean(error?.status === 409 && (
    error.message === ACCEPTANCE_CONTEXT_CHANGED
    || /^revision conflict for .+: expected [0-9]+, current [0-9]+$/.test(error.message)
  ));
  const buildCompletionPayload = (ticket, { verification, acceptedCriteria, acceptanceToken, confirmed = false }) => {
    if (!acceptanceToken || !ACCEPTANCE_CONTEXT_TOKEN.test(acceptanceToken)) {
      throw new Error("Este contexto no incluye la huella de aceptación requerida. Actualiza el servicio y vuelve a cargar la tarea antes de revisarla.");
    }
    const draft = reviewDraftFor(ticket);
    if (draft?.needsConfirmation && !confirmed) {
      throw new Error("Revisa el contexto actualizado y confirma de nuevo antes de completar la tarea.");
    }
    return {
      id: ticket.id,
      expected_revision: ticket.revision,
      expected_acceptance_context_token: acceptanceToken,
      verification,
      accepted_criteria: acceptedCriteria
    };
  };
  const profileById = (id) => app.state?.profiles?.find((profile) => profile.id === id) || null;
  const formatDate = (value) => {
    if (!value) return "Sin fecha";
    const date = new Date(value);
    return Number.isNaN(date.getTime()) ? String(value) : new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(date);
  };
  const shortValue = (value, key) => {
    if (value === null || value === undefined || value === "") return "ninguno";
    if (key === "status") return STATUS[value] || value;
    if (key === "priority") return PRIORITY[value] || value;
    if (key === "type") return TYPE[value] || value;
    if (Array.isArray(value)) return `${value.length} elemento${value.length === 1 ? "" : "s"}`;
    if (typeof value === "object") return "actualizado";
    const text = String(value);
    return text.length > 70 ? `${text.slice(0, 67)}…` : text;
  };
  const describeDetails = (details, action) => {
    if (!details) return "Sin detalles adicionales";
    if (typeof details === "string") return details;
    if (details.before && details.after && typeof details.before === "object" && typeof details.after === "object") {
      const ignored = new Set(["updated_at", "created_at", "revision", "ready", "blockers"]);
      const changed = Object.keys(details.after).filter((key) => !ignored.has(key) && JSON.stringify(details.before[key]) !== JSON.stringify(details.after[key]));
      if (changed.length) {
        return changed.slice(0, 5).map((key) => `${FIELD[key] || key}: ${shortValue(details.before[key], key)} → ${shortValue(details.after[key], key)}`).join(" · ") + (changed.length > 5 ? ` · +${changed.length - 5} cambios` : "");
      }
    }
    if (details.after && typeof details.after === "object") {
      const after = details.after;
      if (after.title) return `${after.title}${after.status ? ` · ${STATUS[after.status] || after.status}` : ""}`;
    }
    for (const key of ["body", "summary", "verification", "checkpoint", "reason", "title"]) {
      if (typeof details[key] === "string" && details[key]) return shortValue(details[key], key);
    }
    if (Array.isArray(details.fields) && details.fields.length) return `Campos: ${details.fields.map((key) => FIELD[key] || key).join(", ")}`;
    const entries = Object.entries(details).filter(([, value]) => value !== null && value !== "" && value !== undefined && typeof value !== "object");
    return entries.length ? entries.slice(0, 4).map(([key, value]) => `${FIELD[key] || key}: ${shortValue(value, key)}`).join(" · ") : (ACTION[action] || "Evento registrado");
  };
  const auditDetails = (details) => {
    if (!details || typeof details !== "object" || !Object.keys(details).length) return null;
    const disclosure = node("details", "audit-details");
    disclosure.append(node("summary", "", "Ver auditoría completa"), node("pre", "", JSON.stringify(details, null, 2)));
    return disclosure;
  };

  async function request(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      try { payload = await response.json(); } catch (_) { /* handled as an invalid response below */ }
    }
    if (!response.ok) throw new ApiError(payload?.error || `La solicitud falló (${response.status})`, response.status);
    return payload;
  }

  function workspaceHeaders(scope, headers = {}) {
    const result = new Headers(headers);
    result.set("X-AgentRelay-Client", "browser");
    if (!scope.legacy) result.set("X-AgentRelay-Workspace", scope.id);
    return result;
  }

  function workspaceRequest(url, options, scope) {
    const captured = scope || captureWorkspace();
    if (!captured.id) throw new Error("No hay un proyecto seleccionado");
    return request(url, { ...(options || {}), headers: workspaceHeaders(captured, options?.headers) });
  }

  function validateWorkspaceState(state, scope) {
    if (!state || typeof state !== "object") throw new Error("El servicio devolvió un estado inválido");
    if (!scope.legacy && state.workspace?.id !== scope.id) {
      throw new Error("El servicio devolvió datos de otro proyecto");
    }
  }

  function setConnected(connected) {
    const line = $(".connection");
    line.classList.toggle("is-online", connected);
    $("#connection-label").textContent = connected ? "Servicio local activo" : "Sin conexión";
  }

  function showError(message) {
    const alert = $("#global-error");
    alert.textContent = message;
    alert.hidden = !message;
  }

  function toast(message, error = false) {
    const item = node("div", `toast${error ? " is-error" : ""}`, message);
    $("#toast-region").append(item);
    setTimeout(() => item.remove(), 4200);
  }

  function renderWorkspaceCatalog() {
    const select = $("#workspace-select");
    clear(select);
    app.workspaces.forEach((workspace) => {
      select.append(option(workspace.id, `${workspace.name} · ${workspace.database}`));
    });
    select.value = app.workspaceId || "";
    const workspace = activeWorkspace();
    $("#workspace-database").textContent = workspace?.database || "Base de datos no indicada";
    $("#workspace-database").title = workspace?.database || "";
    select.disabled = !app.workspaceId || app.mutationCount > 0;
    showSection(app.section, false);
  }

  function syncWorkspaceControls() {
    $("#workspace-select").disabled = !app.workspaceId || app.mutationCount > 0;
    const unavailable = !app.state;
    $("#export-button").disabled = unavailable;
    $("#new-ticket-button").disabled = unavailable;
    $("#new-profile-button").disabled = unavailable;
  }

  function resetWorkspaceUi() {
    app.state = null;
    closeTicket();
    app.dialogDirty = false;
    [$("#ticket-dialog"), $("#profile-dialog")].forEach((dialog) => {
      if (dialog.open) dialog.close();
    });
    $("#ticket-create-form").reset();
    $("#profile-form").reset();
    $("#search-filter").value = "";
    $("#priority-filter").value = "";
    $("#profile-filter").value = "";
    $("#status-filter").value = "";
    ["metrics", "board", "ticket-list", "execution-overview", "runs-list", "profiles-grid", "activity-list"].forEach((id) => clear($("#" + id)));
    $$(".page-view").forEach((view) => { view.hidden = true; });
    $("#demo-badge").hidden = true;
    $("#loading-state").hidden = false;
    $("#loading-state").lastChild.textContent = "Cargando proyecto…";
    showError("");
    syncWorkspaceControls();
  }

  async function selectWorkspace(id) {
    const workspace = app.workspaces.find((item) => item.id === id);
    if (!workspace || id === app.workspaceId) {
      $("#workspace-select").value = app.workspaceId || "";
      return;
    }
    if (app.mutationCount) {
      $("#workspace-select").value = app.workspaceId;
      toast("Espera a que termine la operación en curso antes de cambiar de proyecto.", true);
      return;
    }
    if (hasDirtyEdits() && !window.confirm("Hay cambios sin guardar. ¿Quieres descartarlos y cambiar de proyecto?")) {
      $("#workspace-select").value = app.workspaceId;
      return;
    }
    app.workspaceEpoch += 1;
    app.workspaceId = workspace.id;
    rememberWorkspace(workspace.id);
    resetWorkspaceUi();
    renderWorkspaceCatalog();
    await loadState();
  }

  async function loadWorkspaceCatalog() {
    let catalog;
    try {
      catalog = await request("/api/workspaces", { headers: { "X-AgentRelay-Client": "browser" } });
    } catch (error) {
      if (error.status !== 404) throw error;
      app.legacyWorkspace = true;
      app.workspaces = [{ id: "legacy", name: "Proyecto local", database: "Base de datos local", demo: false }];
      app.workspaceId = "legacy";
      app.workspaceEpoch += 1;
      renderWorkspaceCatalog();
      await loadState();
      return;
    }
    if (!catalog || !Array.isArray(catalog.workspaces) || !catalog.workspaces.length) {
      throw new Error("El catálogo de proyectos está vacío o no es válido");
    }
    const ids = new Set();
    for (const workspace of catalog.workspaces) {
      if (!workspace || typeof workspace.id !== "string" || !workspace.id || typeof workspace.name !== "string" || !workspace.name || typeof workspace.database !== "string" || !workspace.database || ids.has(workspace.id)) {
        throw new Error("El catálogo contiene un proyecto inválido");
      }
      ids.add(workspace.id);
    }
    if (typeof catalog.default_workspace_id !== "string" || !ids.has(catalog.default_workspace_id)) {
      throw new Error("El catálogo no define un proyecto predeterminado válido");
    }
    app.legacyWorkspace = false;
    app.workspaces = catalog.workspaces.map((workspace) => ({ ...workspace }));
    const remembered = storedWorkspace();
    app.workspaceId = ids.has(remembered) ? remembered : catalog.default_workspace_id;
    app.workspaceEpoch += 1;
    rememberWorkspace(app.workspaceId);
    renderWorkspaceCatalog();
    await loadState();
  }

  async function loadState({ quiet = false } = {}) {
    const scope = captureWorkspace();
    const dataEpoch = app.dataEpoch;
    if (!scope.id || app.mutationCount || app.loadingEpoch === scope.epoch) return;
    app.loadingEpoch = scope.epoch;
    try {
      const previousRuns = JSON.stringify((app.state?.execution?.runs || []).map((run) => [run.id, run.status, run.finished_at]));
      const state = await workspaceRequest("/api/state", {}, scope);
      if (!isCurrentWorkspace(scope) || dataEpoch !== app.dataEpoch) return;
      validateWorkspaceState(state, scope);
      app.state = state;
      setConnected(true);
      showError("");
      $("#demo-badge").hidden = !(state.workspace?.demo ?? state.demo);
      $("#loading-state").hidden = true;
      showSection(app.section, false);
      renderAll();
      if (app.selectedId && !app.drawerDirty) {
        const latest = state.tickets?.find((ticket) => ticket.id === app.selectedId);
        const nextRuns = JSON.stringify((state.execution?.runs || []).map((run) => [run.id, run.status, run.finished_at]));
        if (!app.context || latest?.revision !== app.context.ticket?.revision || previousRuns !== nextRuns) {
          await loadContext(app.selectedId);
        }
      }
    } catch (error) {
      if (!isCurrentWorkspace(scope) || dataEpoch !== app.dataEpoch) return;
      setConnected(false);
      if (!quiet || !app.state) {
        $("#loading-state").hidden = true;
        showError(`No se pudo cargar AgentRelay. ${error.message}`);
      }
    } finally {
      if (app.loadingEpoch === scope.epoch) app.loadingEpoch = null;
      if (isCurrentWorkspace(scope)) syncWorkspaceControls();
    }
  }

  async function mutate(action, data, successMessage, { drawerScope = null } = {}) {
    if (app.mutationCount) throw new Error("Espera a que termine la operación en curso.");
    const scope = captureWorkspace();
    let reloadAfterMutation = false;
    app.dataEpoch += 1;
    app.contextRequest += 1;
    app.mutationCount += 1;
    syncWorkspaceControls();
    try {
      const payload = await workspaceRequest("/api/actions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action, actor: "human", data })
      }, scope);
      if (!isCurrentWorkspace(scope)) return null;
      if (!payload || typeof payload !== "object" || !payload.state) throw new Error("El servicio devolvió una acción sin estado actualizado");
      validateWorkspaceState(payload.state, scope);
      app.state = payload.state;
      renderAll();
      if (app.selectedId && (!drawerScope || isCurrentDrawer(drawerScope))) {
        await loadContext(app.selectedId, { forceRender: true });
      }
      if (!isCurrentWorkspace(scope)) return null;
      if (successMessage && (!drawerScope || isCurrentDrawer(drawerScope))) toast(successMessage);
      return payload?.result;
    } catch (error) {
      if (!isCurrentWorkspace(scope)) return null;
      if (!drawerScope || isCurrentDrawer(drawerScope)) toast(error.message, true);
      if (action !== "complete_ticket" && /revision|conflict|actualiz|cambió/i.test(error.message)) reloadAfterMutation = true;
      throw error;
    } finally {
      app.mutationCount = Math.max(0, app.mutationCount - 1);
      app.dataEpoch += 1;
      syncWorkspaceControls();
      if (reloadAfterMutation && isCurrentWorkspace(scope)) await loadState({ quiet: true });
    }
  }

  function fillSelect(select, items, emptyLabel, selected) {
    clear(select);
    if (emptyLabel !== null) select.append(option("", emptyLabel));
    items.forEach((item) => select.append(option(item.id, item.name || `${item.id} · ${item.title}`)));
    if (selected !== undefined && selected !== null) select.value = selected;
  }

  function syncGlobalSelects() {
    const profiles = app.state?.profiles || [];
    fillSelect($("#profile-filter"), profiles, "Todos", $("#profile-filter").value);
    const createProfile = $("#ticket-create-form [name='profile_id']");
    fillSelect(createProfile, profiles, "Sin asignar", createProfile.value);
    const tickets = app.state?.tickets || [];
    const createParent = $("#ticket-create-form [name='parent_id']");
    fillSelect(createParent, tickets.filter((ticket) => !["done", "cancelled"].includes(ticket.status)), "Ninguna", createParent.value);
  }

  function visibleTickets() {
    const query = $("#search-filter").value.trim().toLocaleLowerCase("es");
    const priority = $("#priority-filter").value;
    const profile = $("#profile-filter").value;
    const status = $("#status-filter").value;
    return (app.state?.tickets || []).filter((ticket) => {
      const searchable = `${ticket.id} ${ticket.title} ${ticket.description || ""}`.toLocaleLowerCase("es");
      const defaultActive = !status && ticket.status !== "cancelled";
      const statusMatch = status === "all" || defaultActive || ticket.status === status;
      return (!query || searchable.includes(query)) && (!priority || ticket.priority === priority) && (!profile || ticket.profile_id === profile) && statusMatch;
    });
  }

  function renderMetrics() {
    const tickets = app.state?.tickets || [];
    const active = tickets.filter((ticket) => !["done", "cancelled"].includes(ticket.status));
    const ready = tickets.filter((ticket) => ticket.status === "queued" && ticket.ready).length;
    const inProgress = tickets.filter((ticket) => ticket.status === "in_progress").length;
    const review = tickets.filter((ticket) => ticket.status === "review").length;
    const blocked = tickets.filter((ticket) => ticket.status === "blocked" || (ticket.blockers || []).length).length;
    const definitions = [
      ["Trabajo activo", active.length, `${tickets.length} en total`],
      ["Listas para tomar", ready, "cola sin bloqueos"],
      ["En ejecución", inProgress, `${review} en revisión`],
      ["Con bloqueos", blocked, "requieren atención"]
    ];
    const target = $("#metrics");
    clear(target);
    definitions.forEach(([label, value, note]) => {
      const card = node("div", "metric");
      card.append(node("span", "metric-label", label));
      const line = node("div");
      line.append(node("span", "metric-value", value), node("span", "metric-note", note));
      card.append(line);
      target.append(card);
    });
  }

  function ticketCard(ticket) {
    const card = node("button", "ticket-card");
    card.type = "button";
    card.dataset.ticketId = ticket.id;
    card.setAttribute("aria-label", `Abrir ${ticket.id}: ${ticket.title}`);
    const top = node("div", "card-top");
    top.append(node("span", "ticket-id", ticket.id), node("span", `priority priority-${ticket.priority}`, PRIORITY[ticket.priority] || ticket.priority));
    card.append(top, node("h3", "", ticket.title));
    if (ticket.description) card.append(node("p", "card-description", ticket.description));
    const foot = node("div", "card-foot");
    const profile = profileById(ticket.profile_id);
    const identity = node("span", "profile-chip");
    identity.append(node("span", "avatar", initials(profile?.name || ticket.assignee || TYPE[ticket.type])));
    identity.append(node("span", "", ticket.assignee || profile?.name || TYPE[ticket.type] || ticket.type));
    foot.append(identity);
    const blockers = ticket.blockers || [];
    foot.append(node("span", blockers.length ? "blockers" : "", blockers.length ? `${blockers.length} bloqueo${blockers.length === 1 ? "" : "s"}` : ticket.ready && ticket.status === "queued" ? "Lista" : TYPE[ticket.type] || ticket.type));
    card.append(foot);
    return card;
  }

  function renderBoard() {
    const tickets = visibleTickets();
    const target = $("#board");
    clear(target);
    let columns = COLUMNS;
    if ($("#status-filter").value === "cancelled" || $("#status-filter").value === "all") columns = [...COLUMNS, "cancelled"];
    columns.forEach((status) => {
      const matching = tickets.filter((ticket) => ticket.status === status).sort((a, b) => ({ urgent: 0, high: 1, normal: 2, low: 3 }[a.priority] - ({ urgent: 0, high: 1, normal: 2, low: 3 }[b.priority])));
      const column = node("section", "kanban-column");
      column.setAttribute("aria-labelledby", `column-${status}`);
      const head = node("header", "column-head");
      const title = node("h2", "", STATUS[status]);
      title.id = `column-${status}`;
      head.append(title, node("span", "column-count", matching.length));
      const body = node("div", "column-body");
      matching.forEach((ticket) => body.append(ticketCard(ticket)));
      if (!matching.length) body.append(node("div", "empty-column", "Sin tareas"));
      column.append(head, body);
      target.append(column);
    });
  }

  function renderList() {
    const target = $("#ticket-list");
    clear(target);
    const tickets = visibleTickets();
    if (!tickets.length) {
      target.append(node("div", "empty-page", "No hay tareas que coincidan con los filtros."));
      return;
    }
    tickets.forEach((ticket) => {
      const row = node("button", "list-row");
      row.type = "button";
      row.dataset.ticketId = ticket.id;
      row.append(node("span", "ticket-id", ticket.id));
      const title = node("span", "list-title");
      title.append(node("strong", "", ticket.title), node("small", "", ticket.description || "Sin descripción"));
      row.append(title, node("span", "status-label", STATUS[ticket.status] || ticket.status), node("span", `priority priority-${ticket.priority}`, PRIORITY[ticket.priority] || ticket.priority));
      row.append(node("span", "", profileById(ticket.profile_id)?.name || ticket.assignee || "Sin perfil"));
      target.append(row);
    });
  }

  function renderProfiles() {
    const target = $("#profiles-grid");
    clear(target);
    const profiles = app.state?.profiles || [];
    if (!profiles.length) {
      target.append(node("div", "empty-page", "Todavía no hay perfiles. Crea uno para recomendar roles y modelos."));
      return;
    }
    profiles.forEach((profile) => {
      const card = node("article", "profile-card");
      const head = node("div", "profile-card-head");
      const heading = node("div");
      heading.append(node("h2", "", profile.name), node("span", "role", profile.role));
      const edit = node("button", "button button-quiet button-small", "Editar");
      edit.type = "button";
      edit.dataset.editProfile = profile.id;
      head.append(heading, edit);
      card.append(head, node("p", "", profile.description || "Sin descripción."));
      const model = node("div", "model-box");
      model.append(node("strong", "", profile.model), node("span", "", profile.effort || "Predeterminado"), node("small", "", `${profile.provider || "Proveedor no indicado"} · Preferencia: ${profile.preference || "balanced"}`));
      card.append(model);
      const capabilities = node("div", "capabilities");
      (profile.capabilities || []).forEach((capability) => capabilities.append(node("span", "capability", capability)));
      if (!(profile.capabilities || []).length) capabilities.append(node("span", "capability", "Sin capacidades declaradas"));
      card.append(capabilities);
      target.append(card);
    });
  }

  function renderActivity() {
    const target = $("#activity-list");
    clear(target);
    const events = app.state?.events || [];
    if (!events.length) {
      target.append(node("div", "empty-page", "Aún no hay actividad registrada."));
      return;
    }
    events.forEach((event) => {
      const item = node("article", "event");
      item.append(node("span", "event-icon", "↗"));
      const body = node("div");
      body.append(node("strong", "", `${event.actor || "sistema"} · ${ACTION[event.action] || event.action || "Evento"}${event.ticket_id ? ` · ${event.ticket_id}` : ""}`));
      body.append(node("p", "", describeDetails(event.details, event.action)));
      const raw = auditDetails(event.details);
      if (raw) body.append(raw);
      const time = node("time", "", formatDate(event.created_at));
      if (event.created_at) time.dateTime = event.created_at;
      item.append(body, time);
      target.append(item);
    });
  }

  function executionState() {
    return app.state?.execution || { enabled: false, workers: [], runs: [] };
  }

  function compatibleWorkers(ticket) {
    return (executionState().workers || []).filter((worker) => {
      const profiles = worker.profile_ids || [];
      const profileMatches = !profiles.length || (ticket.profile_id && profiles.includes(ticket.profile_id));
      const astraMatches = ticket.profile_id !== "astra" || (worker.model === "gpt-6-astra" && worker.effort === "high");
      return profileMatches && astraMatches;
    });
  }

  function configuredWorkerText(worker) {
    const effort = worker.effort && worker.effort !== "default" ? ` · esfuerzo ${worker.effort}` : " · esfuerzo predeterminado";
    return `${worker.model || "Modelo no indicado"}${effort} · límite ${worker.timeout_seconds || "—"} s`;
  }

  function setupExecutionEmpty(title, message) {
    const empty = node("div", "execution-setup empty-page");
    empty.append(node("h2", "", title), node("p", "", message));
    const command = node("code", "setup-command", "agentrelay serve --workers workers.json");
    empty.append(command, node("p", "setup-help", "Consulta la sección de ejecución local de la documentación para el formato JSON de ejecutores."));
    return empty;
  }

  function renderExecutions() {
    const execution = executionState();
    const overview = $("#execution-overview");
    const list = $("#runs-list");
    clear(overview); clear(list);
    if (!execution.enabled) {
      overview.append(setupExecutionEmpty("Ejecución local desactivada", "El flujo manual y MCP continúa disponible. Para habilitar ejecutores, reinicia el servicio con un archivo de configuración explícito."));
    } else if (!(execution.workers || []).length) {
      overview.append(setupExecutionEmpty("No hay ejecutores configurados", "La ejecución está habilitada, pero el archivo indicado no contiene ejecutores utilizables. Revisa la configuración y reinicia el servicio."));
    } else {
      const running = (execution.runs || []).find((run) => run.status === "running");
      if (running) overview.append(node("div", "run-notice", `Hay una ejecución activa: ${running.id} · ${running.ticket_id}. AgentRelay admite una sola ejecución simultánea.`));
      const heading = node("div", "subsection-head");
      heading.append(node("h2", "", "Ejecutores configurados"), node("span", "", `${execution.workers.length} configurado${execution.workers.length === 1 ? "" : "s"}`));
      const grid = node("div", "workers-grid");
      execution.workers.forEach((worker) => {
        const card = node("article", "worker-card");
        const head = node("div", "worker-head");
        head.append(node("span", "avatar", initials(worker.name)), node("div", "worker-title"));
        $(".worker-title", head).append(node("strong", "", worker.name), node("small", "", worker.id));
        card.append(head, node("p", "worker-model", configuredWorkerText(worker)));
        const profiles = worker.profile_ids || [];
        card.append(node("small", "worker-profiles", profiles.length ? `Perfiles: ${profiles.map((id) => profileById(id)?.name || id).join(", ")}` : "Sin restricción de perfil; Astra conserva su modelo y esfuerzo obligatorios"));
        grid.append(card);
      });
      overview.append(heading, grid);
    }

    const runHeading = node("div", "subsection-head");
    const runs = execution.runs || [];
    runHeading.append(node("h2", "", "Historial de ejecuciones"), node("span", "", `${runs.length} registro${runs.length === 1 ? "" : "s"}`));
    list.append(runHeading);
    if (!runs.length) {
      list.append(node("div", "empty-page compact-empty", execution.enabled ? "Aún no hay ejecuciones. Abre una tarea en cola y lista para elegir un ejecutor compatible." : "Las ejecuciones aparecerán aquí cuando habilites esta función y lances una tarea."));
      return;
    }
    runs.forEach((run) => {
      const card = node("article", "run-card");
      const top = node("div", "run-card-top");
      const identity = node("div");
      identity.append(node("span", "ticket-id", run.id), node("h3", "", `${run.ticket_id} · ${execution.workers.find((worker) => worker.id === run.worker_id)?.name || run.worker_id}`));
      top.append(identity, node("span", `run-status run-${run.status}`, RUN_STATUS[run.status] || run.status));
      card.append(top);
      const facts = node("div", "run-facts");
      facts.append(node("span", "", `Modelo configurado: ${run.model || "no indicado"}`), node("span", "", `Esfuerzo: ${run.effort || "predeterminado"}`), node("span", "", `Inicio: ${formatDate(run.started_at)}`));
      if (run.finished_at) facts.append(node("span", "", `Fin: ${formatDate(run.finished_at)}`));
      card.append(facts);
      if (run.summary) card.append(node("p", "run-summary", run.summary));
      if (run.error) card.append(node("p", "run-error", run.error));
      const actions = node("div", "run-actions");
      const open = node("button", "button button-quiet button-small", "Abrir tarea");
      open.type = "button"; open.dataset.ticketId = run.ticket_id;
      actions.append(open);
      if (run.status === "running") {
        const cancel = node("button", "button button-danger button-small", "Cancelar ejecución");
        cancel.type = "button";
        cancel.addEventListener("click", async () => {
          cancel.disabled = true;
          try {
            const result = await mutate("cancel_run", { run_id: run.id }, null);
            if (result?.status === "cancelled") toast("Ejecución cancelada");
            else toast(`La ejecución ya había terminado: ${RUN_STATUS[result?.status] || result?.status || "estado desconocido"}`);
          } catch (_) { cancel.disabled = false; }
        });
        actions.append(cancel);
      }
      card.append(actions); list.append(card);
    });
  }

  function renderAll() {
    if (!app.state) return;
    syncGlobalSelects();
    renderMetrics();
    renderBoard();
    renderList();
    renderExecutions();
    renderProfiles();
    renderActivity();
    setDisplay(app.display);
  }

  function showSection(section, render = true) {
    app.section = section;
    const content = {
      board: ["Espacio de trabajo", "Proyecto", "Coordina el trabajo humano y de agentes externos con evidencia trazable."],
      executions: ["Ejecución local", "Ejecuciones", "Lanza trabajo con ejecutores configurados y conserva el resultado para revisión humana."],
      profiles: ["Configuración", "Perfiles", "Recomendaciones explícitas de rol, modelo, esfuerzo y capacidades."],
      activity: ["Auditoría", "Actividad", "Historial reciente y verificable del proyecto."]
    }[section];
    const workspaceName = activeWorkspace()?.name || "Proyecto";
    $("#section-eyebrow").textContent = content[0];
    $("#page-title").textContent = section === "board" ? workspaceName : `${content[1]} · ${workspaceName}`;
    $("#page-subtitle").textContent = content[2];
    document.title = `${content[1]} · ${workspaceName} · AgentRelay`;
    $$(".page-view").forEach((view) => { view.hidden = view.id !== `${section}-view`; });
    $$("[data-nav]").forEach((button) => button.classList.toggle("is-active", button.dataset.nav === section));
    $("#new-ticket-button").hidden = section !== "board";
    if (render && app.state) renderAll();
  }

  function setDisplay(display) {
    app.display = display;
    localStorage.setItem("agentrelay-view", display);
    $("#board").hidden = display !== "board";
    $("#ticket-list").hidden = display !== "list";
    $$('[data-display]').forEach((button) => button.classList.toggle("is-active", button.dataset.display === display));
  }

  async function loadContext(id, { forceRender = false } = {}) {
    const scope = captureWorkspace();
    const requestId = ++app.contextRequest;
    try {
      const context = await workspaceRequest(`/api/tickets/${encodeURIComponent(id)}/context`, {}, scope);
      if (!isCurrentWorkspace(scope) || app.selectedId !== id || requestId !== app.contextRequest) return;
      if (!scope.legacy && context?.workspace?.id !== scope.id) throw new Error("El contexto pertenece a otro proyecto");
      if (!forceRender && app.drawerDirty) return;
      app.context = context;
      if (forceRender || !app.drawerDirty) renderDrawer();
      return context;
    } catch (error) {
      if (!isCurrentWorkspace(scope) || app.selectedId !== id || requestId !== app.contextRequest) return;
      toast(`No se pudo cargar el contexto: ${error.message}`, true);
      return null;
    }
  }

  function openTicket(id) {
    app.drawerEpoch += 1;
    app.selectedId = id;
    app.context = null;
    app.reviewDraft = null;
    app.drawerDirty = false;
    $("#scrim").hidden = false;
    const drawer = $("#ticket-drawer");
    drawer.classList.add("is-open");
    drawer.setAttribute("aria-hidden", "false");
    $("#drawer-id").textContent = id;
    $("#drawer-title").textContent = "Cargando…";
    clear($("#drawer-body"));
    $("#drawer-body").append(node("div", "loading-state", "Cargando contexto…"));
    loadContext(id, { forceRender: true });
    setTimeout(() => $("[data-close]", drawer)?.focus(), 50);
  }

  function closeTicket() {
    app.drawerEpoch += 1;
    app.contextRequest += 1;
    app.selectedId = null;
    app.context = null;
    app.reviewDraft = null;
    app.drawerDirty = false;
    $("#scrim").hidden = true;
    const drawer = $("#ticket-drawer");
    drawer.classList.remove("is-open");
    drawer.setAttribute("aria-hidden", "true");
  }

  function field(labelText, control, className = "") {
    const label = node("label", className, labelText);
    label.append(control);
    return label;
  }

  function input(name, value = "", type = "text") {
    const control = document.createElement("input");
    control.name = name;
    control.type = type;
    control.value = value ?? "";
    return control;
  }

  function textarea(name, value = "", rows = 3) {
    const control = document.createElement("textarea");
    control.name = name;
    control.rows = rows;
    control.value = value ?? "";
    return control;
  }

  function select(name, choices, selected = "") {
    const control = document.createElement("select");
    control.name = name;
    choices.forEach(([value, label]) => control.append(option(value, label)));
    control.value = selected ?? "";
    return control;
  }

  function drawerSection(title) {
    const section = node("section", "drawer-section");
    section.append(node("h3", "", title));
    return section;
  }

  function renderDrawer() {
    const ticket = currentTicket();
    if (!ticket) return;
    $("#drawer-id").textContent = `${ticket.id} · rev. ${ticket.revision}`;
    $("#drawer-title").textContent = ticket.title;
    const body = $("#drawer-body");
    clear(body);
    const summary = node("div", "drawer-summary");
    const recommendedProfile = profileById(ticket.profile_id);
    const summaryData = [
      STATUS[ticket.status],
      PRIORITY[ticket.priority],
      TYPE[ticket.type],
      ticket.ready ? "Lista" : null,
      recommendedProfile ? `Perfil recomendado: ${recommendedProfile.name}` : null,
      ticket.assignee ? `Responsable: ${ticket.assignee}` : null,
      ticket.actual_model ? `Modelo usado: ${ticket.actual_model}` : null,
      ticket.actual_effort ? `Esfuerzo usado: ${ticket.actual_effort}` : null
    ].filter(Boolean);
    summaryData.forEach((value) => summary.append(node("span", "summary-pill", value)));
    if ((ticket.blockers || []).length) summary.append(node("span", "summary-pill blockers", `${ticket.blockers.length} bloqueo${ticket.blockers.length === 1 ? "" : "s"}`));
    const sections = [summary, editSection(ticket), lifecycleSection(ticket)];
    if (ticket.status === "queued" && ticket.ready) sections.push(executionSection(ticket));
    sections.push(relationsSection(ticket), evidenceSection(ticket), sourceChecksSection(), contextSection(ticket));
    body.append(...sections);
    app.drawerDirty = false;
    const markDirty = () => { app.drawerDirty = true; };
    $("#drawer-body").addEventListener("input", markDirty, { once: true });
    $("#drawer-body").addEventListener("change", markDirty, { once: true });
  }

  function editSection(ticket) {
    const section = drawerSection("Definición");
    const form = node("form", "form-grid");
    form.dataset.form = "edit-ticket";
    const locked = ticket.status === "done";
    const titleControl = input("title", ticket.title); titleControl.required = true;
    form.append(field("Título", titleControl, "span-2"));
    form.append(field("Descripción", textarea("description", ticket.description, 4), "span-2"));
    form.append(field("Tipo", select("type", Object.entries(TYPE).map(([value, label]) => [value, label]), ticket.type)));
    form.append(field("Prioridad", select("priority", Object.entries(PRIORITY).map(([value, label]) => [value, label]), ticket.priority)));
    const ticketChoices = [["", "Ninguna"], ...(app.state?.tickets || []).filter((item) => item.id !== ticket.id).map((item) => [item.id, `${item.id} · ${item.title}`])];
    form.append(field("Tarea padre", select("parent_id", ticketChoices, ticket.parent_id || "")));
    const profileChoices = [["", "Sin asignar"], ...(app.state?.profiles || []).map((profile) => [profile.id, profile.name])];
    form.append(field("Perfil recomendado", select("profile_id", profileChoices, ticket.profile_id || "")));
    form.append(field("Dependencias (IDs separados por comas)", input("depends_on", (ticket.depends_on || []).join(", ")), "span-2"));
    form.append(field("Criterios de aceptación (uno por línea)", textarea("acceptance", (ticket.acceptance || []).join("\n"), 4), "span-2"));
    if (locked) {
      $$('input, select, textarea', form).forEach((control) => { control.disabled = true; });
      form.append(node("div", "context-note span-2", "La definición queda cerrada al completar la tarea. Reábrela desde Acciones para cambiar su alcance."));
    } else {
      const actions = node("div", "form-actions span-2");
      const save = node("button", "button button-primary button-small", "Guardar cambios"); save.type = "submit";
      actions.append(save); form.append(actions);
    }
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const data = new FormData(form);
      try {
        await mutate("update_ticket", {
          id: ticket.id,
          expected_revision: currentTicket().revision,
          title: data.get("title").trim(),
          description: data.get("description").trim(),
          type: data.get("type"), priority: data.get("priority"),
          parent_id: data.get("parent_id") || null,
          profile_id: data.get("profile_id") || null,
          depends_on: values(data.get("depends_on")),
          acceptance: values(data.get("acceptance"), /\n/)
        }, "Tarea actualizada");
        app.drawerDirty = false;
      } catch (_) { /* shown globally */ }
    });
    section.append(form);
    return section;
  }

  function lifecycleSection(ticket) {
    const section = drawerSection("Acciones");
    const tabs = node("div", "action-tabs");
    const panels = node("div");
    const actions = [];
    if (ticket.status === "queued" && ticket.ready) actions.push(["claim", "Tomar"]);
    if (ticket.status === "in_progress") actions.push(["checkpoint", "Avance"], ["submit", "Enviar a revisión"]);
    if (ticket.status === "review") actions.push(["complete", "Revisar y cerrar"]);
    actions.push(["transition", "Cambiar estado"]);
    if (!["done", "cancelled"].includes(ticket.status)) actions.push(["comment", "Comentar"], ["child", "Crear hija"], ["help", "Pedir ayuda"], ["split", "Dividir"]);
    else actions.push(["comment", "Comentar"]);
    actions.forEach(([id, label], index) => {
      const tab = node("button", `action-tab${index === 0 ? " is-active" : ""}`, label);
      tab.type = "button"; tab.dataset.actionTab = id;
      tabs.append(tab);
      const panel = buildActionPanel(id, ticket);
      panel.dataset.actionPanel = id;
      panel.hidden = index !== 0;
      panels.append(panel);
    });
    tabs.addEventListener("click", (event) => {
      const button = event.target.closest("[data-action-tab]");
      if (!button) return;
      $$('[data-action-tab]', tabs).forEach((item) => item.classList.toggle("is-active", item === button));
      $$('[data-action-panel]', panels).forEach((panel) => { panel.hidden = panel.dataset.actionPanel !== button.dataset.actionTab; });
    });
    section.append(tabs, panels);
    return section;
  }

  function executionSection(ticket) {
    const section = drawerSection("Ejecución local");
    const execution = executionState();
    if (!(ticket.acceptance || []).length) {
      section.append(node("div", "context-note", "Esta tarea no se puede ejecutar todavía. Añade al menos un criterio de aceptación para delimitar el resultado y su revisión."));
      return section;
    }
    if (!execution.enabled) {
      section.append(node("div", "context-note", "La ejecución local está desactivada. El trabajo manual y mediante MCP sigue disponible. Configúrala al iniciar el servicio con --workers workers.json."));
      return section;
    }
    const workers = compatibleWorkers(ticket);
    if (!workers.length) {
      const profile = profileById(ticket.profile_id);
      section.append(node("div", "context-note", profile ? `No hay un ejecutor configurado para el perfil recomendado ${profile.name}. Puedes tomar la tarea manualmente o actualizar la configuración de ejecutores.` : "Esta tarea no tiene perfil y no hay un ejecutor configurado para cualquier perfil. Puedes tomarla manualmente o actualizar la configuración."));
      return section;
    }
    const running = (execution.runs || []).find((run) => run.status === "running");
    const form = node("form", "stack-form execution-form");
    const workerSelect = select("worker_id", workers.map((worker) => [worker.id, worker.name]), workers[0].id);
    form.append(field("Ejecutor compatible", workerSelect));
    const configured = node("div", "execution-config");
    const updateConfigured = () => {
      const worker = workers.find((item) => item.id === workerSelect.value);
      clear(configured);
      if (!worker) return;
      configured.append(node("strong", "", worker.name), node("span", "", `Modelo de ejecución: ${worker.model || "no indicado"}`), node("span", "", `Esfuerzo de ejecución: ${worker.effort || "predeterminado"}`), node("span", "", `Tiempo máximo: ${worker.timeout_seconds || "—"} segundos`));
    };
    workerSelect.addEventListener("change", updateConfigured);
    updateConfigured();
    form.append(configured, node("div", "context-note", "AgentRelay iniciará el ejecutor elegido. Si entrega un resultado, la tarea pasará a revisión; la aceptación sigue siendo una decisión humana."));
    if (running) form.append(node("div", "alert alert-error", `Ya hay una ejecución activa (${running.id} · ${running.ticket_id}). Cancélala o espera a que termine antes de iniciar otra.`));
    const actions = node("div", "form-actions");
    const start = node("button", "button button-primary button-small", "Ejecutar tarea");
    start.type = "submit"; start.disabled = Boolean(running);
    workerSelect.disabled = Boolean(running);
    actions.append(start); form.append(actions);
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const openTicketState = currentTicket();
      if (!openTicketState || openTicketState.status !== "queued" || !openTicketState.ready) {
        toast("La tarea ya no está en cola y lista. Actualiza su contexto.", true);
        return;
      }
      start.disabled = true;
      try {
        await mutate("start_run", { ticket_id: ticket.id, worker_id: workerSelect.value, expected_revision: openTicketState.revision }, "Ejecución iniciada");
        app.drawerDirty = false;
      } catch (_) { start.disabled = false; }
    });
    section.append(form);
    return section;
  }

  function buildActionPanel(action, ticket) {
    const form = node("form", "stack-form action-panel");
    const profile = profileById(ticket.profile_id);
    let submitLabel = "Guardar";
    let completionAvailable = true;
    let confirmationControl = null;
    if (action === "claim") {
      const assignee = input("assignee", "human"); assignee.required = true;
      form.append(field("Responsable", assignee));
      form.append(node("div", "context-note", profile ? `Recomendación: ${profile.model}${profile.effort ? ` · esfuerzo ${profile.effort}` : ""}. Tomar la tarea no inicia ninguna inferencia.` : "Tomar la tarea no inicia ninguna inferencia."));
      form.append(field("Modelo realmente usado (si se conoce)", input("actual_model", "")));
      form.append(field("Esfuerzo realmente usado (si se conoce)", input("actual_effort", "")));
      submitLabel = "Tomar tarea";
    } else if (action === "checkpoint") {
      const checkpoint = textarea("checkpoint", ticket.checkpoint || "", 3); checkpoint.required = true;
      form.append(field("Resumen del avance", checkpoint));
      submitLabel = "Registrar avance";
    } else if (action === "submit") {
      const summary = textarea("summary", ticket.checkpoint || "", 3); summary.required = true;
      form.append(field("Resumen para revisión", summary));
      const grid = node("div", "form-grid");
      const kind = input("evidence_kind", "archivo"); kind.required = true;
      const label = input("evidence_label", "Resultado"); label.required = true;
      const uri = input("evidence_uri", ""); uri.required = true;
      grid.append(field("Tipo de evidencia", kind), field("Etiqueta", label), field("URI o ruta", uri, "span-2"));
      form.append(grid);
      submitLabel = "Enviar a revisión";
    } else if (action === "complete") {
      const draft = reviewDraftFor(ticket);
      const token = acceptanceContextToken();
      form.dataset.acceptanceContextToken = token || "";
      const verification = textarea("verification", draft?.verification || "", 3); verification.required = true;
      form.append(field("Verificación realizada", verification));
      const checklist = node("div", "check-list");
      const criterionControls = [];
      (ticket.acceptance || []).forEach((criterion, index) => {
        const check = input("accepted_criteria", criterion, "checkbox");
        check.checked = Boolean(draft?.acceptedCriteria?.includes(criterion));
        criterionControls.push(check);
        check.id = `criterion-${ticket.id}-${index}`;
        const label = node("label", "check-row");
        label.htmlFor = check.id;
        label.append(check, node("span", "", criterion));
        checklist.append(label);
      });
      if (!(ticket.acceptance || []).length) checklist.append(node("div", "context-note", "Esta tarea no tiene criterios de aceptación. El backend exige una aceptación significativa para completarla."));
      form.append(checklist);
      if (!token) {
        completionAvailable = false;
        form.append(node("div", "alert alert-error", "Este contexto no incluye la huella de aceptación obligatoria. Actualiza el servicio y vuelve a cargar o abrir la tarea; no se puede aceptar con contexto heredado."));
      } else if (draft?.refreshRequired) {
        completionAvailable = false;
        form.append(node("div", "alert alert-error", "No se pudo cargar el contexto actualizado. Tu borrador está guardado, pero debes reintentar la lectura antes de aceptar."));
        const retry = node("button", "button button-secondary button-small", "Reintentar carga de contexto");
        retry.type = "button";
        retry.addEventListener("click", async () => {
          const currentDraft = reviewDraftFor(ticket);
          if (currentDraft) {
            currentDraft.verification = verification.value;
            currentDraft.acceptedCriteria = criterionControls.filter((control) => control.checked).map((control) => control.value);
          }
          retry.disabled = true;
          verification.disabled = true;
          criterionControls.forEach((control) => { control.disabled = true; });
          await refreshCompletionContext(ticket.id);
          if (reviewDraftFor(currentTicket())?.refreshRequired) retry.disabled = false;
        });
        form.append(retry);
      } else if (draft?.needsConfirmation) {
        form.append(node("div", "alert alert-error", "El contexto de aceptación cambió. Se conservaron tu verificación y criterios, pero debes revisar las relaciones y la evidencia actualizadas antes de confirmar de nuevo."));
        confirmationControl = input("confirm_updated_context", "yes", "checkbox");
        const confirmationLabel = node("label", "check-row");
        confirmationLabel.append(confirmationControl, node("span", "", "He revisado el contexto actualizado y confirmo esta aceptación."));
        form.append(confirmationLabel);
      }
      submitLabel = "Completar tarea";
    } else if (action === "transition") {
      const allowed = [];
      if (ticket.status !== "backlog") allowed.push(["backlog", "Mover a propuestas"]);
      if (ticket.status !== "queued") allowed.push(["queued", "Mover a cola"]);
      if (ticket.status !== "blocked") allowed.push(["blocked", "Marcar bloqueada"]);
      if (ticket.status !== "cancelled") allowed.push(["cancelled", "Cancelar"]);
      const statusControl = select("status", allowed);
      const reasonControl = textarea("reason", ticket.blocked_reason || "", 2);
      const syncReason = () => {
        const required = ticket.status === "done" || statusControl.value === "blocked";
        reasonControl.required = required;
        reasonControl.placeholder = required ? "Indica el motivo de este cambio" : "Motivo opcional";
      };
      statusControl.addEventListener("change", syncReason);
      syncReason();
      form.append(field("Nuevo estado", statusControl));
      form.append(field("Motivo", reasonControl));
      submitLabel = "Cambiar estado";
    } else if (action === "comment") {
      const body = textarea("body", "", 3); body.required = true;
      form.append(field("Comentario", body));
      submitLabel = "Añadir comentario";
    } else if (action === "child") {
      const childTitle = input("title", ""); childTitle.required = true;
      form.append(field("Título de la tarea hija", childTitle));
      form.append(field("Descripción", textarea("description", "", 2)));
      form.append(field("Criterios de aceptación (uno por línea)", textarea("acceptance", "", 3)));
      submitLabel = "Crear tarea hija";
    } else if (action === "help") {
      const helpTitle = input("title", `Ayuda para ${ticket.id}`); helpTitle.required = true;
      const helpDescription = textarea("description", "", 3); helpDescription.required = true;
      form.append(field("Título de la ayuda", helpTitle));
      form.append(field("Qué se necesita", helpDescription));
      const profiles = [["", "Sin perfil"], ...(app.state?.profiles || []).map((item) => [item.id, item.name])];
      form.append(field("Perfil recomendado", select("profile_id", profiles, ticket.profile_id || "")));
      submitLabel = "Solicitar ayuda y bloquear";
    } else if (action === "split") {
      const children = textarea("children", "", 4); children.required = true;
      form.append(field("Nuevas tareas (un título por línea)", children));
      submitLabel = "Dividir y bloquear";
    }
    const actions = node("div", "form-actions");
    const submit = node("button", "button button-primary button-small", submitLabel); submit.type = "submit";
    if (action === "complete") {
      submit.disabled = !completionAvailable || Boolean(confirmationControl);
      confirmationControl?.addEventListener("change", () => { submit.disabled = !confirmationControl.checked; });
    }
    actions.append(submit); form.append(actions);
    form.addEventListener("submit", (event) => submitActionForm(event, action, ticket));
    return form;
  }

  async function refreshCompletionContext(ticketId, drawerScope = captureDrawer(ticketId)) {
    if (!isCurrentDrawer(drawerScope)) return false;
    const draft = reviewDraftFor({ id: ticketId });
    if (!draft) return false;
    draft.refreshRequired = false;
    app.drawerDirty = false;
    const refreshed = await loadContext(ticketId, { forceRender: true });
    if (!isCurrentDrawer(drawerScope)) return false;
    if (!refreshed) {
      draft.refreshRequired = true;
      renderDrawer();
      app.drawerDirty = true;
      toast("No se pudo cargar el contexto actualizado. Tu borrador sigue guardado; usa Reintentar carga de contexto.", true);
      return false;
    }
    if (refreshed.ticket?.status !== "review") {
      app.reviewDraft = null;
      toast("La tarea ya no está en revisión. Se cargó su estado actual y no se reenvió la aceptación.", true);
      return false;
    }
    toast("El contexto cambió. Revisa los datos actualizados y confirma de nuevo; no se ha reenviado la aceptación.", true);
    return true;
  }

  async function handleCompletionConflict(ticket, payload, drawerScope = captureDrawer(ticket.id)) {
    if (!isCurrentDrawer(drawerScope)) return false;
    app.reviewDraft = {
      workspaceId: drawerScope.id,
      workspaceEpoch: drawerScope.epoch,
      drawerEpoch: drawerScope.drawerEpoch,
      ticketId: ticket.id,
      verification: payload.verification,
      acceptedCriteria: [...payload.accepted_criteria],
      previousToken: payload.expected_acceptance_context_token,
      needsConfirmation: true,
      refreshRequired: false
    };
    return refreshCompletionContext(ticket.id, drawerScope);
  }

  async function submitActionForm(event, action, originalTicket) {
    event.preventDefault();
    const form = event.currentTarget;
    const data = new FormData(form);
    const ticket = currentTicket() || originalTicket;
    const completionScope = action === "complete" ? captureDrawer(ticket.id) : null;
    const base = { id: ticket.id, expected_revision: ticket.revision };
    let apiAction = action;
    let payload = base;
    let message = "Acción registrada";
    if (action === "claim") {
      apiAction = "claim_ticket"; payload = { ...base, assignee: data.get("assignee").trim(), actual_model: data.get("actual_model").trim() || null, actual_effort: data.get("actual_effort").trim() || null }; message = "Tarea tomada";
    } else if (action === "checkpoint") {
      payload = { ...base, checkpoint: data.get("checkpoint").trim() }; message = "Avance registrado";
    } else if (action === "submit") {
      apiAction = "submit_ticket"; payload = { ...base, summary: data.get("summary").trim(), evidence: [{ kind: data.get("evidence_kind").trim(), label: data.get("evidence_label").trim(), uri: data.get("evidence_uri").trim() }] }; message = "Enviada a revisión";
    } else if (action === "complete") {
      apiAction = "complete_ticket";
      try {
        payload = buildCompletionPayload(ticket, {
          verification: data.get("verification").trim(),
          acceptedCriteria: data.getAll("accepted_criteria"),
          acceptanceToken: form.dataset.acceptanceContextToken,
          confirmed: data.get("confirm_updated_context") === "yes"
        });
      } catch (error) {
        toast(error.message, true);
        return;
      }
      message = "Tarea completada";
    } else if (action === "transition") {
      payload = { ...base, status: data.get("status"), reason: data.get("reason").trim() }; message = "Estado actualizado";
    } else if (action === "comment") {
      apiAction = "add_comment"; payload = { id: ticket.id, expected_revision: ticket.revision, body: data.get("body").trim() }; message = "Comentario añadido";
    } else if (action === "child") {
      apiAction = "create_ticket"; payload = { title: data.get("title").trim(), description: data.get("description").trim(), parent_id: ticket.id, profile_id: ticket.profile_id || null, acceptance: values(data.get("acceptance"), /\n/) }; message = "Tarea hija creada";
    } else if (action === "help") {
      apiAction = "request_help"; payload = { ...base, title: data.get("title").trim(), description: data.get("description").trim(), profile_id: data.get("profile_id") || null }; message = "Ayuda solicitada";
    } else if (action === "split") {
      apiAction = "split_ticket"; payload = { ...base, children: values(data.get("children"), /\n/).map((title) => ({ title, profile_id: ticket.profile_id || null })) }; message = "Tarea dividida";
    }
    try {
      await mutate(apiAction, payload, message, { drawerScope: completionScope });
      if (completionScope && !isCurrentDrawer(completionScope)) return;
      if (action === "complete") app.reviewDraft = null;
      app.drawerDirty = false;
    } catch (error) {
      if (completionScope && !isCurrentDrawer(completionScope)) return;
      if (action !== "complete" || !acceptanceRefreshConflict(error)) return;
      await handleCompletionConflict(ticket, payload, completionScope);
    }
  }

  function relationsSection(ticket) {
    const section = drawerSection("Relaciones y bloqueos");
    const groups = [
      ["Padre", app.context?.parent ? [app.context.parent] : []],
      ["Dependencias", app.context?.dependencies || []],
      ["Hijas", app.context?.children || []]
    ];
    groups.forEach(([label, items]) => {
      if (!items.length) return;
      section.append(node("h4", "", label));
      const list = node("div", "relation-list");
      items.forEach((item) => {
        const row = node("details", "audit-details context-note");
        row.append(node("summary", "", `${item.id} · ${item.title} · ${STATUS[item.status] || item.status} · rev. ${item.revision}`));
        if (item.description) row.append(node("p", "", item.description));
        const criteria = item.acceptance || [];
        row.append(node("strong", "", "Criterios de aceptación"));
        if (criteria.length) {
          const criteriaList = node("ul", "");
          criteria.forEach((criterion) => criteriaList.append(node("li", "", criterion)));
          row.append(criteriaList);
        } else row.append(node("p", "", "Sin criterios registrados."));
        if (item.checkpoint) row.append(node("strong", "", "Último resumen"), node("p", "", item.checkpoint));
        const evidence = item.evidence || [];
        row.append(node("strong", "", "Evidencia registrada"));
        if (evidence.length) {
          const evidenceList = node("div", "evidence-list");
          evidence.forEach((entry) => evidenceList.append(node("div", "evidence-item", `${entry.label || "Evidencia"} · ${entry.kind || "referencia"} · ${entry.uri || "Sin URI"}`)));
          row.append(evidenceList);
        } else row.append(node("p", "", "Sin evidencia registrada."));
        const open = node("button", "button button-secondary button-small", "Abrir esta tarea"); open.type = "button";
        open.addEventListener("click", () => openTicket(item.id));
        row.append(open); list.append(row);
      });
      section.append(list);
    });
    if ((ticket.blockers || []).length) {
      section.append(node("h4", "", "Bloqueos activos"));
      section.append(node("div", "context-note", (ticket.blockers || []).join("\n")));
    }
    if (ticket.blocked_reason) section.append(node("div", "context-note", `Motivo manual: ${ticket.blocked_reason}`));
    if (!groups.some(([, items]) => items.length) && !(ticket.blockers || []).length && !ticket.blocked_reason) section.append(node("div", "context-note", "Sin relaciones ni bloqueos."));
    return section;
  }

  function sourceChecksSection() {
    const section = drawerSection("Comprobaciones de fuentes");
    const checks = app.context?.source_checks || [];
    const page = app.context?.source_checks_page || {};
    const total = Number.isInteger(page.total) ? page.total : checks.length;
    section.append(node("div", "context-note", `Mostrando ${checks.length} de ${total} observaciones históricas. No demuestran que las fuentes sigan vigentes.`));
    if (!checks.length) return section;
    const list = node("div", "history-list");
    checks.forEach((check) => {
      const item = node("details", "audit-details context-note");
      item.append(node("summary", "", `Comprobación #${check.check_id} · revisión observada ${check.ticket_revision}`));
      item.append(node("p", "", `Snapshot: ${check.snapshot_id || "No indicado"}`));
      item.append(node("p", "", `SHA-256 del informe: ${check.report_sha256 || "No indicado"}`));
      if (typeof check.ticket_revision_matches_now === "boolean") {
        item.append(node("p", "", check.ticket_revision_matches_now ? "La revisión observada coincide con la revisión actual." : "La revisión observada no coincide con la revisión actual."));
      }
      if (check.summary && typeof check.summary === "object") {
        const labels = { total: "total", unchanged: "sin cambios", modified: "modificados", missing: "ausentes", uncheckable: "no comprobables" };
        const parts = Object.keys(labels)
          .filter((key) => Number.isInteger(check.summary[key]))
          .map((key) => `${labels[key]}: ${check.summary[key]}`);
        if (parts.length) item.append(node("p", "", `Resumen: ${parts.join(" · ")}`));
      }
      if (check.checked_at) item.append(node("time", "", `Comprobado: ${formatDate(check.checked_at)}`));
      list.append(item);
    });
    section.append(list);
    return section;
  }

  function evidenceSection(ticket) {
    const section = drawerSection("Resultado y evidencia");
    if (ticket.checkpoint) {
      section.append(node("h4", "", "Último resumen"));
      section.append(node("div", "context-note", ticket.checkpoint));
    }
    const evidence = ticket.evidence || [];
    if (evidence.length) {
      const list = node("div", "evidence-list");
      evidence.forEach((item) => {
        const row = node("div", "evidence-item");
        row.append(node("strong", "", `${item.label || "Evidencia"} · ${item.kind || "referencia"}`), node("small", "", item.uri || "Sin URI"));
        list.append(row);
      });
      section.append(list);
    } else if (!ticket.checkpoint) section.append(node("div", "context-note", "Todavía no se ha aportado evidencia."));
    return section;
  }

  function contextSection() {
    const section = drawerSection("Contexto e historial");
    if (app.context?.instructions) {
      section.append(node("h4", "", "Instrucciones"));
      section.append(node("div", "context-note", typeof app.context.instructions === "string" ? app.context.instructions : JSON.stringify(app.context.instructions, null, 2)));
    }
    const events = app.context?.events || [];
    if (!events.length) section.append(node("div", "context-note", "No hay eventos para esta tarea."));
    else {
      const list = node("div", "history-list");
      events.forEach((event) => {
        const item = node("div", "history-item");
        item.append(node("strong", "", `${event.actor || "sistema"} · ${ACTION[event.action] || event.action || "Evento"}`), node("p", "", describeDetails(event.details, event.action)), node("time", "", formatDate(event.created_at)));
        const raw = auditDetails(event.details);
        if (raw) item.append(raw);
        list.append(item);
      });
      section.append(list);
    }
    return section;
  }

  function openProfile(profile = null) {
    const form = $("#profile-form");
    form.reset();
    app.dialogDirty = false;
    $("#profile-dialog-title").textContent = profile ? "Editar perfil" : "Nuevo perfil";
    ["id", "name", "role", "provider", "model", "effort", "preference", "description"].forEach((name) => {
      form.elements[name].value = profile?.[name] || (name === "preference" ? "balanced" : name === "effort" ? "default" : "");
    });
    form.elements.capabilities.value = (profile?.capabilities || []).join(", ");
    $("#profile-dialog").showModal();
  }

  async function exportJson() {
    const scope = captureWorkspace();
    const workspace = activeWorkspace();
    try {
      const response = await fetch("/api/export", { headers: workspaceHeaders(scope) });
      if (!isCurrentWorkspace(scope)) return;
      if (!response.ok) {
        let message = `La exportación falló (${response.status})`;
        try { message = (await response.json()).error || message; } catch (_) { /* non-JSON error */ }
        throw new Error(message);
      }
      const blob = await response.blob();
      if (!isCurrentWorkspace(scope)) return;
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `agentrelay-${fileSlug(workspace?.name)}-${new Date().toISOString().slice(0, 10)}.json`;
      document.body.append(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      toast(`Exportación de ${workspace?.name || "proyecto"} preparada`);
    } catch (error) {
      if (isCurrentWorkspace(scope)) toast(error.message, true);
    }
  }

  function wireEvents() {
    document.addEventListener("click", (event) => {
      const nav = event.target.closest("[data-nav]");
      if (nav) { event.preventDefault(); showSection(nav.dataset.nav); return; }
      const card = event.target.closest("[data-ticket-id]");
      if (card) { openTicket(card.dataset.ticketId); return; }
      const editProfile = event.target.closest("[data-edit-profile]");
      if (editProfile) openProfile(profileById(editProfile.dataset.editProfile));
    });
    ["search-filter", "priority-filter", "profile-filter", "status-filter"].forEach((id) => $("#" + id).addEventListener(id === "search-filter" ? "input" : "change", () => { renderBoard(); renderList(); }));
    $("#workspace-select").addEventListener("change", (event) => selectWorkspace(event.currentTarget.value));
    $$('[data-display]').forEach((button) => button.addEventListener("click", () => setDisplay(button.dataset.display)));
    $("#new-ticket-button").addEventListener("click", () => { $("#ticket-create-form").reset(); app.dialogDirty = false; syncGlobalSelects(); $("#ticket-dialog").showModal(); });
    $("#new-profile-button").addEventListener("click", () => openProfile());
    $("#export-button").addEventListener("click", exportJson);
    $("#refresh-button").addEventListener("click", () => loadState());
    $("#refresh-executions-button").addEventListener("click", () => loadState());
    $("#scrim").addEventListener("click", closeTicket);
    $("[data-close]").addEventListener("click", closeTicket);
    document.addEventListener("keydown", (event) => { if (event.key === "Escape" && app.selectedId) closeTicket(); });

    $("#ticket-create-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (event.submitter?.value === "cancel") { app.dialogDirty = false; $("#ticket-dialog").close(); return; }
      const data = new FormData(event.currentTarget);
      try {
        const result = await mutate("create_ticket", {
          title: data.get("title").trim(), description: data.get("description").trim(), type: data.get("type"), priority: data.get("priority"),
          parent_id: data.get("parent_id") || null, profile_id: data.get("profile_id") || null,
          depends_on: values(data.get("depends_on")), acceptance: values(data.get("acceptance"), /\n/)
        }, "Tarea creada");
        app.dialogDirty = false;
        $("#ticket-dialog").close();
        const id = result?.id || result?.ticket?.id;
        if (id) openTicket(id);
      } catch (_) { /* keep form open */ }
    });

    $("#profile-form").addEventListener("submit", async (event) => {
      event.preventDefault();
      if (event.submitter?.value === "cancel") { app.dialogDirty = false; $("#profile-dialog").close(); return; }
      const data = new FormData(event.currentTarget);
      const id = data.get("id");
      const payload = {
        name: data.get("name").trim(), role: data.get("role").trim(), provider: data.get("provider").trim(), model: data.get("model").trim(),
        effort: data.get("effort").trim(), preference: data.get("preference"), capabilities: values(data.get("capabilities")), description: data.get("description").trim()
      };
      if (id) payload.id = id;
      try { await mutate(id ? "update_profile" : "create_profile", payload, id ? "Perfil actualizado" : "Perfil creado"); app.dialogDirty = false; $("#profile-dialog").close(); } catch (_) { /* keep form open */ }
    });
    [$("#ticket-create-form"), $("#profile-form")].forEach((form) => {
      const markDialogDirty = () => { if (form.closest("dialog")?.open) app.dialogDirty = true; };
      form.addEventListener("input", markDialogDirty);
      form.addEventListener("change", markDialogDirty);
    });
    [$("#ticket-dialog"), $("#profile-dialog")].forEach((dialog) => {
      dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
      dialog.addEventListener("close", () => { app.dialogDirty = false; });
    });
  }

  async function boot() {
    try {
      await loadWorkspaceCatalog();
    } catch (error) {
      setConnected(false);
      $("#loading-state").hidden = true;
      $("#workspace-select").disabled = true;
      showError(`No se pudo cargar el catálogo de proyectos. ${error.message}`);
    }
  }

  wireEvents();
  syncWorkspaceControls();
  boot();
  setInterval(() => { if (app.workspaceId) loadState({ quiet: true }); }, 15000);
})();
