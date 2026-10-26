# -*- coding: utf-8 -*-
"""
Diario de conversaciones.

Cada mensaje se anota en un archivo por día (datos/diario/AAAA-MM-DD.jsonl).
Sirve para dos cosas:
  1. que CAZEL pueda recordar de qué se habló;
  2. convertir las conversaciones buenas en diálogos de entrenamiento para
     Cerebro. Eso NO es automático: se exporta un borrador a datos/revision/
     para que lo revises y lo corrijas tú antes de añadirlo al corpus.
"""

import datetime
import json
import os
import threading


class Diario:
    def __init__(self, dir_diario, dir_revision, reloj=datetime.datetime.now):
        self.dir = dir_diario
        self.dir_revision = dir_revision
        self._reloj = reloj
        self._lock = threading.Lock()

    def anotar(self, rol, texto):
        ahora = self._reloj()
        linea = {"t": ahora.strftime("%H:%M:%S"), "rol": rol, "texto": str(texto)[:2000]}
        try:
            with self._lock:
                os.makedirs(self.dir, exist_ok=True)
                ruta = os.path.join(self.dir, ahora.strftime("%Y-%m-%d") + ".jsonl")
                with open(ruta, "a", encoding="utf-8") as f:
                    f.write(json.dumps(linea, ensure_ascii=False) + "\n")
        except OSError:
            pass            # el diario nunca debe romper la conversación

    def _archivos(self):
        if not os.path.isdir(self.dir):
            return []
        return sorted(n for n in os.listdir(self.dir) if n.endswith(".jsonl"))

    def ultimos(self, n=20):
        filas = []
        for nombre in reversed(self._archivos()):
            try:
                with open(os.path.join(self.dir, nombre), "r", encoding="utf-8") as f:
                    for l in f:
                        try:
                            d = json.loads(l)
                            d["dia"] = nombre[:-6]
                            filas.append(d)
                        except ValueError:
                            continue
            except OSError:
                continue
            if len(filas) >= n:
                break
        return filas[-n:]

    def exportar_para_revision(self):
        """Escribe pares «usuario:/cerebro:» (solo conversación normal, sin
        comandos) en datos/revision/dialogos_pendientes.txt para revisarlos."""
        pares = []
        for nombre in self._archivos():
            pendiente = None
            try:
                with open(os.path.join(self.dir, nombre), "r", encoding="utf-8") as f:
                    for l in f:
                        try:
                            d = json.loads(l)
                        except ValueError:
                            continue
                        if d.get("rol") == "usuario":
                            t = str(d.get("texto", "")).strip()
                            pendiente = None if (not t or t.startswith("/")) else t
                        elif d.get("rol") == "ia" and pendiente:
                            r = str(d.get("texto", "")).strip().replace("\n", " ")
                            if r:
                                pares.append((pendiente.replace("\n", " "), r))
                            pendiente = None
            except OSError:
                continue
        if not pares:
            return {"pares": 0, "archivo": None}
        os.makedirs(self.dir_revision, exist_ok=True)
        ruta = os.path.join(self.dir_revision, "dialogos_pendientes.txt")
        with open(ruta + ".tmp", "w", encoding="utf-8") as f:
            f.write("# Borrador: corrige las respuestas y copia al corpus (cerebro/data/corpus/) "
                    "solo lo que esté bien.\n\n")
            for u, r in pares:
                f.write(f"usuario: {u}\ncerebro: {r}\n\n")
        os.replace(ruta + ".tmp", ruta)
        return {"pares": len(pares), "archivo": os.path.relpath(ruta, os.path.dirname(self.dir))}
