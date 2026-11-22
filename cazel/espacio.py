# -*- coding: utf-8 -*-
"""
Gestor de espacio del USB.

Qué hace:
  * mide el espacio libre y avisa cuando queda poco;
  * propone qué liberar, de lo menos valioso a lo más valioso;
  * libera SOLO lo que tú confirmas, con una excepción: lo "seguro" (cachés
    que se regeneran solas y compresión sin pérdida) puede hacerse sin
    preguntar si lo dejas activado en los ajustes.

Lo que NUNCA toca (lista de protegidos): el modelo entrenado, tu memoria,
la biblioteca aprobada, los perfiles de robots y los ajustes.

Seguridad: `liberar` no acepta rutas; acepta ids de una propuesta que se
vuelve a calcular en ese momento, y comprueba cada ruta contra la lista de
protegidos y contra la carpeta del programa.
"""

import gzip
import hashlib
import os
import shutil
import time

from .seguridad import ruta_dentro


def _id(tipo, ruta_rel):
    return hashlib.sha1(f"{tipo}|{ruta_rel}".encode("utf-8")).hexdigest()[:10]


class GestorEspacio:
    def __init__(self, raiz, datos, ajustes_espacio, memoria=None, auditoria=None,
                 uso_disco=shutil.disk_usage, reloj=time.time):
        self.raiz = os.path.realpath(raiz)
        self.datos = os.path.realpath(datos)
        self.aj = ajustes_espacio
        self.memoria = memoria
        self.auditoria = auditoria
        self._uso_disco = uso_disco
        self._reloj = reloj

    # -- protegidos ------------------------------------------------------------------

    def _protegidos(self):
        return [
            os.path.join(self.raiz, "cerebro", "checkpoints"),
            os.path.join(self.datos, "memoria.json"),
            os.path.join(self.datos, "core2.sqlite3"),
            os.path.join(self.datos, "core2-modelos.json"),
            os.path.join(self.datos, "ajustes.json"),
            os.path.join(self.datos, "biblioteca"),
            os.path.join(self.datos, "robots"),
        ]

    def es_protegido(self, ruta):
        real = os.path.realpath(ruta)
        for p in self._protegidos():
            p = os.path.realpath(p)
            try:
                if os.path.commonpath([real, p]) == p:
                    return True
            except ValueError:
                continue
        return False

    # -- medición --------------------------------------------------------------------

    def uso(self):
        os.makedirs(self.datos, exist_ok=True)
        total, usado, libre = self._uso_disco(self.datos)
        pct = round(100.0 * usado / total, 1) if total else 0.0
        alerta = (pct >= float(self.aj["aviso_porcentaje_usado"])
                  or libre < float(self.aj["aviso_libre_mb"]) * 1024 * 1024)
        mensaje = ("Queda poco espacio en el USB: conviene liberar un poco." if alerta
                   else "Hay espacio de sobra.")
        return {"total": total, "usado": usado, "libre": libre,
                "porcentaje_usado": pct, "alerta": alerta, "mensaje": mensaje}

    # -- propuesta -------------------------------------------------------------------

    def _edad_dias(self, ruta):
        try:
            return (self._reloj() - os.path.getmtime(ruta)) / 86400.0
        except OSError:
            return 0.0

    def candidatos(self):
        """Lista de cosas que se podrían liberar. Orden: de menor a mayor valor."""
        lista = []
        umbral_urgente = float(self.aj.get("umbral_recuerdos_urgente_mb", 20)) * 1024 * 1024
        limpieza_critica = (self.aj.get("auto_limpieza_segura", True)
                            and self.uso()["libre"] < umbral_urgente)

        def anadir(tipo, ruta, accion, motivo, seguro, bytes_=None):
            if tipo == "recuerdo":          # `ruta` es la clave del recuerdo, no una ruta
                lista.append({"id": _id(tipo, str(ruta)), "tipo": tipo, "ruta": str(ruta),
                              "bytes": int(bytes_ or 0), "accion": accion, "motivo": motivo,
                              "seguro_auto": bool(seguro)})
                return
            if self.es_protegido(ruta) or not os.path.exists(ruta):
                return
            real = ruta_dentro(self.raiz, ruta)
            if real is None:
                return
            rel = os.path.relpath(real, self.raiz)
            if bytes_ is None:
                try:
                    bytes_ = os.path.getsize(real)
                except OSError:
                    bytes_ = 0
            lista.append({"id": _id(tipo, rel), "tipo": tipo, "ruta": rel, "bytes": int(bytes_),
                          "accion": accion, "motivo": motivo, "seguro_auto": bool(seguro)})

        # 1) cachés de Python (se regeneran solas): UNA sola línea para todas
        caches, tam_caches = [], 0
        for base, dirs, _ in os.walk(self.raiz):
            for d in list(dirs):
                if d == "__pycache__":
                    ruta = os.path.join(base, d)
                    real = ruta_dentro(self.raiz, ruta)
                    if real is not None and not self.es_protegido(real):
                        caches.append(os.path.relpath(real, self.raiz))
                        tam_caches += sum(os.path.getsize(os.path.join(r, f))
                                          for r, _, fs in os.walk(real) for f in fs)
                    dirs.remove(d)
        if caches:
            lista.append({"id": _id("cache", "pycache"), "tipo": "cache",
                          "ruta": f"cachés de Python ({len(caches)} carpetas)", "rutas": sorted(caches),
                          "bytes": tam_caches, "accion": "borrar",
                          "motivo": "Cachés de Python: se regeneran solas al arrancar.",
                          "seguro_auto": True})

        # 2) archivos temporales que dejó un guardado interrumpido
        for base, _, fs in os.walk(self.datos):
            for f in fs:
                if f.endswith(".tmp"):
                    anadir("temporal", os.path.join(base, f), "borrar",
                           "Archivo temporal de un guardado interrumpido.", True)

        # 3) diario antiguo: se comprime (sin perder nada)
        dir_diario = os.path.join(self.datos, "diario")
        if os.path.isdir(dir_diario):
            dias = float(self.aj["dias_diario"])
            for n in sorted(os.listdir(dir_diario)):
                ruta = os.path.join(dir_diario, n)
                if n.endswith(".jsonl") and self._edad_dias(ruta) > dias:
                    anadir("diario", ruta, "comprimir",
                           f"Conversación de hace más de {int(dias)} días: se comprime sin perder nada.",
                           True)
                elif n.endswith(".jsonl.gz") and self._edad_dias(ruta) > dias * 4:
                    anadir("diario_viejo", ruta, "borrar",
                           f"Conversación comprimida de hace más de {int(dias * 4)} días.", limpieza_critica)

        # 4) cuarentena olvidada
        dir_cuar = os.path.join(self.datos, "cuarentena")
        if os.path.isdir(dir_cuar):
            dias = float(self.aj["dias_cuarentena"])
            for n in sorted(os.listdir(dir_cuar)):
                ruta = os.path.join(dir_cuar, n)
                if os.path.isfile(ruta) and self._edad_dias(ruta) > dias:
                    anadir("cuarentena", ruta, "borrar",
                           f"Texto sin revisar desde hace más de {int(dias)} días.", False)

        # 5) registro de auditoría grande
        aud = os.path.join(self.datos, "auditoria.log")
        if os.path.isfile(aud) and os.path.getsize(aud) > 128 * 1024:
            anadir("auditoria", aud, "borrar", "Registro de actividad grande (se vuelve a crear).",
                   limpieza_critica)

        # 6) recuerdos triviales: normalmente solo se proponen si son antiguos.
        # Con el USB en estado crítico pueden entrar también recuerdos recientes,
        # pero nunca los datos personales/nombre ni categorías de usuario/robot.
        if self.memoria is not None:
            dias = float(self.aj["dias_recuerdos_poco_importantes"])
            urgente = (self.aj.get("auto_olvidar_recuerdos_triviales", True)
                       and limpieza_critica)
            ahora = self._reloj()
            for clave, e in list(self.memoria.long_term_memory.items()):
                if (float(e.get("importancia", 1)) > 1
                        or str(clave).lower() in {"nombre", "usuario", "robot"}
                        or str(e.get("categoria", "")).lower() in {"usuario", "robot", "seguridad"}):
                    continue
                try:
                    import datetime
                    fecha = datetime.datetime.strptime(e.get("fecha", ""), "%Y-%m-%d %H:%M:%S")
                    edad = (ahora - fecha.timestamp()) / 86400.0
                except (ValueError, OSError):
                    continue
                if edad > dias or urgente:
                    razon = ("Recuerdo trivial; solo se olvida automáticamente con el USB casi lleno."
                             if urgente and edad <= dias else
                             f"Recuerdo poco importante de hace más de {int(dias)} días.")
                    anadir("recuerdo", clave, "olvidar", f"{razon} «{clave}».",
                           urgente, len(str(e)))
        return lista

    def propuesta(self):
        c = self.candidatos()
        return {"uso": self.uso(), "candidatos": c,
                "bytes_liberables": sum(x["bytes"] for x in c)}

    # -- ejecución -------------------------------------------------------------------

    def _ejecutar(self, c):
        """Aplica un candidato. Devuelve bytes liberados."""
        if c["tipo"] == "recuerdo":
            if self.memoria is not None and self.memoria.eliminar_largo_plazo(c["ruta"]):
                return c["bytes"]
            return 0
        if c["tipo"] == "cache":
            total = 0
            for rel in c.get("rutas", []):
                real = ruta_dentro(self.raiz, os.path.join(self.raiz, rel))
                if real is None or self.es_protegido(real) or not os.path.isdir(real) \
                        or os.path.basename(real) != "__pycache__":
                    continue
                total += sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(real) for f in fs)
                shutil.rmtree(real, ignore_errors=True)
            return total
        ruta = ruta_dentro(self.raiz, os.path.join(self.raiz, c["ruta"]))
        if ruta is None or self.es_protegido(ruta) or not os.path.exists(ruta):
            return 0
        if c["accion"] == "borrar":
            if os.path.isdir(ruta):
                tam = sum(os.path.getsize(os.path.join(r, f))
                          for r, _, fs in os.walk(ruta) for f in fs)
                shutil.rmtree(ruta)
                return tam
            tam = os.path.getsize(ruta)
            os.remove(ruta)
            return tam
        if c["accion"] == "comprimir":
            antes = os.path.getsize(ruta)
            destino = ruta + ".gz"
            with open(ruta, "rb") as f_in, gzip.open(destino + ".tmp", "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)
            os.replace(destino + ".tmp", destino)
            os.remove(ruta)
            return max(0, antes - os.path.getsize(destino))
        return 0

    def liberar(self, ids, confirmado=False):
        """Libera los candidatos cuyo id esté en `ids`. Exige confirmado=True."""
        if confirmado is not True:
            raise PermissionError("Hace falta tu confirmación para liberar espacio.")
        pedidos = set(ids or [])
        hechos, errores, liberado = [], [], 0
        for c in self.candidatos():
            if c["id"] not in pedidos:
                continue
            try:
                b = self._ejecutar(c)
                liberado += b
                hechos.append({"id": c["id"], "ruta": c["ruta"], "accion": c["accion"], "bytes": b})
            except OSError as e:
                errores.append({"id": c["id"], "error": str(e)})
        if self.auditoria:
            self.auditoria.registrar("espacio_liberado", elementos=len(hechos), bytes=liberado)
        return {"liberado": liberado, "hechos": hechos, "errores": errores,
                "desconocidos": sorted(pedidos - {c["id"] for c in hechos} - {e["id"] for e in errores})}

    def limpieza_automatica_segura(self):
        """Si falta espacio y los ajustes lo permiten, aplica solo lo 'seguro'."""
        if not self.aj.get("auto_limpieza_segura") or not self.uso()["alerta"]:
            return {"liberado": 0, "hechos": [], "errores": [], "desconocidos": []}
        candidatos = [c for c in self.candidatos() if c["seguro_auto"]]
        critico = self.uso()["libre"] < float(self.aj.get("umbral_recuerdos_urgente_mb", 20)) * 1024 * 1024
        if not critico:
            return self.liberar([c["id"] for c in candidatos], confirmado=True)
        # Modo crítico: borrar en orden y detenerse al recuperar el mínimo normal.
        objetivo = float(self.aj.get("aviso_libre_mb", 50)) * 1024 * 1024
        total = {"liberado": 0, "hechos": [], "errores": [], "desconocidos": []}
        for candidato in candidatos:
            if self.uso()["libre"] >= objetivo:
                break
            r = self.liberar([candidato["id"]], confirmado=True)
            total["liberado"] += r["liberado"]
            total["hechos"].extend(r["hechos"])
            total["errores"].extend(r["errores"])
            total["desconocidos"].extend(r["desconocidos"])
        return total
