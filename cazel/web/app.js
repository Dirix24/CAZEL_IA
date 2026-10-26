"use strict";
/* Interfaz de CAZEL IA. Todo el texto que viene de fuera (Wikipedia, robots,
   archivos) se inserta con textContent: nunca como HTML. */

const TOKEN = document.querySelector('meta[name="cazel-token"]').content;
const $ = (s) => document.querySelector(s);
let estado = null;

function h(etiqueta, props = {}, ...hijos) {
  const el = document.createElement(etiqueta);
  for (const [k, v] of Object.entries(props)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else if (k === "value") el.value = v;
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const hijo of hijos.flat()) {
    if (hijo === null || hijo === undefined || hijo === false) continue;
    el.append(hijo.nodeType ? hijo : document.createTextNode(String(hijo)));
  }
  return el;
}

function poner(el, ...hijos) {
  el.replaceChildren(...hijos.flat(Infinity).filter((x) => x !== null && x !== undefined && x !== false));
}

async function api(accion, datos = {}) {
  let r;
  try {
    r = await fetch("/api/" + accion, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Cazel-Token": TOKEN },
      body: JSON.stringify(datos),
    });
  } catch (e) {
    throw new Error("No puedo hablar con CAZEL. ¿Sigue abierta la ventana negra (terminal)?");
  }
  let cuerpo = {};
  try { cuerpo = await r.json(); } catch (e) { /* respuesta vacía */ }
  if (!r.ok) throw new Error(cuerpo.error || "Error " + r.status);
  return cuerpo;
}

const mb = (b) => (b / (1024 * 1024)).toFixed(b > 1e10 ? 0 : 1) + " MB";
const kb = (b) => (b < 1024 ? b + " B" : (b / 1024).toFixed(b < 10240 ? 1 : 0) + " KB");

/* ---------- chat ---------- */
function mensaje(texto, clase = "ia") {
  const caja = $("#mensajes");
  caja.append(h("div", { class: "msg " + clase }, texto));
  caja.scrollTop = caja.scrollHeight;
}

$("#form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const campo = $("#texto");
  const texto = campo.value.trim();
  if (!texto) return;
  campo.value = "";
  mensaje(texto, "yo");
  try {
    const r = await api("chat", { texto });
    if (r.respuesta) mensaje(r.respuesta);
    if (r.terminar) mensaje("CAZEL se apagó. Ya puedes cerrar esta pestaña.", "sistema");
  } catch (e) { mensaje(e.message, "ia error"); }
  refrescar();
});

/* ---------- barra de estado ---------- */
function chip(clase, texto) { return h("span", { class: "chip " + clase }, h("i"), texto); }

async function refrescar() {
  try {
    const r = await fetch("/api/estado", { headers: { "X-Cazel-Token": TOKEN } });
    if (!r.ok) throw new Error();
    estado = await r.json();
  } catch (e) {
    $("#sub").textContent = "sin conexión con CAZEL";
    return;
  }
  const p = estado.puerta, u = estado.espacio, rb = estado.robot;
  $("#sub").textContent = estado.modelo.cargado
    ? "Cerebro · " + estado.modelo.parametros.toLocaleString("es") + " parámetros"
    : "Cerebro no cargado";
  poner($("#chips"),
    p.abierta ? chip("aviso", "Internet abierto · " + Math.ceil(p.segundos_restantes / 60) + " min")
              : chip("ok", "Wikipedia cerrada"),
    chip(u.alerta ? "aviso" : "ok", "USB " + u.porcentaje_usado + " % · " + mb(u.libre) + " libres"),
    rb.conectado ? chip("ok", "Robot: " + rb.nombre) : chip("", "Sin robot"),
    estado.cuarentena ? chip("aviso", estado.cuarentena + " por revisar") : null,
  );
  $("#btn-parar").classList.toggle("oculto", !rb.conectado);
}

$("#btn-parar").addEventListener("click", async () => {
  try { mensaje((await api("robots_parar")).texto, "sistema"); } catch (e) { mensaje(e.message, "ia error"); }
});

