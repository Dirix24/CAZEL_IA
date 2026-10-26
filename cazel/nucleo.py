# -*- coding: utf-8 -*-
"""
El núcleo de CAZEL: junta a Cerebro (el modelo), la puerta a Wikipedia, la
biblioteca, el gestor de espacio, el diario y los robots.

La interfaz web (servidor.py) y los comandos del chat llaman SOLO a esta
clase, así todo pasa por los mismos controles.
"""

import importlib
import os
import re
import sys
import threading

from . import config as cfg
from . import motor_externo
from .biblioteca import Biblioteca
from .diario import Diario
from .espacio import GestorEspacio
from .puerta import ErrorPuerta, Puerta
from .robot import analizador
from .robot.control import ErrorRobot, GestorRobots
from .seguridad import Auditoria

MIN_LIBRE_DESCARGA = 5 * 1024 * 1024        # no se descarga nada con menos de 5 MB libres

AYUDA_CAZEL = """Comandos de CAZEL:
  /internet [minutos]   da permiso de internet (solo Wikipedia) por unos minutos
  /casa                 cierra la puerta: vuelvo a casa, sin internet
  /wiki tema            busca en Wikipedia (necesita permiso)
  /traer titulo         descarga una página a la cuarentena (necesita permiso)
  /cuarentena           lista lo descargado que aún no revisaste
  /aprobar archivo      pasa un texto de la cuarentena a la biblioteca
  /rechazar archivo     borra un texto de la cuarentena
  /investiga tema       busca en tu biblioteca aprobada (también: «investiga tema»)
  /robots               escanea puertos       /detectar puerto   pregunta «AYUDA»
  /conectar puerto      conecta (usa el perfil detectado)   /desconectar
  /orden nombre [valor] envía una orden del perfil   /sensor nombre   lee un sensor
  /parar                parada de emergencia (también escribir «para» o «stop»)
  /espacio              estado del USB y qué se puede liberar
  /exportar             prepara el diario para revisar y entrenar a Cerebro
"""

_RE_INVESTIGA = re.compile(r"^\s*(?:investiga|investigar|documentate|docum[eé]ntate)\s+(?:sobre\s+)?(.{2,200})$",
                           re.IGNORECASE)
_RE_BUSCA_WIKI = re.compile(r"^\s*(?:busca|buscar|investiga)\s+en\s+(?:wikipedia|internet)\s+(.{2,200})$",
                            re.IGNORECASE)
_PARAR = {"para", "parar", "stop", "detente", "alto", "pará"}


class ErrorCazel(Exception):
    """Error normal (mensaje para mostrar al usuario)."""


def _importar_cerebro(dir_cerebro):
    if not os.path.isdir(dir_cerebro):
        raise ErrorCazel(f"No encuentro la carpeta de Cerebro: {dir_cerebro}")
    if dir_cerebro not in sys.path:
        sys.path.insert(0, dir_cerebro)
    ccfg = importlib.import_module("config")
    if os.path.dirname(os.path.realpath(ccfg.__file__)) != os.path.realpath(dir_cerebro):
        raise ErrorCazel("Otro módulo llamado «config» tapa al de Cerebro. "
                         "Ejecuta CAZEL desde su propia carpeta.")
    return ccfg


