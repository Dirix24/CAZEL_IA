# -*- coding: utf-8 -*-
"""
Piezas de seguridad compartidas (inspiradas en el "cuerpo" de Arquitectura-Arus:
auditoría, límite de ritmo y guardia de rutas).

  * Auditoria     registro de lo importante en un archivo pequeño (rota solo,
                  para no gastar el USB).
  * LimiteRitmo   máximo N acciones cada T segundos.
  * ruta_dentro   comprueba con realpath + commonpath que una ruta sigue
                  dentro de una carpeta (bloquea ../ y enlaces simbólicos).
  * nombre_seguro convierte un título en un nombre de archivo sin sorpresas.
"""

import datetime
import json
import os
import re
import threading
import time
import unicodedata
from collections import deque


def ruta_dentro(base, ruta):
    """Ruta real de `ruta` si está dentro de `base` (y no es `base`); si no, None."""
    base_real = os.path.realpath(base)
    real = os.path.realpath(ruta)
    try:
        if os.path.commonpath([base_real, real]) != base_real or real == base_real:
            return None
    except ValueError:      # p. ej. distintas unidades en Windows
        return None
    return real


def nombre_seguro(texto, maximo=60):
    """'Física cuántica (rama)' -> 'fisica_cuantica_rama'. Nunca devuelve vacío."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    t = re.sub(r"[^A-Za-z0-9]+", "_", t).strip("_").lower()
    return (t[:maximo].strip("_")) or "sin_nombre"


class LimiteRitmo:
    def __init__(self, limite=20, segundos=10, reloj=time.monotonic):
        self.limite = limite
        self.segundos = segundos
        self._reloj = reloj
        self._llamadas = deque()
        self._lock = threading.Lock()

    def permitido(self):
        with self._lock:
            ahora = self._reloj()
            while self._llamadas and ahora - self._llamadas[0] > self.segundos:
                self._llamadas.popleft()
            if len(self._llamadas) >= self.limite:
                return False
            self._llamadas.append(ahora)
            return True


class Auditoria:
    """Registro JSON-por-línea. Si pasa de `max_bytes` se queda con la mitad
    final, así nunca crece sin control en un USB pequeño."""

    def __init__(self, ruta, max_bytes=256 * 1024):
        self.ruta = ruta
        self.max_bytes = max_bytes
        self._lock = threading.Lock()

    def registrar(self, evento, **datos):
        linea = {"t": datetime.datetime.now().isoformat(timespec="seconds"), "evento": evento}
        for k, v in datos.items():
            linea[k] = str(v)[:300]
        try:
            with self._lock:
                os.makedirs(os.path.dirname(os.path.abspath(self.ruta)), exist_ok=True)
                with open(self.ruta, "a", encoding="utf-8") as f:
                    f.write(json.dumps(linea, ensure_ascii=False) + "\n")
                self._recortar()
        except OSError:
            pass        # el registro nunca debe romper la aplicación

    def _recortar(self):
        try:
            if os.path.getsize(self.ruta) <= self.max_bytes:
                return
            with open(self.ruta, "rb") as f:
                f.seek(-self.max_bytes // 2, os.SEEK_END)
                f.readline()                       # descarta la línea cortada
                resto = f.read()
            tmp = self.ruta + ".tmp"
            with open(tmp, "wb") as f:
                f.write(resto)
            os.replace(tmp, self.ruta)
        except OSError:
            pass

    def ultimos(self, n=50):
        try:
            with open(self.ruta, "r", encoding="utf-8") as f:
                lineas = f.readlines()[-n:]
        except OSError:
            return []
        salida = []
        for l in lineas:
            try:
                salida.append(json.loads(l))
            except ValueError:
                continue
        return salida