/* ---------- menú ⋮ ---------- */
const menu = $("#menu"), btnMenu = $("#btn-menu");
function menuAbierto(v) {
  menu.classList.toggle("oculto", !v);
  btnMenu.setAttribute("aria-expanded", String(v));
  if (v) menu.querySelector("button").focus();
}
btnMenu.addEventListener("click", (e) => { e.stopPropagation(); menuAbierto(menu.classList.contains("oculto")); });
document.addEventListener("click", (e) => { if (!menu.contains(e.target)) menuAbierto(false); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") menuAbierto(false); });
menu.addEventListener("click", (e) => {
  const b = e.target.closest("button[data-panel]");
  if (!b) return;
  menuAbierto(false);
  const f = PANELES[b.dataset.panel];
  if (f) f();
});

/* ---------- paneles ---------- */
const dlg = $("#panel");
function abrirPanel(titulo, nota) {
  const cont = h("div", { class: "panel" },
    h("button", { class: "btn sec chico cierra", onclick: () => dlg.close() }, "Cerrar"),
    h("h2", {}, titulo), nota ? h("p", { class: "nota" }, nota) : null);
  $("#panel-contenido").replaceChildren(cont);
  if (!dlg.open) dlg.showModal();
  return cont;
}
dlg.addEventListener("click", (e) => { if (e.target === dlg) dlg.close(); });
dlg.addEventListener("close", refrescar);

function estadoTexto(el, texto, clase) {
  el.className = clase || "";
  el.textContent = texto || "";
}
async function intentar(zona, fn) {
  try { return await fn(); } catch (e) { estadoTexto(zona, e.message, "error-txt"); return null; }
}

/* ----- Robótica ----- */
async function panelRobotica() {
  const cont = abrirPanel("Escanear placas y componentes",
    "Escanear identifica puertos USB serie y algunas placas por sus IDs. «Detectar» consulta AYUDA para listar " +
    "órdenes y sensores que el firmware del robot anuncie. Los componentes conectados no siempre son visibles " +
    "sin firmware o un bus compatible.");
  const msg = h("p", { class: "nota" });
  const lista = h("div");
  const control = h("div");
  const perfiles = h("div");
  const autoconectar = h("input", { type: "checkbox" });
  cont.append(
    h("div", { class: "fila" },
      h("button", { class: "btn", onclick: escanear }, "Escanear placas y puertos"),
      h("button", { class: "btn sec", onclick: pintarControl }, "Actualizar")),
    h("label", { class: "linea" }, autoconectar, h("span", {}, "Conectar automáticamente si responde CAZEL-1; puede reiniciar placas al abrir el puerto.")),
    msg, lista, h("h3", {}, "Robot conectado"), control, h("h3", {}, "Perfiles guardados"), perfiles);

  async function escanear() {
    estadoTexto(msg, "Escaneando…");
    const r = await intentar(msg, () => api("robots_escanear"));
    if (!r) return;
    estadoTexto(msg, r.puertos.length + " puerto(s) encontrado(s).");
    lista.replaceChildren(...r.puertos.map((p) => {
      const info = h("small", {});
      const tarjeta = h("div", { class: "tarjeta" },
        h("h4", {}, p.puerto), h("small", {}, p.descripcion),
        h("div", { class: "fila" },
          h("button", { class: "btn chico", onclick: async () => {
            estadoTexto(info, "Preguntando AYUDA…");
            const d = await intentar(info, () => api("robots_detectar", { puerto: p.puerto }));
            if (!d) return;
            if (!d.encontrado) {
              estadoTexto(info, "No respondió como robot CAZEL (" + d.motivo + "). Prueba «Adaptar con mi código» en el menú ⋮.", "aviso");
              return;
            }
            const pf = d.perfil;
            estadoTexto(info, "Encontré «" + pf.nombre + "» — órdenes: " + Object.keys(pf.ordenes).join(", ") +
              (Object.keys(pf.lecturas).length ? " · sensores: " + Object.keys(pf.lecturas).join(", ") : ""), "ok-txt");
          } }, "Detectar"),
          h("button", { class: "btn chico sec", onclick: async () => {
            estadoTexto(info, "Conectando…");
            const r2 = await intentar(info, () => api("robots_conectar", { puerto: p.puerto }));
            if (r2) { estadoTexto(info, "Conectado a «" + r2.nombre + "».", "ok-txt"); await refrescar(); pintarControl(); pintarPerfiles(); }
          } }, "Conectar")),
        info);
      return tarjeta;
    }));
    if (autoconectar.checked) {
      for (const p of r.puertos.filter((x) => x.puerto !== "simulado")) {
        estadoTexto(msg, "Buscando protocolo CAZEL-1 en " + p.puerto + "…");
        const d = await intentar(msg, () => api("robots_detectar", { puerto: p.puerto }));
        if (!d || !d.encontrado) continue;
        const guardado = await intentar(msg, () => api("robots_guardar", { perfil: d.perfil }));
        if (!guardado) continue;
        const con = await intentar(msg, () => api("robots_conectar", { puerto: p.puerto, perfil: d.perfil.nombre }));
        if (con) {
          estadoTexto(msg, "Conectado a " + d.perfil.nombre + " en " + p.puerto + ". Sensores: " +
            (Object.keys(d.perfil.lecturas || {}).join(", ") || "el firmware no declaró sensores"), "ok-txt");
          await refrescar(); pintarControl(); pintarPerfiles(); return;
        }
      }
      estadoTexto(msg, "No encontré una placa CAZEL-1 compatible. Otras placas necesitan un firmware/adaptador.", "aviso");
    }
  }

  async function pintarControl() {
    await refrescar();
    const rb = estado.robot;
    if (!rb.conectado) { control.replaceChildren(h("p", { class: "nota" }, "Ningún robot conectado.")); return; }
    const filas = [];
    filas.push(h("div", { class: "fila" },
      h("strong", {}, rb.nombre + " en " + rb.puerto),
      h("button", { class: "btn peligro chico", onclick: async () => {
        const r = await intentar(msg, () => api("robots_parar")); if (r) estadoTexto(msg, r.texto, "ok-txt"); } }, "PARAR"),
      h("button", { class: "btn sec chico", onclick: async () => {
        await intentar(msg, () => api("robots_desconectar")); await refrescar(); pintarControl(); } }, "Desconectar")));
    for (const [n, s] of Object.entries(rb.ordenes)) {
      if (n === "parar") continue;
      const campo = s.parametro ? h("input", { type: "number", step: "any", min: s.min, max: s.max,
        placeholder: s.parametro + " (" + s.min + " a " + s.max + ")", "aria-label": n + " " + s.parametro }) : null;
      const sal = h("small", {});
      filas.push(h("div", { class: "tarjeta" },
        h("h4", {}, n), h("div", { class: "fila" }, campo,
          h("button", { class: "btn chico", onclick: async () => {
            const r = await intentar(sal, () => api("robots_orden", { nombre: n, valor: campo ? campo.value : null }));
            if (r) estadoTexto(sal, r.texto, "ok-txt"); } }, "Enviar")), sal));
    }
    for (const [n, s] of Object.entries(rb.lecturas)) {
      const sal = h("small", {});
      filas.push(h("div", { class: "tarjeta" }, h("h4", {}, "Sensor: " + n),
        h("div", { class: "fila" }, h("button", { class: "btn chico sec", onclick: async () => {
          const r = await intentar(sal, () => api("robots_leer", { nombre: n }));
          if (r) estadoTexto(sal, r.texto, "ok-txt"); } }, "Leer " + (s.unidad || ""))), sal));
    }
    control.replaceChildren(...filas);
  }

  async function pintarPerfiles() {
    const r = await intentar(msg, () => api("robots_perfiles"));
    if (!r) return;
    perfiles.replaceChildren(...(r.perfiles.length ? r.perfiles.map((p) => h("div", { class: "tarjeta" },
      h("h4", {}, p.nombre), h("small", {}, "Origen: " + p.origen + " · órdenes: " + Object.keys(p.ordenes).join(", ")),
      h("div", { class: "fila" }, h("button", { class: "btn sec chico", onclick: async () => {
        if (!confirm("¿Borrar el perfil «" + p.nombre + "»?")) return;
        await intentar(msg, () => api("robots_borrar", { nombre: p.nombre })); pintarPerfiles(); } }, "Borrar"))))
      : [h("p", { class: "nota" }, "Todavía no hay perfiles guardados.")]));
  }
  pintarControl(); pintarPerfiles(); escanear();
}

/* ----- Adaptar con mi código ----- */
function panelCodigo() {
  const cont = abrirPanel("Adaptar con mi código",
    "Pega código de Arduino y placas compatibles. El análisis se hace localmente por reglas; identifica pines, " +
    "sensores, librerías y familias de placa, y genera un " +
    "«adaptador» para que tu robot hable con CAZEL. CAZEL nunca sube nada a tu placa: lo subes tú con el Arduino IDE.");
  const codigo = h("textarea", { placeholder: "// pega aquí tu sketch (.ino)", spellcheck: "false", "aria-label": "Código del Arduino" });
  const nombre = h("input", { type: "text", value: "mi_robot", maxlength: "24", "aria-label": "Nombre del robot" });
  const msg = h("p", { class: "nota" });
  const salida = h("div");
  cont.append(codigo,
    h("div", { class: "fila" }, h("label", {}, "Nombre del robot: "), nombre,
      h("button", { class: "btn", onclick: analizar }, "Analizar y generar adaptador"),
      h("button", { class: "btn sec", onclick: () => cargarArchivo() }, "Abrir archivo .ino")),
    msg, salida);

  function cargarArchivo() {
    const f = h("input", { type: "file", accept: ".ino,.cpp,.c,.h,.txt" });
    f.addEventListener("change", async () => {
      const a = f.files[0];
      if (!a) return;
      if (a.size > 200000) { estadoTexto(msg, "El archivo es demasiado grande (máximo 200 KB).", "error-txt"); return; }
      codigo.value = await a.text();
    });
    f.click();
  }

  async function analizar() {
    estadoTexto(msg, "Analizando…");
    const r = await intentar(msg, () => api("codigo_adaptador", { codigo: codigo.value, nombre: nombre.value }));
    if (!r) return;
    estadoTexto(msg, "Listo. Revisa lo que encontré antes de usar el adaptador.", "ok-txt");
    const i = r.informe, plan = i.plan, items = [];
    plan.servos.forEach((s) => items.push("Servo «" + s.variable + "» en el pin " + s.pin + " → orden " + s.orden + " (0–180°)"));
    plan.pwm.forEach((p) => items.push("Salida PWM en el pin " + p.pin + " → orden " + p.orden + " (0–255)"));
    plan.digitales.forEach((p) => items.push("Salida digital en el pin " + p.pin + " → orden " + p.orden + " (0 ó 1)"));
    plan.lecturas_analogicas.forEach((p) => items.push("Lectura analógica en " + p.pin + " → sensor " + p.lectura));
    if (plan.ultrasonico) items.push("Sensor ultrasónico (trig " + plan.ultrasonico.trig + ", echo " + plan.ultrasonico.echo + ") → sensor distancia (cm)");
    poner(salida,
      h("h3", {}, "Lo que encontré"),
      h("p", { class: "nota" }, "Placa(s) probable(s): " + (i.placas_probables || ["sin identificar"]).join(", ")),
      items.length ? h("ul", {}, items.map((t) => h("li", {}, t))) : h("p", { class: "aviso" }, "No encontré pines ni servos."),
      i.librerias.length ? h("p", { class: "nota" }, "Librerías: " + i.librerias.map((l) => l.nombre + (l.descripcion ? " (" + l.descripcion + ")" : "")).join(", ")) : null,
      ...i.notas.map((n) => h("p", { class: "aviso" }, "⚠ " + n)),
      h("h3", {}, "Adaptador para el Arduino"),
      h("ol", {},
        h("li", {}, "Copia o descarga el sketch de abajo."),
        h("li", {}, "Ábrelo en el Arduino IDE y COMPRUEBA que cada pin es el de tu montaje."),
        h("li", {}, "Súbelo a la placa tú mismo."),
        h("li", {}, "Vuelve a «Escanear robótica» → Detectar: ahora el robot se presentará solo.")),
      h("div", { class: "fila" },
        h("button", { class: "btn sec chico", onclick: async () => {
          try { await navigator.clipboard.writeText(r.sketch); estadoTexto(msg, "Copiado.", "ok-txt"); }
          catch (e) { estadoTexto(msg, "No pude copiar; selecciona el texto a mano.", "aviso"); } } }, "Copiar"),
        h("button", { class: "btn sec chico", onclick: () => {
          const a = h("a", { href: URL.createObjectURL(new Blob([r.sketch], { type: "text/plain" })),
            download: nombre.value + "_cazel.ino" });
          a.click(); URL.revokeObjectURL(a.href); } }, "Descargar .ino")),
      h("pre", { class: "codigo" }, r.sketch));
  }
}

/* ----- Análisis de proyectos multilenguaje ----- */
function panelProyecto() {
  const cont = abrirPanel("Analizar código y proyectos",
    "Selecciona varios archivos de código para un análisis local sin conexión. Busca familias de placas, " +
    "librerías, componentes y señales de riesgo en Python, C/C++, Arduino, JavaScript, Rust y archivos de configuración. " +
    "Es un análisis heurístico: no compila ni cambia los archivos.");
  const msg = h("p", { class: "nota" }), out = h("div");
  const pick = h("input", { type: "file", multiple: true,
    accept: ".ino,.cpp,.c,.h,.hpp,.py,.js,.ts,.java,.rs,.pde,.yaml,.yml,.toml,.md,.xml,.txt" });
  const abrir = h("button", { class: "btn sec", onclick: () => pick.click() }, "Elegir archivos del proyecto");
  pick.addEventListener("change", async () => {
    const fs = [...pick.files].slice(0, 24);
    let total = 0;
    const archivos = [];
    for (const f of fs) {
      if (total >= 150000) break;
      const texto = (await f.text()).slice(0, 40000);
      total += texto.length;
      archivos.push({ ruta: f.webkitRelativePath || f.name, texto });
    }
    estadoTexto(msg, "Analizando " + archivos.length + " archivo(s) localmente…");
    const r = await intentar(msg, () => api("proyecto_archivos", { archivos }));
    if (r) mostrarInforme(out, r, archivos);
  });
  cont.append(h("div", { class: "fila" }, abrir), msg, out);
}

function mostrarInforme(out, r, archivos = []) {
  const partes = ["Encontré " + r.cantidad + " archivos y " + r.lineas + " líneas.",
    "Placas/plataformas probables: " + r.placas.join(", "),
    "Componentes o buses por indicios: " + r.componentes.join(", "),
    "Dependencias: " + (r.dependencias.length ? r.dependencias.join(", ") : "sin identificar")];
  const items = r.archivos.map((f) => h("div", { class: "tarjeta" },
    h("strong", {}, f.ruta + " · " + f.lineas + " líneas"),
    f.funciones.length ? h("p", { class: "nota" }, "Funciones: " + f.funciones.join(", ")) : null,
    ...f.avisos.map((a) => h("p", { class: "aviso" }, "⚠ " + a))));
  const sugerencias = (r.mejoras || []).map((m) => h("div", { class: "tarjeta" },
    h("strong", {}, m.nivel.toUpperCase() + " · " + m.ruta + (m.linea ? ":" + m.linea : "")),
    h("p", {}, m.mensaje), m.propuesta ? h("p", { class: "nota" }, "Propuesta: " + m.propuesta) : null));
  poner(out, h("div", { class: "tarjeta" }, partes.map((x) => h("p", {}, x)), h("p", { class: "nota" }, r.nota)),
    ...items, h("h3", {}, "Mejoras sugeridas"),
    ...(sugerencias.length ? sugerencias : [h("p", { class: "nota" }, "No encontré patrones de riesgo conocidos; revisa el proyecto de todas formas.") ]));
}

/* ----- Repositorio GitHub público ----- */
function panelGitHub() {
  const cont = abrirPanel("Leer un repositorio GitHub",
    "Pega la página principal de un repositorio público. CAZEL leerá un conjunto limitado de archivos fuente " +
    "a través de la API pública de GitHub, sin ejecutar, enviar a otro modelo ni modificar nada. El análisis se hace " +
    "localmente mediante las reglas de Cerebro.");
  const url = h("input", { type: "url", placeholder: "https://github.com/usuario/proyecto", maxlength: "300", "aria-label": "URL del repositorio" });
  const msg = h("p", { class: "nota" }), out = h("div");
  const revisar = async (ev) => {
    ev.preventDefault();
    estadoTexto(msg, "Leyendo solo archivos fuente públicos…");
    const r = await intentar(msg, () => api("repositorio_github", { url: url.value }));
    if (!r) return;
    estadoTexto(msg, "Lectura completada: " + r.repositorio + " · rama " + r.rama + " · " + r.informe.cantidad + " archivos.", "ok-txt");
    mostrarInforme(out, r.informe);
    if (r.truncado) out.prepend(h("p", { class: "aviso" }, "GitHub indicó que el árbol del repositorio es muy grande; el análisis puede estar incompleto."));
  };
  cont.append(h("form", { class: "fila", onsubmit: revisar }, url, h("button", { class: "btn", type: "submit" }, "Leer y analizar")),
    msg, out);
}

/* ----- Internet y biblioteca ----- */
async function panelInternet() {
  const cont = abrirPanel("Internet y biblioteca",
    "La puerta de Wikipedia está cerrada por defecto. Al abrirla puede buscar y traer artículos durante unos minutos. " +
    "GitHub tiene una acción aparte de solo lectura para repositorios públicos. Lo que viene de Wikipedia va a cuarentena " +
    "y solo pasa a la biblioteca si tú lo apruebas.");
  const msg = h("p", { class: "nota" });
  const zonaPuerta = h("div"), zonaBus = h("div"), zonaCuar = h("div"), zonaBib = h("div"), vista = h("pre", { class: "codigo oculto" });
  const consulta = h("input", { type: "text", placeholder: "Tema para buscar en Wikipedia", maxlength: "200", "aria-label": "Buscar en Wikipedia" });
  const minutos = h("select", { "aria-label": "Minutos de permiso" }, [5, 15, 30, 60].map((m) => h("option", { value: m, selected: m === 15 }, m + " min")));

  cont.append(zonaPuerta, msg,
    h("h3", {}, "Buscar en Wikipedia"),
    h("form", { class: "fila", onsubmit: async (ev) => {
      ev.preventDefault();
      estadoTexto(msg, "Buscando…");
      const r = await intentar(msg, () => api("wiki_buscar", { consulta: consulta.value }));
      if (!r) return;
      estadoTexto(msg, r.resultados.length ? "" : "Sin resultados.");
      zonaBus.replaceChildren(...r.resultados.map((x) => h("div", { class: "tarjeta" },
        h("h4", {}, x.titulo), h("small", {}, x.resumen),
        h("div", { class: "fila" }, h("button", { class: "btn chico", type: "button", onclick: async () => {
          estadoTexto(msg, "Descargando a la cuarentena…");
          const t = await intentar(msg, () => api("wiki_traer", { titulo: x.titulo, idioma: x.idioma }));
          if (t) { estadoTexto(msg, "«" + t.titulo + "» está en la cuarentena. Revísalo abajo.", "ok-txt"); pintar(); refrescar(); } } }, "Traer a cuarentena")))));
    } }, consulta, h("button", { class: "btn", type: "submit" }, "Buscar")),
    zonaBus,
    h("h3", {}, "Cuarentena (sin revisar)"), zonaCuar, vista,
    h("h3", {}, "Mi biblioteca (aprobado)"), zonaBib);

  async function pintar() {
    await refrescar();
    const p = estado.puerta;
    zonaPuerta.replaceChildren(h("div", { class: "fila" },
      p.abierta ? chip("aviso", "Puerta abierta · " + Math.ceil(p.segundos_restantes / 60) + " min · " + p.peticiones_usadas + "/" + p.peticiones_max + " peticiones")
                : chip("ok", "Puerta cerrada: en casa"),
      p.abierta ? h("button", { class: "btn sec chico", onclick: async () => { await intentar(msg, () => api("puerta", { accion: "cerrar" })); pintar(); } }, "Volver a casa")
                : [minutos, h("button", { class: "btn chico", onclick: async () => {
                    await intentar(msg, () => api("puerta", { accion: "abrir", minutos: Number(minutos.value) })); pintar(); } }, "Dar permiso de internet")]));
    const c = await api("cuarentena"), b = await api("biblioteca");
    zonaCuar.replaceChildren(...(c.archivos.length ? c.archivos.map((a) => h("div", { class: "tarjeta" },
      h("h4", {}, a.titulo), h("small", {}, a.archivo + " · " + kb(a.bytes) + (a.fuente ? " · " + a.fuente : "")),
      h("div", { class: "fila" },
        h("button", { class: "btn sec chico", onclick: async () => {
          const v = await intentar(msg, () => api("cuarentena_ver", { archivo: a.archivo }));
          if (v) { vista.textContent = v.texto; vista.classList.remove("oculto"); vista.scrollIntoView({ block: "nearest" }); } } }, "Ver"),
        h("button", { class: "btn chico", onclick: async () => { await intentar(msg, () => api("aprobar", { archivo: a.archivo })); vista.classList.add("oculto"); pintar(); } }, "Aprobar"),
        h("button", { class: "btn peligro chico", onclick: async () => { await intentar(msg, () => api("rechazar", { archivo: a.archivo })); vista.classList.add("oculto"); pintar(); } }, "Rechazar"))))
      : [h("p", { class: "nota" }, "La cuarentena está vacía.")]));
    zonaBib.replaceChildren(...(b.archivos.length ? b.archivos.map((a) => h("div", { class: "tarjeta" },
      h("h4", {}, a.titulo), h("small", {}, kb(a.bytes) + (a.fuente ? " · " + a.fuente : ""))))
      : [h("p", { class: "nota" }, "Aún no aprobaste ningún texto.")]));
  }
  pintar();
}

/* ----- Espacio ----- */
async function panelEspacio() {
  const cont = abrirPanel("Espacio del USB",
    "Nunca se toca el modelo, la biblioteca aprobada, los perfiles de robots ni los ajustes. Con el USB casi lleno, " +
    "puede olvidar automáticamente recuerdos triviales; los recuerdos importantes y personales se conservan. " +
    "Los demás elementos se borran solo cuando los marcas y confirmas.");
  const msg = h("p", { class: "nota" }), zona = h("div");
  cont.append(msg, zona);
  async function pintar() {
    const r = await intentar(msg, () => api("espacio"));
    if (!r) return;
    const u = r.uso, marcas = new Map();
    const filas = r.candidatos.map((c) => {
      const cb = h("input", { type: "checkbox", checked: c.seguro_auto });
      marcas.set(c.id, cb);
      return h("label", { class: "linea" }, cb, h("span", {}, h("strong", {}, c.accion + " · " + (c.tipo === "recuerdo" ? "recuerdo" : c.ruta)),
        h("br"), h("small", {}, c.motivo + (c.bytes ? " (" + kb(c.bytes) + ")" : ""))));
    });
    poner(zona,
      h("div", { class: "barra-uso" + (u.alerta ? " alerta" : "") }, (() => { const r = h("div"); r.style.width = Math.min(100, u.porcentaje_usado) + "%"; return r; })()),
      h("p", {}, u.porcentaje_usado + " % usado · " + mb(u.libre) + " libres de " + mb(u.total) + ". " + u.mensaje),
      r.candidatos.length ? [h("h3", {}, "Se puede liberar (" + kb(r.bytes_liberables) + ")"), ...filas,
        h("div", { class: "fila" }, h("button", { class: "btn", onclick: async () => {
          const ids = [...marcas].filter(([, cb]) => cb.checked).map(([id]) => id);
          if (!ids.length) { estadoTexto(msg, "No marcaste nada.", "aviso"); return; }
          if (!confirm("¿Liberar " + ids.length + " elemento(s)? Los borrados no se pueden recuperar.")) return;
          const x = await intentar(msg, () => api("espacio_liberar", { ids, confirmado: true }));
          if (x) { estadoTexto(msg, "Liberé " + kb(x.liberado) + (x.errores.length ? " (con " + x.errores.length + " error/es)" : "") + ".", "ok-txt"); pintar(); } } }, "Liberar lo marcado"))]
        : h("p", { class: "nota" }, "No hay nada que liberar por ahora."));
  }
  pintar();
}

/* ----- Diario ----- */
async function panelDiario() {
  const cont = abrirPanel("Diario y entrenamiento",
    "Cada conversación se anota en el diario. Puedes exportarla como borrador de diálogos para entrenar a Cerebro; " +
    "tú decides qué se copia a su corpus (así no aprende nada sin que lo revises).");
  const msg = h("p", { class: "nota" }), zona = h("div");
  cont.append(h("div", { class: "fila" }, h("button", { class: "btn", onclick: async () => {
    const r = await intentar(msg, () => api("diario_exportar"));
    if (r) estadoTexto(msg, r.pares ? "Preparé " + r.pares + " diálogos en «" + r.archivo + "» para que los revises." : "Todavía no hay diálogos que exportar.", r.pares ? "ok-txt" : "aviso"); } }, "Exportar para revisar")), msg, h("h3", {}, "Últimos mensajes"), zona);
  const r = await intentar(msg, () => api("diario_ultimos"));
  if (r) zona.replaceChildren(...(r.filas.length ? r.filas.map((f) => h("p", {}, h("small", {}, f.dia + " " + f.t + " · " + f.rol + ": "), f.texto)) : [h("p", { class: "nota" }, "El diario está vacío.")]));
}

function panelAyuda() {
  const cont = abrirPanel("Ayuda");
  cont.append(
    h("h3", {}, "Qué es CAZEL IA"),
    h("p", {}, "Una IA portátil que vive en tu USB. Usa a Cerebro (un modelo de lenguaje pequeño hecho desde cero) como cerebro, " +
      "y esta interfaz como cuerpo: memoria, puerta controlada a Wikipedia, biblioteca, gestor de espacio y control de robots."),
    h("h3", {}, "Lo que sí y lo que no"),
    h("ul", {},
      h("li", {}, "Sí: análisis heurístico local de proyectos con varios archivos, familias de placas, dependencias y componentes comunes; lectura limitada de repositorios GitHub públicos."),
      h("li", {}, "El cerebro incluido es pequeño: el análisis de código local detecta patrones y sugiere mejoras conocidas, pero no entiende cualquier proyecto ni compila el código."),
      h("li", {}, "No: no ve imágenes ni oye audio todavía. Eso necesita módulos aparte."),
      h("li", {}, "Fuera de su corpus, Cerebro responde con seguridad pero sin sentido: para datos reales usa la biblioteca (investiga ...).")),
    h("h3", {}, "Frases útiles"),
    h("ul", {},
      h("li", {}, "/ayuda · /internet · /casa · /wiki tema · /traer título · /cuarentena · /aprobar archivo"),
      h("li", {}, "Menú → Analizar código y proyectos: elige varios archivos para un informe local"),
      h("li", {}, "Menú → Repositorio GitHub: pega una URL pública; no escribe ni sube cambios"),
      h("li", {}, "investiga robots → busca en tu biblioteca aprobada"),
      h("li", {}, "/robots · /detectar puerto · /conectar puerto · /orden avanzar 20 · /sensor distancia"),
      h("li", {}, "«para», «stop» o el botón rojo PARAR detienen el robot al instante")));
}

function panelApagar() {
  if (!confirm("¿Apagar CAZEL? Se enviará PARAR al robot y se cerrará la puerta de internet.")) return;
  api("apagar").then(() => {
    mensaje("CAZEL se apagó. Ya puedes cerrar esta pestaña y quitar el USB con seguridad.", "sistema");
    $("#texto").disabled = true;
    $("#chips").replaceChildren(chip("", "Apagado"));
  }).catch((e) => mensaje(e.message, "ia error"));
}

const PANELES = { robotica: panelRobotica, proyecto: panelProyecto, codigo: panelCodigo,
  github: panelGitHub, internet: panelInternet,
  espacio: panelEspacio, diario: panelDiario, ayuda: panelAyuda, apagar: panelApagar };

/* ---------- arranque ---------- */
mensaje("Hola, soy CAZEL IA. Puedo analizar proyectos localmente, escanear placas serie, leer repositorios públicos " +
  "de GitHub cuando lo pidas, o buscar en Wikipedia con permiso.", "sistema");
refrescar();
setInterval(refrescar, 5000);
$("#texto").focus();
