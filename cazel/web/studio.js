"use strict";

const el = id => document.getElementById(id);
const token = document.querySelector('meta[name="cazel-token"]').content;
let session = "";
let polling = false;
let changesKey = "";

async function api(action, data = {}) {
  const response = await fetch("/api/core2/" + action, {
    method: "POST",
    headers: {"Content-Type": "application/json", "X-Cazel-Token": token},
    body: JSON.stringify({session, ...data})
  });
  const answer = await response.json();
  if (!response.ok) throw new Error(answer.error || "Error de CAZEL.");
  return answer;
}

function element(tag, text) {
  const result = document.createElement(tag);
  result.textContent = text;
  return result;
}

function error(message) {
  el("state").textContent = message;
  el("state").classList.add("error");
}

function bind(id, callback, type = "click") {
  el(id).addEventListener(type, async () => {
    try { await callback(); }
    catch (problem) { error(problem.message); }
  });
}

async function sessions() {
  const choices = await api("sessions");
  const select = el("sessions");
  select.replaceChildren(new Option("Seleccionar sesión", ""));
  for (const item of choices) select.add(new Option(item.project + " · " + item.session.slice(0, 6), item.session));
  select.value = session;
}

async function files() {
  const selected = session;
  const names = await api("files");
  if (selected !== session) return;
  const list = el("files");
  list.replaceChildren();
  for (const path of names) {
    const button = element("button", path);
    button.addEventListener("click", async () => {
      try {
        const content = await api("read", {path});
        if (selected !== session) return;
        el("path").value = path;
        el("code").value = content.content;
        highlight();
      } catch (problem) { error(problem.message); }
    });
    list.append(button);
  }
}

function highlight() {
  const view = el("syntax");
  const tokens = el("code").value.split(/\b(def|class|return|import|from|async|await|if|else|const|let|function|fn|pub|int|void|public|throw)\b/g);
  view.replaceChildren();
  tokens.forEach((part, index) => {
    if (index % 2) {
      const mark = element("span", part);
      mark.className = "keyword";
      view.append(mark);
    } else view.append(document.createTextNode(part));
  });
}

function renderChanges(changes) {
  const key = JSON.stringify(changes.map(c => [c.id, c.state]));
  if (changesKey === key) return;
  changesKey = key;
  const list = el("changes");
  list.replaceChildren();
  for (const item of changes) {
    const article = element("article", "");
    const details = element("details", "");
    details.open = item.state === "pending";
    const states = {pending:"Pendiente", applying:"Aplicación interrumpida", applied:"Aplicado",
                    rejected:"Rechazado", undoing:"Restauración interrumpida", undone:"Deshecho"};
    details.append(element("summary", item.path + " · " + (states[item.state] || item.state)));
    const diff = element("pre", "");
    for (const line of item.diff.split("\n").slice(0, 3000)) {
      const span = element("span", line + "\n");
      if (line.startsWith("+")) span.className = "addition";
      if (line.startsWith("-")) span.className = "removal";
      diff.append(span);
    }
    details.append(diff);
    article.append(details);
    const actions = {
      pending: [["accept", "Aceptar"], ["reject", "Rechazar"]],
      applying: [["accept", "Reintentar aplicación"]],
      applied: [["undo", "Deshacer"]],
      undoing: [["undo", "Reintentar restauración"]]
    };
    for (const [action, label] of actions[item.state] || []) {
      const button = element("button", label);
      button.addEventListener("click", async () => {
        try {
          await api(action, {id: item.id});
          await files();
          await refresh();
        } catch (problem) { error(problem.message); }
      });
      article.append(button);
    }
    list.append(article);
  }
}

function renderEvents(events) {
  const list = el("events");
  list.replaceChildren();
  for (const event of events.slice().reverse()) {
    const message = {
      request: event.text,
      exploration: "Exploración · " + (event.files || []).length + " candidatos",
      plan: (event.steps || []).join(" → "),
      research: "Investigación pública · " + event.repository,
      proposal: "Edición propuesta · " + event.path,
      tool: event.ok ? "Herramienta · " + event.name : event.error,
      model: "Modelo · " + event.mode,
      result: (event.state || "") + " · " + event.summary,
      change: "Cambio · " + event.path + " · " + event.state,
      test: "Pruebas · " + event.state
    }[event.kind];
    list.append(element("li", message || event.kind));
  }
  const test = events.slice().reverse().find(event => event.kind === "test");
  el("console").textContent = test ? test.state + " · código " + test.returncode + "\n" + test.output : "Sin resultados recientes.";
}

async function refresh() {
  if (!session || polling) return;
  polling = true;
  const selected = session;
  try {
    const [status, changes] = await Promise.all([api("status"), api("changes")]);
    if (selected !== session) return;
    el("mode").value = status.mode;
    el("mode").disabled = status.active;
    el("start").disabled = status.active;
    el("test").disabled = status.active;
    el("cancel").disabled = !status.active;
    if (status.active || !el("state").classList.contains("error")) {
      el("state").textContent = status.active ? "Tarea activa" : "Proyecto abierto · " + status.mode;
    }
    renderEvents(status.events);
    renderChanges(changes);
  } finally { polling = false; }
}

async function select(id) {
  if (!id) return;
  session = id;
  changesKey = "";
  el("state").classList.remove("error");
  for (const id of ["path", "code", "prompt"]) el(id).value = "";
  for (const id of ["files", "changes", "events"]) el(id).replaceChildren();
  highlight();
  await files();
  await refresh();
}

function permissions() {
  const testing = el("testing").value;
  const remote = el("remote").checked;
  if (testing === "trusted" && !window.confirm("¿Ejecutar código de pruebas con tus permisos de usuario?")) return null;
  el("remote").checked = false;
  el("testing").value = "";
  return {testing, remote};
}

bind("open", async () => {
  await select((await api("open", {path: el("project").value})).session);
  await sessions();
});
bind("sessions", () => select(el("sessions").value), "change");
bind("research", async () => {
  const url = el("research-url").value;
  if (!url || !window.confirm("¿Consultar este repositorio público en GitHub?")) return;
  const report = await api("research", {url, authorized: true});
  el("research-report").textContent = JSON.stringify(report, null, 2);
  await refresh();
});
bind("refresh", files);
bind("stage", async () => {
  await api("stage", {path: el("path").value, content: el("code").value});
  await refresh();
});
bind("mode", async () => {
  await api("mode", {mode: el("mode").value});
  await refresh();
}, "change");
bind("start", async () => {
  const granted = permissions();
  if (!granted) return;
  el("state").classList.remove("error");
  await api("start", {...granted, prompt: el("prompt").value});
  el("prompt").value = "";
  await refresh();
});
bind("test", async () => {
  const granted = permissions();
  if (granted) {
    el("state").classList.remove("error");
    await api("test", granted);
    await refresh();
  }
});
bind("cancel", () => api("cancel"));
bind("theme", () => {
  const light = document.documentElement.classList.toggle("light");
  localStorage.setItem("cazel-theme", light ? "light" : "dark");
});
bind("code", highlight, "input");
document.documentElement.classList.toggle("light", localStorage.getItem("cazel-theme") === "light");
sessions().catch(problem => error(problem.message));
setInterval(() => refresh().catch(problem => error(problem.message)), 1200);
