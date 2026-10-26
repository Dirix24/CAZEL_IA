# -*- coding: utf-8 -*-
"""
La PUERTA de CAZEL: la única parte del programa que habla con internet.

Reglas (se hacen cumplir en el código, no son una promesa):
  * Por defecto está CERRADA. Se abre solo si tú lo pides, por unos minutos,
    y se vuelve a cerrar sola al terminar el tiempo.
  * Solo se puede hablar con los dominios de la lista blanca (por defecto,
    es.wikipedia.org y en.wikipedia.org), solo por HTTPS y solo a través de la
    API oficial de Wikipedia. Una redirección a otro dominio se rechaza.
  * Hay un tope de peticiones por permiso y una pausa entre peticiones.
  * Lo descargado NO se usa directamente: va a la carpeta de CUARENTENA y tú
    decides si lo apruebas (ver biblioteca.py).
  * Todo queda anotado en el registro de auditoría.

Importante y honesto: esta puerta es un candado dentro del programa. Protege
contra errores y contra un uso accidental, pero no sustituye a desconectar el
equipo de la red si necesitas aislamiento total.
"""

import datetime
import html
import json
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from .seguridad import nombre_seguro

USER_AGENT = "CAZEL-IA/0.1 (proyecto educativo local; lectura de Wikipedia)"
LIMITE_RESPUESTA_BYTES = 4_000_000
LICENCIA = "CC BY-SA 4.0 (texto de Wikipedia; si lo compartes, cita la fuente y la licencia)"


class ErrorPuerta(Exception):
    """Error normal de la puerta (mensaje pensado para mostrarse al usuario)."""


class PuertaCerrada(ErrorPuerta):
    pass


class DestinoNoPermitido(ErrorPuerta):
    pass


class LimiteAlcanzado(ErrorPuerta):
    pass


