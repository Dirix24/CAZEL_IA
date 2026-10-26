# -*- coding: utf-8 -*-
"""
Cuarentena y biblioteca.

  descargas de la puerta  ->  CUARENTENA  --(tú apruebas)-->  BIBLIOTECA
                                  |
                                  +--(tú rechazas)--> se borra

Solo lo que está en la biblioteca se usa para "investigar": CAZEL busca en
esos textos y te enseña los pasajes más parecidos a tu pregunta, con su
fuente. No inventa: si no hay nada relevante, lo dice.
"""

import os
import re
import unicodedata

from .seguridad import ruta_dentro

_NOMBRE_VALIDO = re.compile(r"[a-z0-9_]{1,80}(?:__[a-z]{2,3})?\.txt")
_PALABRAS_VACIAS = {
    "que", "los", "las", "una", "uno", "unos", "unas", "del", "con", "por", "para", "como",
    "pero", "mas", "sus", "esta", "este", "esto", "eso", "ese", "esa", "son", "fue", "han",
    "hay", "muy", "sobre", "entre", "cual", "cuales", "donde", "cuando", "quien", "the",
    "and", "for", "are", "was", "with", "that", "this", "from", "what", "how",
}


def _sin_acentos(t):
    return unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("ascii").lower()


def _palabras(t):
    return {p for p in re.findall(r"[a-z0-9]+", _sin_acentos(t))
            if len(p) > 2 and p not in _PALABRAS_VACIAS}


def _leer_cabecera(ruta):
    meta, cuerpo = {}, []
    try:
        with open(ruta, "r", encoding="utf-8", errors="replace") as f:
            en_cabecera = True
            for linea in f:
                if en_cabecera and linea.startswith("# "):
                    k, _, v = linea[2:].partition(":")
                    meta[k.strip()] = v.strip()
                elif en_cabecera and not linea.strip():
                    en_cabecera = False
                else:
                    en_cabecera = False
                    cuerpo.append(linea)
    except OSError:
        pass
    return meta, "".join(cuerpo)


class Biblioteca:
    def __init__(self, dir_cuarentena, dir_biblioteca, auditoria=None):
        self.dir_cuarentena = dir_cuarentena
        self.dir_biblioteca = dir_biblioteca
        self.auditoria = auditoria

    def _anotar(self, evento, **datos):
        if self.auditoria:
            self.auditoria.registrar(evento, **datos)

    def _ruta(self, carpeta, nombre):
        if not isinstance(nombre, str) or not _NOMBRE_VALIDO.fullmatch(nombre):
            raise ValueError("Nombre de archivo no válido.")
        os.makedirs(carpeta, exist_ok=True)
        ruta = ruta_dentro(carpeta, os.path.join(carpeta, nombre))
        if ruta is None:
            raise ValueError("Ruta no permitida.")
        return ruta

    def _listar(self, carpeta):
        if not os.path.isdir(carpeta):
            return []
        filas = []
        for n in sorted(os.listdir(carpeta)):
            if not _NOMBRE_VALIDO.fullmatch(n):
                continue
            ruta = os.path.join(carpeta, n)
            if not os.path.isfile(ruta):
                continue
            meta, _ = _leer_cabecera(ruta)
            filas.append({"archivo": n, "bytes": os.path.getsize(ruta),
                          "titulo": meta.get("titulo", n), "fuente": meta.get("fuente", ""),
                          "descargado": meta.get("descargado", "")})
        return filas

    def listar_cuarentena(self):
        return self._listar(self.dir_cuarentena)

    def listar_biblioteca(self):
        return self._listar(self.dir_biblioteca)

    def vista_previa(self, nombre, caracteres=1500):
        """Primeros caracteres de un texto en cuarentena, para que lo revises."""
        ruta = self._ruta(self.dir_cuarentena, nombre)
        if not os.path.isfile(ruta):
            raise ValueError("Ese archivo no está en cuarentena.")
        meta, cuerpo = _leer_cabecera(ruta)
        return {"archivo": nombre, "titulo": meta.get("titulo", nombre),
                "fuente": meta.get("fuente", ""), "texto": cuerpo[:max(100, int(caracteres))]}

    def aprobar(self, nombre):
        origen = self._ruta(self.dir_cuarentena, nombre)
        if not os.path.isfile(origen):
            raise ValueError("Ese archivo no está en cuarentena.")
        destino = self._ruta(self.dir_biblioteca, nombre)
        os.replace(origen, destino)
        self._anotar("texto_aprobado", archivo=nombre)
        return {"archivo": nombre, "estado": "aprobado"}

    def rechazar(self, nombre):
        origen = self._ruta(self.dir_cuarentena, nombre)
        if not os.path.isfile(origen):
            raise ValueError("Ese archivo no está en cuarentena.")
        os.remove(origen)
        self._anotar("texto_rechazado", archivo=nombre)
        return {"archivo": nombre, "estado": "rechazado"}

    def buscar(self, consulta, limite=3, max_archivos=300):
        """Pasajes de la biblioteca más parecidos a la consulta (por palabras)."""
        buscadas = _palabras(consulta)
        if not buscadas or not os.path.isdir(self.dir_biblioteca):
            return []
        candidatos = []
        for n in sorted(os.listdir(self.dir_biblioteca))[:max_archivos]:
            if not _NOMBRE_VALIDO.fullmatch(n):
                continue
            meta, cuerpo = _leer_cabecera(os.path.join(self.dir_biblioteca, n))
            titulo = meta.get("titulo", n)
            bonus_titulo = len(buscadas & _palabras(titulo))
            for parrafo in re.split(r"\n\s*\n|\n", cuerpo):
                parrafo = parrafo.strip()
                if len(parrafo) < 15:
                    continue
                aciertos = len(buscadas & _palabras(parrafo))
                if aciertos:
                    candidatos.append((aciertos + bonus_titulo * 0.5, titulo,
                                       meta.get("fuente", ""), parrafo[:600]))
        candidatos.sort(key=lambda c: c[0], reverse=True)
        return [{"puntos": round(p, 2), "titulo": t, "fuente": f, "texto": x}
                for p, t, f, x in candidatos[:max(1, min(int(limite), 10))]]