class Cazel:
    def __init__(self, datos=None, ajustes=None, abridor_web=None, abrir_transporte=None,
                 cargar_modelo=True, uso_disco=None, reloj_puerta=None, dormir=None):
        self.rutas = cfg.rutas(datos)
        os.makedirs(self.rutas["datos"], exist_ok=True)
        self.ajustes = ajustes if ajustes is not None else cfg.cargar_ajustes(self.rutas["ajustes"])
        self._lock = threading.RLock()

        self.auditoria = Auditoria(self.rutas["auditoria"])
        kw = {}
        if reloj_puerta:
            kw["reloj"] = reloj_puerta
        if dormir:
            kw["dormir"] = dormir
        self.puerta = Puerta(self.rutas["cuarentena"], self.ajustes["internet"], self.auditoria,
                             abridor=abridor_web, **kw)
        self.biblioteca = Biblioteca(self.rutas["cuarentena"], self.rutas["biblioteca"], self.auditoria)
        self.diario = Diario(self.rutas["diario"], self.rutas["revision"])
        self.robots = GestorRobots(self.rutas["robots"], self.ajustes["robot"], self.auditoria,
                                   abrir_transporte=abrir_transporte)

        # --- Cerebro ---
        self._ccfg = _importar_cerebro(cfg.DIR_CEREBRO)
        from agent.controlled_agent import ControlledAgent          # noqa: E402 (viene de Cerebro)
        from agent.tools.registry import ToolRegistry               # noqa: E402
        from memory.advanced_memory import AdvancedMemoryManager    # noqa: E402
        self.memoria = AdvancedMemoryManager(filepath=self.rutas["memoria"])
        agente = ControlledAgent(registry=ToolRegistry(workspace=self.rutas["workspace"]))
        self.modelo, self.meta_modelo, self.ruta_modelo = None, {}, None
        if cargar_modelo:
            self._cargar_modelo()
        self.conversacion = self._crear_conversacion(agente)

        kwe = {"uso_disco": uso_disco} if uso_disco else {}
        self.espacio = GestorEspacio(cfg.RAIZ, self.rutas["datos"], self.ajustes["espacio"],
                                     memoria=self.memoria, auditoria=self.auditoria, **kwe)
        self.espacio.limpieza_automatica_segura()
        self.auditoria.registrar("inicio", modelo=bool(self.modelo))

    # -- modelo ----------------------------------------------------------------------------

    def _cargar_modelo(self):
        from core.checkpoint import cargar_checkpoint               # noqa: E402 (de Cerebro)
        ruta = os.path.join(cfg.DIR_CEREBRO, "checkpoints", "best.npz")
        if not os.path.exists(ruta):
            return
        try:
            datos = cargar_checkpoint(ruta, con_optimizador=False)
            self.modelo, self.meta_modelo, self.ruta_modelo = datos["modelo"], datos["meta"], ruta
        except Exception as e:          # modelo dañado: CAZEL arranca igual, sin chat de Cerebro
            self.auditoria.registrar("modelo_error", error=e)

    def _crear_conversacion(self, agente):
        from chat import Conversacion                               # noqa: E402 (de Cerebro)
        cazel = self

        class CazelConversacion(Conversacion):
            def responder_modelo(self, mensaje):
                if self.modelo is None:
                    return ("Mi modelo (Cerebro) no está cargado: falta cerebro/checkpoints/best.npz. "
                            "Los comandos de CAZEL sí funcionan; escribe /ayuda.")
                return super().responder_modelo(mensaje)

            def _comando(self, entrada):
                if entrada.split(None, 1)[0].lower() in ("/ayuda", "/help"):
                    return AYUDA_CAZEL + "\n\n" + super()._comando(entrada)[0], False
                return super()._comando(entrada)

            def estado(self):
                base = super().estado() if self.modelo is not None else "=== ESTADO ===\nModelo: no cargado"
                return base + "\n" + cazel.resumen_estado_texto()

        return CazelConversacion(self.modelo, self.memoria, agente, info_checkpoint=self.meta_modelo)

    # -- chat ----------------------------------------------------------------------------------

    def chat(self, texto):
        """Procesa un mensaje del usuario. Devuelve (respuesta, terminar)."""
        texto = str(texto or "").strip()
        if not texto:
            return "", False
        if len(texto) > 4000:
            return "El mensaje es demasiado largo (máximo 4000 caracteres).", False
        with self._lock:
            self.diario.anotar("usuario", texto)
            try:
                respuesta, terminar = self._enrutar(texto)
            except (ErrorCazel, ErrorPuerta, ErrorRobot, motor_externo.ErrorMotor, ValueError) as e:
                respuesta, terminar = str(e), False
            if respuesta:
                self.diario.anotar("ia", respuesta)
            return respuesta, terminar

    def _enrutar(self, texto):
        bajo = texto.lower().strip(" .!¡")
        if bajo in _PARAR:
            if self.robots.estado()["conectado"]:
                return self.robots.parar(), False
            return "No hay ningún robot conectado, así que no hay nada que parar.", False
        m = _RE_BUSCA_WIKI.match(texto)
        if m:
            return self._cmd_wiki(m.group(1)), False
        m = _RE_INVESTIGA.match(texto)
        if m:
            return self._cmd_investiga(m.group(1)), False
        if texto.startswith("/"):
            partes = texto.split(None, 1)
            cmd, resto = partes[0].lower(), (partes[1].strip() if len(partes) > 1 else "")
            fn = self._COMANDOS.get(cmd)
            if fn is not None:
                return fn(self, resto), False
        return self.conversacion.procesar(texto)

    # -- comandos ---------------------------------------------------------------------------------

    def _cmd_internet(self, resto):
        minutos = None
        if resto:
            try:
                minutos = float(resto.replace(",", "."))
            except ValueError:
                raise ErrorCazel("Uso: /internet [minutos]")
        e = self.puerta.abrir(minutos)
        return (f"Puerta abierta por {e['segundos_restantes'] // 60 + 1} minutos. "
                f"Solo puedo hablar con: {', '.join(e['dominios'])}. Escribe /casa para cerrarla.")

    def _cmd_casa(self, resto):
        self.puerta.cerrar()
        return "Volví a casa: la puerta de internet está cerrada."

    def _cmd_wiki(self, resto):
        if not resto:
            raise ErrorCazel("Uso: /wiki tema")
        res = self.puerta.buscar(resto)
        if not res:
            return f"No encontré nada en Wikipedia sobre «{resto}»."
        return "Esto encontré (usa /traer «título» para bajar uno a la cuarentena):\n" + "\n".join(
            f"  · {r['titulo']}: {r['resumen']}" for r in res)

    def _cmd_traer(self, resto):
        if not resto:
            raise ErrorCazel("Uso: /traer título")
        r = self.traer(resto)
        return (f"Descargado «{r['titulo']}» a la cuarentena ({r['caracteres']} caracteres). "
                f"Revísalo y usa /aprobar {r['archivo']} o /rechazar {r['archivo']}.")

    def _cmd_cuarentena(self, resto):
        lista = self.biblioteca.listar_cuarentena()
        if not lista:
            return "La cuarentena está vacía."
        return "En cuarentena (sin revisar):\n" + "\n".join(
            f"  · {x['archivo']}  ({x['bytes'] // 1024 + 1} KB)  {x['titulo']}" for x in lista)

    def _cmd_aprobar(self, resto):
        return f"Aprobado: {self.biblioteca.aprobar(resto)['archivo']} ya está en mi biblioteca."

    def _cmd_rechazar(self, resto):
        return f"Rechazado y borrado: {self.biblioteca.rechazar(resto)['archivo']}."

    def _cmd_investiga(self, resto):
        if not resto:
            raise ErrorCazel("Uso: /investiga tema")
        res = self.biblioteca.buscar(resto)
        if not res:
            return (f"No tengo nada sobre «{resto}» en mi biblioteca aprobada. "
                    f"Puedes darme permiso con /internet y usar /wiki {resto}.")
        return "Esto dice mi biblioteca:\n" + "\n\n".join(
            f"· {r['titulo']}\n  {r['texto']}\n  Fuente: {r['fuente']}" for r in res)

    def _cmd_robots(self, resto):
        p = self.robots.escanear()
        return "Puertos encontrados (aún no envié nada a ninguno):\n" + "\n".join(
            f"  · {x['puerto']}  {x['descripcion']}" for x in p) + "\nUsa /detectar puerto."

    def _cmd_detectar(self, resto):
        if not resto:
            raise ErrorCazel("Uso: /detectar puerto   (por ejemplo /detectar simulado)")
        r = self.robots.detectar(resto)
        if not r["encontrado"]:
            return (f"Ahí no hay un robot que hable CAZEL ({r['motivo']}). Si es tu Arduino, "
                    f"usa «Adaptar con mi código» en el menú ⋮ para generar el adaptador.")
        p = r["perfil"]
        self.robots.guardar_perfil(p)
        return (f"¡Encontré «{p['nombre']}»! Órdenes: {', '.join(p['ordenes'])}. "
                f"Lecturas: {', '.join(p['lecturas']) or 'ninguna'}. Perfil guardado. "
                f"Escribe /conectar {resto}.")

    def _cmd_conectar(self, resto):
        puerto = resto.strip()
        if not puerto:
            raise ErrorCazel("Uso: /conectar puerto")
        det = self.robots.detectar(puerto)
        if not det["encontrado"]:
            raise ErrorCazel("Ese puerto no respondió como un robot CAZEL. " + det["motivo"])
        self.robots.guardar_perfil(det["perfil"])
        e = self.robots.conectar(puerto, det["perfil"])
        return f"Conectado a «{e['nombre']}». Órdenes: {', '.join(e['ordenes'])}."

    def _cmd_desconectar(self, resto):
        return "Desconectado (envié PARAR antes)." if self.robots.desconectar() else "No había ningún robot conectado."

    def _cmd_orden(self, resto):
        p = resto.split()
        if not p or len(p) > 2:
            raise ErrorCazel("Uso: /orden nombre [valor]")
        return self.robots.ejecutar(p[0], p[1] if len(p) == 2 else None)

    def _cmd_leer(self, resto):
        if not resto:
            raise ErrorCazel("Uso: /leer nombre_de_sensor")
        return self.robots.leer(resto.split()[0])["texto"]

    def _cmd_parar(self, resto):
        return self.robots.parar()

    def _cmd_espacio(self, resto):
        p = self.espacio.propuesta()
        u = p["uso"]
        t = (f"USB: {u['porcentaje_usado']} % usado, {u['libre'] // (1024 * 1024)} MB libres. {u['mensaje']}")
        if p["candidatos"]:
            t += f"\nSe podrían liberar {p['bytes_liberables'] // 1024} KB (abre «Espacio» en el menú ⋮ para elegir qué)."
        return t

    def _cmd_exportar(self, resto):
        r = self.diario.exportar_para_revision()
        if not r["pares"]:
            return "Todavía no hay conversaciones que exportar."
        return (f"Preparé {r['pares']} diálogos en «{r['archivo']}». Revísalos y copia al corpus de "
                f"Cerebro solo los que estén bien.")

    def _cmd_consulta(self, resto):
        return motor_externo.consultar(self.ajustes["motor_externo"], resto)

    # «/leer» ya existe en Cerebro (leer un archivo del workspace), por eso el sensor es /sensor.
    _COMANDOS = {
        "/internet": _cmd_internet, "/casa": _cmd_casa, "/wiki": _cmd_wiki, "/traer": _cmd_traer,
        "/cuarentena": _cmd_cuarentena, "/aprobar": _cmd_aprobar, "/rechazar": _cmd_rechazar,
        "/investiga": _cmd_investiga, "/robots": _cmd_robots, "/detectar": _cmd_detectar,
        "/conectar": _cmd_conectar, "/desconectar": _cmd_desconectar, "/orden": _cmd_orden,
        "/sensor": _cmd_leer, "/parar": _cmd_parar, "/espacio": _cmd_espacio,
        "/exportar": _cmd_exportar, "/consulta": _cmd_consulta,
    }

    # -- operaciones que usa también la interfaz ------------------------------------------------

    def traer(self, titulo, idioma="es"):
        uso = self.espacio.uso()
        if uso["libre"] < MIN_LIBRE_DESCARGA:
            self.espacio.limpieza_automatica_segura()
            if self.espacio.uso()["libre"] < MIN_LIBRE_DESCARGA:
                raise ErrorCazel("No hay espacio suficiente para descargar. Abre «Espacio» en el menú ⋮ "
                                 "y libera algo.")
        return self.puerta.traer(titulo, idioma)

    def analizar_codigo(self, codigo):
        return analizador.analizar_codigo(codigo)

    def adaptador(self, codigo, nombre):
        informe = analizador.analizar_codigo(codigo)
        informe["propuesta"]["nombre"] = str(nombre).lower()
        return {"informe": informe, "sketch": analizador.generar_adaptador(informe, nombre)}

    # -- estado -------------------------------------------------------------------------------------

    def estado(self):
        return {
            "modelo": {"cargado": self.modelo is not None,
                       "parametros": self.modelo.n_parametros() if self.modelo is not None else 0},
            "puerta": self.puerta.estado(),
            "espacio": self.espacio.uso(),
            "robot": self.robots.estado(),
            "cuarentena": len(self.biblioteca.listar_cuarentena()),
            "biblioteca": len(self.biblioteca.listar_biblioteca()),
            "motor_externo": bool(self.ajustes["motor_externo"].get("activo")),
        }

    def resumen_estado_texto(self):
        e = self.estado()
        p, u, r = e["puerta"], e["espacio"], e["robot"]
        return "\n".join([
            f"Internet: {'ABIERTA (' + str(p['segundos_restantes'] // 60 + 1) + ' min)' if p['abierta'] else 'cerrada (en casa)'}",
            f"USB: {u['porcentaje_usado']} % usado, {u['libre'] // (1024 * 1024)} MB libres",
            f"Robot: {('conectado a ' + r['nombre']) if r['conectado'] else 'ninguno conectado'}",
            f"Cuarentena: {e['cuarentena']} · Biblioteca: {e['biblioteca']} textos",
        ])

    def cerrar(self):
        """Apagado ordenado: PARAR al robot, cerrar la puerta."""
        try:
            self.robots.desconectar()
        finally:
            self.puerta.cerrar()
            self.auditoria.registrar("apagado")
