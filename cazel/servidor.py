# -*- coding: utf-8 -*-
"""
Servidor local de la interfaz de CAZEL.

La interfaz es una página web que se abre en tu navegador, pero el servidor
SOLO escucha en 127.0.0.1 (este mismo equipo): nadie de tu red ni de internet
puede entrar. Además:
  * cada vez que arranca crea una clave aleatoria (token) que la página envía
    en cada petición; sin ella el servidor no hace nada;
  * comprueba las cabeceras Host y Origin (protege contra páginas web
    maliciosas que intenten hablar con un servidor local);
  * las peticiones POST deben ser JSON y de tamaño limitado;
  * cabeceras de seguridad estrictas (CSP): la página no carga nada de fuera;
  * se apaga sola tras un rato sin actividad (y antes envía PARAR al robot).
"""

import hmac
import json
import os
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import motor_externo, github_repo, proyecto
from .nucleo import Cazel, ErrorCazel
from .puerta import ErrorPuerta
from .robot import protocolo
from .robot.control import ErrorRobot

DIR_WEB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "web")
MAX_CUERPO = 400_000
ARCHIVOS_ESTATICOS = {
    "/app.css": ("app.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "application/javascript; charset=utf-8"),
}
ERRORES_NORMALES = (ErrorCazel, ErrorPuerta, ErrorRobot, motor_externo.ErrorMotor,
                    github_repo.ErrorGitHub, protocolo.ErrorProtocolo, ValueError, PermissionError)


def _texto(d, clave, maximo=4000, obligatorio=True):
    v = d.get(clave, "")
    if not isinstance(v, str):
        raise ValueError(f"«{clave}» debe ser texto.")
    v = v.strip()
    if obligatorio and not v:
        raise ValueError(f"Falta «{clave}».")
    if len(v) > maximo:
        raise ValueError(f"«{clave}» es demasiado largo.")
    return v


class Servidor:
    def __init__(self, cazel, puerto=8765, abrir_navegador=True, minutos_inactividad=20):
        self.cazel = cazel
        self.token = secrets.token_urlsafe(18)
        self.abrir_navegador = abrir_navegador
        self.inactividad_s = max(1, minutos_inactividad) * 60
        self.ultima_actividad = time.monotonic()
        self._parado = threading.Event()
        self.httpd = None
        for p in range(int(puerto), int(puerto) + 25):      # si está ocupado, prueba el siguiente
            try:
                self.httpd = ThreadingHTTPServer(("127.0.0.1", p), self._crear_handler())
                break
            except OSError:
                continue
        if self.httpd is None:
            raise OSError("No encontré un puerto libre para la interfaz.")
        self.puerto = self.httpd.server_address[1]
        self.httpd.daemon_threads = True
        self.hosts = {f"127.0.0.1:{self.puerto}", f"localhost:{self.puerto}"}
        self.origenes = {f"http://{h}" for h in self.hosts}

    @property
    def url(self):
        return f"http://127.0.0.1:{self.puerto}/"

    # -- acciones de la API --------------------------------------------------------------

    def _acciones(self):
        c = self.cazel
        R = c.robots

        def chat(d):
            respuesta, terminar = c.chat(_texto(d, "texto"))
            if terminar:
                threading.Thread(target=self.parar, daemon=True).start()
            return {"respuesta": respuesta, "terminar": terminar}

        def puerta(d):
            a = _texto(d, "accion", 10)
            if a == "abrir":
                return c.puerta.abrir(d.get("minutos"))
            if a == "cerrar":
                return c.puerta.cerrar()
            raise ValueError("Acción de puerta no válida.")

        def robots_conectar(d):
            puerto = _texto(d, "puerto", 60)
            nombre = _texto(d, "perfil", 30, obligatorio=False)
            if nombre:
                perfil = next((p for p in R.perfiles() if p["nombre"] == nombre.lower()), None)
                if perfil is None:
                    raise ErrorCazel(f"No tengo guardado un perfil llamado «{nombre}».")
            else:
                det = R.detectar(puerto)
                if not det["encontrado"]:
                    raise ErrorCazel("Ese puerto no respondió como un robot CAZEL: " + det["motivo"])
                perfil = det["perfil"]
                R.guardar_perfil(perfil)
            return R.conectar(puerto, perfil)

        def analizar_archivos(d):
            archivos = d.get("archivos")
            if not isinstance(archivos, list) or len(archivos) > proyecto.MAX_ARCHIVOS:
                raise ValueError("El proyecto debe tener como máximo 24 archivos compatibles.")
            return proyecto.analizar(archivos)

        def revisar_github(d):
            datos = github_repo.descargar(_texto(d, "url", 300))
            c.auditoria.registrar("repositorio_publico_leido", repositorio=datos["repositorio"],
                                  archivos=len(datos["archivos"]))
            informe = proyecto.analizar(datos["archivos"])
            salida = {"repositorio": datos["repositorio"], "url": datos["url"],
                      "rama": datos["rama"], "truncado": datos["truncado"],
                      "caracteres": datos["caracteres"], "informe": informe}
            return salida

        def espacio_liberar(d):
            ids = d.get("ids")
            if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids) or len(ids) > 500:
                raise ValueError("Lista de elementos no válida.")
            return c.espacio.liberar(ids, confirmado=d.get("confirmado") is True)

        return {
            "estado": lambda d: c.estado(),
            "chat": chat,
            "puerta": puerta,
            "wiki_buscar": lambda d: {"resultados": c.puerta.buscar(
                _texto(d, "consulta", 200), _texto(d, "idioma", 3, False) or "es")},
            "wiki_traer": lambda d: c.traer(_texto(d, "titulo", 200), _texto(d, "idioma", 3, False) or "es"),
            "cuarentena": lambda d: {"archivos": c.biblioteca.listar_cuarentena()},
            "cuarentena_ver": lambda d: c.biblioteca.vista_previa(_texto(d, "archivo", 100)),
            "aprobar": lambda d: c.biblioteca.aprobar(_texto(d, "archivo", 100)),
            "rechazar": lambda d: c.biblioteca.rechazar(_texto(d, "archivo", 100)),
            "biblioteca": lambda d: {"archivos": c.biblioteca.listar_biblioteca()},
            "biblioteca_buscar": lambda d: {"resultados": c.biblioteca.buscar(_texto(d, "consulta", 200))},
            "robots_escanear": lambda d: {"puertos": R.escanear()},
            "robots_detectar": lambda d: R.detectar(_texto(d, "puerto", 60)),
            "robots_perfiles": lambda d: {"perfiles": R.perfiles()},
            "robots_guardar": lambda d: {"perfil": R.guardar_perfil(d.get("perfil"))},
            "robots_borrar": lambda d: {"borrado": R.borrar_perfil(_texto(d, "nombre", 30))},
            "robots_conectar": robots_conectar,
            "robots_desconectar": lambda d: {"desconectado": R.desconectar()},
            "robots_orden": lambda d: {"texto": R.ejecutar(
                _texto(d, "nombre", 30), None if d.get("valor") in (None, "") else str(d.get("valor"))[:30])},
            "robots_leer": lambda d: R.leer(_texto(d, "nombre", 30)),
            "robots_parar": lambda d: {"texto": R.parar()},
            "codigo_analizar": lambda d: c.analizar_codigo(_texto(d, "codigo", 200_000)),
            "proyecto_archivos": analizar_archivos,
            "repositorio_github": revisar_github,
            "codigo_adaptador": lambda d: c.adaptador(_texto(d, "codigo", 200_000),
                                                      _texto(d, "nombre", 24)),
            "espacio": lambda d: c.espacio.propuesta(),
            "espacio_liberar": espacio_liberar,
            "diario_exportar": lambda d: c.diario.exportar_para_revision(),
            "diario_ultimos": lambda d: {"filas": c.diario.ultimos(30)},
            "consulta": lambda d: {"respuesta": motor_externo.consultar(
                c.ajustes["motor_externo"], _texto(d, "texto", 20000))},
            "apagar": lambda d: (threading.Thread(target=self.parar, daemon=True).start()
                                 or {"apagando": True}),
        }

    # -- HTTP -----------------------------------------------------------------------------

    def _crear_handler(self):
        srv = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "CAZEL"
            sys_version = ""
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):          # sin ruido en la consola
                pass

            # utilidades
            def _enviar(self, codigo, cuerpo, tipo):
                if isinstance(cuerpo, str):
                    cuerpo = cuerpo.encode("utf-8")
                self.send_response(codigo)
                self.send_header("Content-Type", tipo)
                self.send_header("Content-Length", str(len(cuerpo)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("Content-Security-Policy",
                                 "default-src 'none'; script-src 'self'; style-src 'self'; "
                                 "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                                 "form-action 'none'; frame-ancestors 'none'")
                self.end_headers()
                self.wfile.write(cuerpo)

            def _json(self, codigo, datos):
                self._enviar(codigo, json.dumps(datos, ensure_ascii=False), "application/json; charset=utf-8")

            def _host_ok(self):
                return (self.headers.get("Host") or "").lower() in srv.hosts

            def _origen_ok(self):
                o = self.headers.get("Origin")
                return o is None or o.lower() in srv.origenes

            def _token_ok(self):
                t = self.headers.get("X-Cazel-Token") or ""
                return hmac.compare_digest(t.encode("utf-8"), srv.token.encode("utf-8"))

            # métodos
            def do_GET(self):
                srv.ultima_actividad = time.monotonic()
                if not self._host_ok():
                    return self._json(403, {"error": "Host no permitido."})
                ruta = self.path.split("?", 1)[0]
                if ruta == "/":
                    try:
                        with open(os.path.join(DIR_WEB, "index.html"), "r", encoding="utf-8") as f:
                            html = f.read().replace("__TOKEN__", srv.token)
                    except OSError:
                        return self._json(500, {"error": "Falta la interfaz (carpeta cazel/web)."})
                    return self._enviar(200, html, "text/html; charset=utf-8")
                if ruta in ARCHIVOS_ESTATICOS:
                    nombre, tipo = ARCHIVOS_ESTATICOS[ruta]
                    try:
                        with open(os.path.join(DIR_WEB, nombre), "rb") as f:
                            return self._enviar(200, f.read(), tipo)
                    except OSError:
                        return self._json(404, {"error": "No encontrado."})
                if ruta == "/favicon.ico":
                    return self._enviar(204, b"", "image/x-icon")
                if ruta == "/api/estado":
                    if not self._token_ok():
                        return self._json(401, {"error": "Falta la clave de sesión."})
                    return self._json(200, srv.cazel.estado())
                return self._json(404, {"error": "No encontrado."})

            def do_POST(self):
                srv.ultima_actividad = time.monotonic()
                if not self._host_ok() or not self._origen_ok():
                    return self._json(403, {"error": "Origen no permitido."})
                if not self._token_ok():
                    return self._json(401, {"error": "Falta la clave de sesión. Recarga la página."})
                ruta = self.path.split("?", 1)[0]
                if not ruta.startswith("/api/"):
                    return self._json(404, {"error": "No encontrado."})
                if not (self.headers.get("Content-Type") or "").lower().startswith("application/json"):
                    return self._json(415, {"error": "Se esperaba JSON."})
                try:
                    largo = int(self.headers.get("Content-Length") or 0)
                except ValueError:
                    return self._json(400, {"error": "Longitud no válida."})
                if largo < 0 or largo > MAX_CUERPO:
                    return self._json(413, {"error": "Petición demasiado grande."})
                try:
                    datos = json.loads(self.rfile.read(largo).decode("utf-8") or "{}")
                    if not isinstance(datos, dict):
                        raise ValueError
                except (ValueError, UnicodeDecodeError):
                    return self._json(400, {"error": "JSON no válido."})
                accion = srv._acciones().get(ruta[5:])
                if accion is None:
                    return self._json(404, {"error": "Acción desconocida."})
                try:
                    return self._json(200, accion(datos))
                except ERRORES_NORMALES as e:
                    return self._json(400, {"error": str(e)})
                except Exception as e:           # nunca se enseña un traceback al navegador
                    srv.cazel.auditoria.registrar("error_interno", ruta=ruta, error=repr(e))
                    return self._json(500, {"error": "Error interno. Quedó anotado en la auditoría."})

        return Handler

    # -- ciclo de vida --------------------------------------------------------------------------

    def _vigilar_inactividad(self):
        while not self._parado.wait(5):
            if time.monotonic() - self.ultima_actividad > self.inactividad_s:
                self.cazel.auditoria.registrar("apagado_por_inactividad")
                self.parar()
                return

    def servir(self):
        """Bloquea hasta que se apaga. Siempre deja al robot en PARAR."""
        threading.Thread(target=self._vigilar_inactividad, daemon=True).start()
        if self.abrir_navegador:
            threading.Timer(0.6, self._abrir_navegador).start()
        try:
            self.httpd.serve_forever(poll_interval=0.3)
        except KeyboardInterrupt:
            pass
        finally:
            self.cazel.cerrar()
            self.httpd.server_close()

    def _abrir_navegador(self):
        try:
            webbrowser.open(self.url)
        except Exception:
            pass

    def parar(self):
        self._parado.set()
        threading.Thread(target=self.httpd.shutdown, daemon=True).start()