class _RedireccionSegura(urllib.request.HTTPRedirectHandler):
    def __init__(self, validar):
        self._validar = validar

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        self._validar(newurl)       # lanza DestinoNoPermitido si se sale de la lista
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class Puerta:
    def __init__(self, dir_cuarentena, ajustes_internet, auditoria=None,
                 reloj=time.monotonic, abridor=None, dormir=time.sleep):
        self.dir_cuarentena = dir_cuarentena
        self.aj = ajustes_internet
        self.auditoria = auditoria
        self._reloj = reloj
        self._dormir = dormir
        self._abridor = abridor or self._abrir_real
        self._lock = threading.RLock()
        self._abierta = False
        self._hasta = 0.0
        self._peticiones = 0
        self._ultima = None

    # -- estado ---------------------------------------------------------------------

    def _anotar(self, evento, **datos):
        if self.auditoria:
            self.auditoria.registrar(evento, **datos)

    def _revisar_vencimiento(self):
        if self._abierta and self._reloj() >= self._hasta:
            self._abierta = False
            self._anotar("puerta_cerrada", motivo="tiempo agotado")

    def estado(self):
        with self._lock:
            self._revisar_vencimiento()
            restante = max(0, int(self._hasta - self._reloj())) if self._abierta else 0
            return {
                "abierta": self._abierta,
                "segundos_restantes": restante,
                "peticiones_usadas": self._peticiones,
                "peticiones_max": int(self.aj["max_paginas_por_permiso"]),
                "dominios": list(self.aj["dominios"]),
            }

    def abrir(self, minutos=None):
        """Da permiso de internet por `minutos` (con un máximo en los ajustes)."""
        with self._lock:
            if minutos is None:
                minutos = self.aj["minutos_permiso"]
            try:
                minutos = float(minutos)
            except (TypeError, ValueError):
                raise ErrorPuerta("Los minutos deben ser un número.")
            minutos = max(1.0, min(minutos, float(self.aj["max_minutos_permiso"])))
            self._abierta = True
            self._hasta = self._reloj() + minutos * 60
            self._peticiones = 0
            self._anotar("puerta_abierta", minutos=minutos)
            return self.estado()

    def cerrar(self):
        with self._lock:
            if self._abierta:
                self._anotar("puerta_cerrada", motivo="cerrada por el usuario")
            self._abierta = False
            self._hasta = 0.0
            return self.estado()

    # -- control de destino ------------------------------------------------------------

    def validar_url(self, url):
        """Lanza DestinoNoPermitido salvo que sea https a un dominio de la lista."""
        try:
            p = urllib.parse.urlsplit(str(url))
            puerto = p.port
        except ValueError:
            raise DestinoNoPermitido("Dirección no válida.")
        host = (p.hostname or "").lower()
        permitido = (p.scheme == "https" and host in {d.lower() for d in self.aj["dominios"]}
                     and not p.username and not p.password and puerto in (None, 443))
        if not permitido:
            self._anotar("destino_rechazado", url=url)
            raise DestinoNoPermitido(
                "Destino no permitido. Solo puedo hablar con: " + ", ".join(self.aj["dominios"]))
        return url

    def _idiomas(self):
        return {d.split(".")[0].lower() for d in self.aj["dominios"]
                if d.lower().endswith(".wikipedia.org")}

    def _api(self, idioma):
        idioma = str(idioma).lower()
        if not re.fullmatch(r"[a-z]{2,3}", idioma) or idioma not in self._idiomas():
            raise DestinoNoPermitido(
                "Idioma no permitido. Disponibles: " + ", ".join(sorted(self._idiomas())))
        return idioma, f"https://{idioma}.wikipedia.org/w/api.php"

    # -- red -------------------------------------------------------------------------------

    def _abrir_real(self, url):
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT,
                                                   "Accept": "application/json"})
        opener = urllib.request.build_opener(_RedireccionSegura(self.validar_url))
        with opener.open(req, timeout=float(self.aj["timeout_segundos"])) as r:
            datos = r.read(LIMITE_RESPUESTA_BYTES + 1)
        if len(datos) > LIMITE_RESPUESTA_BYTES:
            raise ErrorPuerta("La respuesta es demasiado grande.")
        return datos

    def _pedir_json(self, url):
        with self._lock:
            self._revisar_vencimiento()
            if not self._abierta:
                raise PuertaCerrada("La puerta está cerrada. Dame permiso de internet primero.")
            self.validar_url(url)
            if self._peticiones >= int(self.aj["max_paginas_por_permiso"]):
                raise LimiteAlcanzado("Alcancé el máximo de peticiones de este permiso. "
                                      "Ciérralo y ábrelo de nuevo si quieres seguir.")
            pausa = float(self.aj["segundos_entre_peticiones"])
            if self._ultima is not None and pausa > 0:
                espera = pausa - (self._reloj() - self._ultima)
                if espera > 0:
                    self._dormir(espera)
            self._peticiones += 1
            self._ultima = self._reloj()
            self._anotar("peticion", url=url)
        try:
            bruto = self._abridor(url)
            datos = json.loads(bruto.decode("utf-8", errors="replace"))
        except ErrorPuerta:
            raise
        except urllib.error.URLError as e:
            raise ErrorPuerta(f"No pude conectar: {getattr(e, 'reason', e)}")
        except (OSError, ValueError) as e:
            raise ErrorPuerta(f"Respuesta inesperada de Wikipedia: {e}")
        if isinstance(datos, dict) and "error" in datos:
            raise ErrorPuerta("Wikipedia devolvió un error: "
                              + str(datos["error"].get("info", datos["error"]))[:200])
        return datos

    # -- acciones -------------------------------------------------------------------------

    @staticmethod
    def _limpiar_texto(t, maximo):
        t = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", str(t)).strip()
        if not t or len(t) > maximo:
            raise ErrorPuerta(f"El texto debe tener entre 1 y {maximo} caracteres.")
        return t

    def buscar(self, consulta, idioma="es", limite=5):
        consulta = self._limpiar_texto(consulta, 200)
        idioma, api = self._api(idioma)
        limite = max(1, min(int(limite), 10))
        url = api + "?" + urllib.parse.urlencode({
            "action": "query", "list": "search", "srsearch": consulta, "srlimit": limite,
            "format": "json", "utf8": 1})
        datos = self._pedir_json(url)
        resultados = []
        for r in (datos.get("query", {}).get("search", []) or [])[:limite]:
            resumen = html.unescape(re.sub(r"<[^>]+>", "", r.get("snippet", "")))
            resultados.append({"titulo": str(r.get("title", ""))[:200], "resumen": resumen[:300],
                               "idioma": idioma})
        return resultados

    def traer(self, titulo, idioma="es"):
        """Descarga el texto de una página y lo deja en CUARENTENA."""
        titulo = self._limpiar_texto(titulo, 200)
        idioma, api = self._api(idioma)
        url = api + "?" + urllib.parse.urlencode({
            "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "plain",
            "titles": titulo, "redirects": 1, "format": "json", "utf8": 1})
        datos = self._pedir_json(url)
        paginas = (datos.get("query", {}) or {}).get("pages", {}) or {}
        pagina = next(iter(paginas.values()), None)
        if not isinstance(pagina, dict) or "missing" in pagina or not pagina.get("extract"):
            raise ErrorPuerta(f"No encontré una página llamada «{titulo}».")
        real = str(pagina.get("title", titulo))[:200]
        texto = str(pagina["extract"])[: int(self.aj["max_bytes_pagina"])]
        url_pagina = f"https://{idioma}.wikipedia.org/wiki/" + urllib.parse.quote(real.replace(" ", "_"))
        nombre = f"{nombre_seguro(real)}__{idioma}.txt"
        cabecera = (f"# titulo: {real}\n# fuente: {url_pagina}\n# licencia: {LICENCIA}\n"
                    f"# descargado: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"# estado: cuarentena\n\n")
        os.makedirs(self.dir_cuarentena, exist_ok=True)
        destino = os.path.join(self.dir_cuarentena, nombre)
        tmp = destino + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(cabecera + texto)
        os.replace(tmp, destino)
        self._anotar("pagina_en_cuarentena", archivo=nombre, caracteres=len(texto))
        return {"archivo": nombre, "titulo": real, "fuente": url_pagina, "caracteres": len(texto)}
