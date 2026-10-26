# -*- coding: utf-8 -*-
"""
Control de robots.

GestorRobots reúne todo lo que hace la interfaz:
  escanear()            lista puertos (NO envía nada a ningún dispositivo)
  detectar(puerto)      envía solo «AYUDA» y lee la lista de órdenes
  guardar_perfil / perfiles   perfiles aprobados, en datos/robots/
  conectar / ejecutar / leer / parar / desconectar

Reglas de seguridad que se hacen cumplir aquí:
  * La orden que llega al robot se CONSTRUYE (protocolo.construir_orden) solo
    con órdenes del perfil y números dentro de su rango. Nunca es texto libre.
  * Límite de ritmo: 20 órdenes cada 10 s (ajustable). PARAR no tiene límite.
  * PARAR sale siempre primero, incluso si hay otra orden en curso.
  * Al desconectar o cerrar la aplicación se envía PARAR antes de cerrar.
  * Una sola conexión a la vez.
"""

import json
import os
import threading
import time

from ..seguridad import LimiteRitmo, nombre_seguro
from . import protocolo, transporte
from .protocolo import ErrorProtocolo


class ErrorRobot(Exception):
    """Error normal del robot (mensaje pensado para mostrarse al usuario)."""


class GestorRobots:
    def __init__(self, dir_robots, ajustes_robot, auditoria=None, abrir_transporte=None):
        self.dir = dir_robots
        self.aj = ajustes_robot
        self.auditoria = auditoria
        self._abrir = abrir_transporte or self._abrir_real
        self._lock = threading.RLock()
        self._parar_lock = threading.Lock()
        self._tr = None
        self._perfil = None
        self._puerto = None
        lim, seg = self.aj["limite_ordenes"]
        self._ritmo = LimiteRitmo(int(lim), float(seg))

    # -- utilidades --------------------------------------------------------------------

    def _anotar(self, evento, **datos):
        if self.auditoria:
            self.auditoria.registrar(evento, **datos)

    def _abrir_real(self, puerto, baudios):
        if puerto == "simulado":
            return transporte.SimTransporte()
        return transporte.SerieTransporte(puerto, baudios,
                                          espera_arranque=float(self.aj["espera_arranque_s"]))

    # -- escanear y detectar ----------------------------------------------------------------

    def escanear(self):
        """Puertos disponibles. El robot simulado se ofrece siempre, para poder
        probar la interfaz sin hardware."""
        puertos = transporte.listar_puertos()
        puertos.append({"puerto": "simulado", "descripcion": "Robot simulado (para probar sin hardware)"})
        self._anotar("escaneo", puertos=len(puertos) - 1)
        return puertos

    def detectar(self, puerto):
        """Envía SOLO «AYUDA» a ese puerto e interpreta la respuesta."""
        if not transporte.puerto_permitido(puerto):
            raise ErrorRobot("Ese puerto no es válido.")
        with self._lock:
            if self._tr is not None and self._puerto == puerto:
                raise ErrorRobot("Ese puerto ya está conectado. Desconéctalo antes de detectarlo.")
            ultimo_error = "No respondió."
            for baudios in self.aj["baudios"]:
                try:
                    tr = self._abrir(puerto, int(baudios))
                except (transporte.ErrorTransporte, OSError) as e:
                    raise ErrorRobot(str(e))
                try:
                    tr.vaciar()
                    tr.escribir_linea("AYUDA")
                    lineas = []
                    limite = time.monotonic() + float(self.aj["timeout_respuesta_s"])
                    while time.monotonic() < limite and len(lineas) < 80:
                        l = tr.leer_linea(max(0.05, limite - time.monotonic()))
                        if l is None:
                            break
                        lineas.append(l)
                        if l.strip().upper() == "FIN":
                            break
                    perfil = protocolo.parsear_ayuda(lineas)
                    perfil["baudios"] = int(baudios)
                    perfil["origen"] = "autodescubierto"
                    perfil["puerto"] = puerto
                    self._anotar("robot_detectado", puerto=puerto, nombre=perfil["nombre"],
                                 ordenes=len(perfil["ordenes"]))
                    return {"encontrado": True, "perfil": perfil}
                except ErrorProtocolo as e:
                    ultimo_error = str(e)
                except transporte.ErrorTransporte as e:
                    raise ErrorRobot(str(e))
                finally:
                    tr.cerrar()
            self._anotar("robot_no_detectado", puerto=puerto, motivo=ultimo_error)
            return {"encontrado": False, "motivo": ultimo_error}

    # -- perfiles ------------------------------------------------------------------------------

    def _ruta_perfil(self, nombre):
        return os.path.join(self.dir, nombre_seguro(nombre, 24) + ".json")

    def guardar_perfil(self, perfil):
        limpio = protocolo.validar_perfil(perfil)
        os.makedirs(self.dir, exist_ok=True)
        ruta = self._ruta_perfil(limpio["nombre"])
        with open(ruta + ".tmp", "w", encoding="utf-8") as f:
            json.dump(limpio, f, ensure_ascii=False, indent=2)
        os.replace(ruta + ".tmp", ruta)
        self._anotar("perfil_guardado", nombre=limpio["nombre"], origen=limpio["origen"])
        return limpio

    def perfiles(self):
        salida = []
        if not os.path.isdir(self.dir):
            return salida
        for n in sorted(os.listdir(self.dir)):
            if not n.endswith(".json"):
                continue
            try:
                with open(os.path.join(self.dir, n), "r", encoding="utf-8") as f:
                    salida.append(protocolo.validar_perfil(json.load(f)))
            except (OSError, ValueError, ErrorProtocolo, TypeError):
                continue            # un perfil corrupto no rompe a los demás
        return salida

    def borrar_perfil(self, nombre):
        ruta = self._ruta_perfil(nombre)
        if os.path.isfile(ruta):
            os.remove(ruta)
            self._anotar("perfil_borrado", nombre=nombre)
            return True
        return False

    # -- conexión ---------------------------------------------------------------------------------

    def estado(self):
        with self._lock:
            if self._tr is None:
                return {"conectado": False}
            return {"conectado": True, "puerto": self._puerto, "nombre": self._perfil["nombre"],
                    "ordenes": {n: dict(s) for n, s in self._perfil["ordenes"].items()},
                    "lecturas": {n: dict(s) for n, s in self._perfil["lecturas"].items()}}

    def conectar(self, puerto, perfil):
        perfil = protocolo.validar_perfil(perfil)
        with self._lock:
            if self._tr is not None:
                raise ErrorRobot("Ya hay un robot conectado. Desconéctalo primero.")
            try:
                tr = self._abrir(puerto, perfil["baudios"])
            except (transporte.ErrorTransporte, OSError) as e:
                raise ErrorRobot(str(e))
            self._tr, self._perfil, self._puerto = tr, perfil, puerto
            self._anotar("robot_conectado", puerto=puerto, nombre=perfil["nombre"])
            return self.estado()

    def _hablar(self, linea, esperar_valor=False):
        """Envía una línea y devuelve (tipo, dato) de la respuesta."""
        tr = self._tr
        try:
            tr.vaciar()
            tr.escribir_linea(linea)
            limite = time.monotonic() + float(self.aj["timeout_respuesta_s"])
            while True:
                falta = limite - time.monotonic()
                if falta <= 0:
                    return "err", "El robot no respondió a tiempo."
                l = tr.leer_linea(falta)
                if l is None:
                    return "err", "El robot no respondió a tiempo."
                tipo, dato = protocolo.parsear_respuesta(l)
                if tipo != "otro":
                    return tipo, dato
        except transporte.ErrorTransporte as e:
            self._soltar()
            raise ErrorRobot(str(e))

    def _soltar(self):
        try:
            if self._tr is not None:
                self._tr.cerrar()
        finally:
            self._tr, self._perfil, self._puerto = None, None, None

    def ejecutar(self, nombre, valor=None):
        """Valida y envía una orden del perfil. Devuelve un texto para el usuario."""
        nombre = str(nombre).strip().lower()
        if nombre == "parar":
            return self.parar()
        with self._lock:
            if self._tr is None:
                raise ErrorRobot("No hay ningún robot conectado.")
            try:
                linea = protocolo.construir_orden(self._perfil, nombre, valor,
                                                  tope_absoluto=float(self.aj["tope_valor_absoluto"]))
            except ErrorProtocolo as e:
                raise ErrorRobot(str(e))
            if not self._ritmo.permitido():
                self._anotar("orden_rechazada", motivo="ritmo", orden=linea)
                raise ErrorRobot("Demasiadas órdenes seguidas. Espera unos segundos.")
            tipo, dato = self._hablar(linea)
            self._anotar("orden", robot=self._perfil["nombre"], orden=linea, respuesta=f"{tipo} {dato or ''}")
            if tipo == "ok":
                return f"Hecho: {linea}"
            raise ErrorRobot(f"El robot respondió con un error: {dato}" if tipo == "err"
                             else "Respuesta inesperada del robot.")

    def leer(self, nombre):
        nombre = str(nombre).strip().lower()
        with self._lock:
            if self._tr is None:
                raise ErrorRobot("No hay ningún robot conectado.")
            if nombre not in self._perfil["lecturas"]:
                raise ErrorRobot(f"Este robot no tiene la lectura «{nombre}». Tiene: "
                                 f"{', '.join(sorted(self._perfil['lecturas'])) or 'ninguna'}.")
            tipo, dato = self._hablar(f"LEER {nombre}")
            if tipo == "val":
                u = self._perfil["lecturas"][nombre]["unidad"]
                return {"valor": dato, "texto": f"{nombre} = {protocolo.formatear_numero(dato)} {u}".strip()}
            raise ErrorRobot(f"No pude leer «{nombre}»: {dato}")

    def parar(self):
        """Parada de emergencia: no espera turno ni límite de ritmo. Se intenta
        incluso si otra orden está esperando respuesta."""
        with self._parar_lock:
            tr = self._tr
            if tr is None:
                raise ErrorRobot("No hay ningún robot conectado.")
            try:
                tr.escribir_linea("PARAR")
            except transporte.ErrorTransporte as e:
                raise ErrorRobot(f"No pude enviar PARAR: {e}")
            self._anotar("parar", robot=(self._perfil or {}).get("nombre", "?"))
            return "PARAR enviado."

    def desconectar(self):
        with self._lock:
            if self._tr is None:
                return False
            try:
                self._tr.escribir_linea("PARAR")
            except Exception:
                pass
            nombre = self._perfil["nombre"]
            self._soltar()
            self._anotar("robot_desconectado", nombre=nombre)
            return True
