# -*- coding: utf-8 -*-
"""
Pruebas de CAZEL IA (solo librería estándar):

    python3 -m unittest discover -s tests -v        (desde la carpeta de CAZEL)

No usan internet ni hardware: Wikipedia, el robot y el disco se simulan.
"""

import gzip
import http.client
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import urllib.request

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RAIZ)

from cazel import config as cfg                                   # noqa: E402
from cazel import motor_externo                                   # noqa: E402
from cazel.biblioteca import Biblioteca                           # noqa: E402
from cazel.diario import Diario                                   # noqa: E402
from cazel.espacio import GestorEspacio                           # noqa: E402
from cazel.nucleo import Cazel                                    # noqa: E402
from cazel.puerta import (DestinoNoPermitido, ErrorPuerta, LimiteAlcanzado,  # noqa: E402
                          Puerta, PuertaCerrada)
from cazel.robot import analizador, protocolo, transporte         # noqa: E402
from cazel.robot.control import ErrorRobot, GestorRobots          # noqa: E402
from cazel.seguridad import Auditoria, LimiteRitmo, nombre_seguro, ruta_dentro  # noqa: E402
from cazel.servidor import Servidor                               # noqa: E402

AJ = cfg.AJUSTES_POR_DEFECTO


def tmp():
    d = tempfile.mkdtemp(prefix="cazel_test_")
    return d


class Base(unittest.TestCase):
    def setUp(self):
        self.d = tmp()
        self.addCleanup(shutil.rmtree, self.d, ignore_errors=True)


# ============================================================ seguridad / config
class TestSeguridad(Base):
    def test_ruta_dentro_bloquea_escapes(self):
        base = os.path.join(self.d, "base")
        os.makedirs(base)
        self.assertIsNotNone(ruta_dentro(base, os.path.join(base, "a.txt")))
        self.assertIsNone(ruta_dentro(base, os.path.join(base, "..", "fuera.txt")))
        self.assertIsNone(ruta_dentro(base, base))
        self.assertIsNone(ruta_dentro(base, base + "_vecina/x"))      # mismo prefijo, otra carpeta
        if hasattr(os, "symlink"):
            fuera = os.path.join(self.d, "fuera")
            os.makedirs(fuera)
            os.symlink(fuera, os.path.join(base, "enlace"))
            self.assertIsNone(ruta_dentro(base, os.path.join(base, "enlace", "x")))

    def test_nombre_seguro(self):
        self.assertEqual(nombre_seguro("Física cuántica (rama)"), "fisica_cuantica_rama")
        self.assertEqual(nombre_seguro("../../etc/passwd"), "etc_passwd")
        self.assertEqual(nombre_seguro("///"), "sin_nombre")
        self.assertLessEqual(len(nombre_seguro("a" * 500)), 60)

    def test_limite_ritmo(self):
        t = [0.0]
        l = LimiteRitmo(3, 10, reloj=lambda: t[0])
        self.assertTrue(all(l.permitido() for _ in range(3)))
        self.assertFalse(l.permitido())
        t[0] = 11
        self.assertTrue(l.permitido())

    def test_auditoria_rota_y_no_crece(self):
        a = Auditoria(os.path.join(self.d, "a.log"), max_bytes=2000)
        for i in range(200):
            a.registrar("evento", n=i, extra="x" * 50)
        self.assertLessEqual(os.path.getsize(a.ruta), 2500)
        self.assertEqual(a.ultimos(1)[0]["n"], "199")

    def test_ajustes_ignoran_tipos_malos_y_archivo_corrupto(self):
        ruta = os.path.join(self.d, "aj.json")
        with open(ruta, "w") as f:
            json.dump({"puerto_web": "mal", "internet": {"minutos_permiso": 5, "dominios": "x"},
                       "desconocido": 1}, f)
        a = cfg.cargar_ajustes(ruta)
        self.assertEqual(a["puerto_web"], 8765)                         # tipo erróneo: se ignora
        self.assertEqual(a["internet"]["minutos_permiso"], 5)           # tipo bueno: se aplica
        self.assertEqual(a["internet"]["dominios"], AJ["internet"]["dominios"])
        self.assertNotIn("desconocido", a)
        with open(ruta, "w") as f:
            f.write("{no es json")
        self.assertEqual(cfg.cargar_ajustes(ruta)["puerto_web"], 8765)
        self.assertEqual(cfg.cargar_ajustes(os.path.join(self.d, "no_existe.json"))["puerto_web"], 8765)


# ============================================================ puerta
def wiki_falso(respuestas):
    """Abridor falso: devuelve JSON según un fragmento de la URL."""
    llamadas = []

    def abridor(url):
        llamadas.append(url)
        for clave, cuerpo in respuestas.items():
            if clave in url:
                return json.dumps(cuerpo).encode("utf-8")
        raise AssertionError("URL inesperada: " + url)
    abridor.llamadas = llamadas
    return abridor


RESP_BUSCAR = {"query": {"search": [
    {"title": "Robot", "snippet": 'Un <span class="searchmatch">robot</span> es una m&aacute;quina'},
    {"title": "Robótica", "snippet": "Ciencia de los robots"}]}}
RESP_PAGINA = {"query": {"pages": {"123": {"pageid": 123, "title": "Robot", "extract": "Un robot es una máquina.\n\nSe usa en fábricas."}}}}
RESP_FALTA = {"query": {"pages": {"-1": {"title": "Zzz", "missing": ""}}}}


class TestPuerta(Base):
    def crear(self, respuestas=None, **aj):
        ajustes = json.loads(json.dumps(AJ["internet"]))
        ajustes.update(aj)
        self.t = [1000.0]
        self.dormidos = []
        ab = wiki_falso(respuestas or {})
        p = Puerta(os.path.join(self.d, "cuar"), ajustes, Auditoria(os.path.join(self.d, "aud.log")),
                   reloj=lambda: self.t[0], abridor=ab, dormir=self.dormidos.append)
        return p, ab

    def test_cerrada_por_defecto(self):
        p, ab = self.crear({"list=search": RESP_BUSCAR})
        self.assertFalse(p.estado()["abierta"])
        with self.assertRaises(PuertaCerrada):
            p.buscar("robot")
        self.assertEqual(ab.llamadas, [])                               # ni siquiera intentó salir

    def test_buscar_y_traer(self):
        p, ab = self.crear({"list=search": RESP_BUSCAR, "prop=extracts": RESP_PAGINA})
        p.abrir(5)
        r = p.buscar("robot")
        self.assertEqual([x["titulo"] for x in r], ["Robot", "Robótica"])
        self.assertEqual(r[0]["resumen"], "Un robot es una máquina")    # sin HTML ni entidades
        res = p.traer("Robot")
        ruta = os.path.join(self.d, "cuar", res["archivo"])
        self.assertTrue(os.path.isfile(ruta))
        txt = open(ruta, encoding="utf-8").read()
        self.assertIn("# fuente: https://es.wikipedia.org/wiki/Robot", txt)
        self.assertIn("# estado: cuarentena", txt)
        self.assertIn("Se usa en fábricas.", txt)
        self.assertTrue(all(u.startswith("https://es.wikipedia.org/w/api.php") for u in ab.llamadas))

    def test_pagina_inexistente(self):
        p, _ = self.crear({"prop=extracts": RESP_FALTA})
        p.abrir()
        with self.assertRaises(ErrorPuerta):
            p.traer("Zzz")

    def test_solo_https_y_solo_dominios_permitidos(self):
        p, _ = self.crear()
        for malo in ["http://es.wikipedia.org/w/api.php", "https://evil.com/", "https://es.wikipedia.org.evil.com/",
                     "https://user:pw@es.wikipedia.org/", "https://es.wikipedia.org:8443/", "ftp://es.wikipedia.org/",
                     "https://evil.com/?x=es.wikipedia.org", "file:///etc/passwd", "no es una url"]:
            with self.assertRaises(DestinoNoPermitido, msg=malo):
                p.validar_url(malo)
        p.validar_url("https://es.wikipedia.org/w/api.php?x=1")
        p.validar_url("https://en.wikipedia.org/w/api.php")

    def test_idiomas_no_permitidos(self):
        p, ab = self.crear()
        p.abrir()
        for idioma in ["fr", "../x", "es.evil.com", "", "ES\n", "xx"]:
            with self.assertRaises(DestinoNoPermitido, msg=idioma):
                p.buscar("hola", idioma)
        self.assertEqual(ab.llamadas, [])

    def test_permiso_caduca_solo(self):
        p, _ = self.crear({"list=search": RESP_BUSCAR})
        p.abrir(2)
        self.assertTrue(p.estado()["abierta"])
        self.t[0] += 2 * 60 + 1
        self.assertFalse(p.estado()["abierta"])
        with self.assertRaises(PuertaCerrada):
            p.buscar("robot")

    def test_minutos_con_tope_y_validacion(self):
        p, _ = self.crear()
        e = p.abrir(99999)
        self.assertLessEqual(e["segundos_restantes"], 60 * 60)
        with self.assertRaises(ErrorPuerta):
            p.abrir("abc")

    def test_maximo_de_peticiones_y_pausa(self):
        p, _ = self.crear({"list=search": RESP_BUSCAR}, max_paginas_por_permiso=3)
        p.abrir()
        for _ in range(3):
            p.buscar("robot")
        with self.assertRaises(LimiteAlcanzado):
            p.buscar("robot")
        self.assertEqual(len(self.dormidos), 2)                         # pausa entre peticiones
        p.abrir()                                                       # un permiso nuevo reinicia la cuenta
        p.buscar("robot")

    def test_cerrar_a_mano(self):
        p, _ = self.crear({"list=search": RESP_BUSCAR})
        p.abrir()
        p.cerrar()
        with self.assertRaises(PuertaCerrada):
            p.buscar("robot")

    def test_error_de_wikipedia_y_json_roto(self):
        p, _ = self.crear({"list=search": {"error": {"info": "bad"}}})
        p.abrir()
        with self.assertRaises(ErrorPuerta):
            p.buscar("x")
        p2 = Puerta(os.path.join(self.d, "c2"), AJ["internet"], abridor=lambda u: b"<html>no json</html>",
                    dormir=lambda s: None)
        p2.abrir()
        with self.assertRaises(ErrorPuerta):
            p2.buscar("x")

    def test_texto_de_busqueda_validado(self):
        p, _ = self.crear()
        p.abrir()
        with self.assertRaises(ErrorPuerta):
            p.buscar("")
        with self.assertRaises(ErrorPuerta):
            p.buscar("a" * 500)

    def test_redireccion_a_otro_dominio_se_rechaza(self):
        from cazel.puerta import _RedireccionSegura
        p, _ = self.crear()
        h = _RedireccionSegura(p.validar_url)
        with self.assertRaises(DestinoNoPermitido):
            h.redirect_request(urllib.request.Request("https://es.wikipedia.org/x"), None, 302, "Found", {},
                               "https://evil.com/robar")


# ============================================================ biblioteca
class TestBiblioteca(Base):
    def setUp(self):
        super().setUp()
        self.cu, self.bi = os.path.join(self.d, "cu"), os.path.join(self.d, "bi")
        os.makedirs(self.cu)
        self.b = Biblioteca(self.cu, self.bi)
        self.escribir("robot__es.txt", "Robot", "Un robot es una máquina programable capaz de realizar tareas.\n\n"
                      "La robótica industrial usa brazos mecánicos en las fábricas de coches.")
        self.escribir("cocina__es.txt", "Cocina", "La cocina mediterránea usa aceite de oliva, tomate y pescado fresco.")

    def escribir(self, nombre, titulo, cuerpo, carpeta=None):
        with open(os.path.join(carpeta or self.cu, nombre), "w", encoding="utf-8") as f:
            f.write(f"# titulo: {titulo}\n# fuente: https://es.wikipedia.org/wiki/{titulo}\n\n{cuerpo}")

    def test_flujo_cuarentena_aprobar_buscar(self):
        self.assertEqual(len(self.b.listar_cuarentena()), 2)
        self.assertEqual(self.b.buscar("robot"), [])                     # en cuarentena NO se usa
        self.b.aprobar("robot__es.txt")
        self.assertEqual(len(self.b.listar_cuarentena()), 1)
        r = self.b.buscar("qué es un robot programable")
        self.assertTrue(r and "máquina programable" in r[0]["texto"])
        self.assertIn("wikipedia.org", r[0]["fuente"])
        self.assertEqual(self.b.buscar("pescado"), [])                   # la cocina sigue en cuarentena

    def test_rechazar_borra(self):
        self.b.rechazar("cocina__es.txt")
        self.assertFalse(os.path.exists(os.path.join(self.cu, "cocina__es.txt")))

    def test_nombres_peligrosos(self):
        for n in ["../x.txt", "..\\x.txt", "/etc/passwd", "a/b.txt", "robot__es.txt\x00", "ROBOT.txt", "x" * 200 + ".txt",
                  "robot__es.txt/../../x", "", None, 5]:
            with self.assertRaises(ValueError, msg=repr(n)):
                self.b.aprobar(n)
        with self.assertRaises(ValueError):
            self.b.aprobar("noexiste__es.txt")

    def test_vista_previa_limitada(self):
        v = self.b.vista_previa("robot__es.txt", 120)
        self.assertEqual(v["titulo"], "Robot")
        self.assertLessEqual(len(v["texto"]), 120)

    def test_busqueda_sin_resultados(self):
        self.b.aprobar("robot__es.txt")
        self.assertEqual(self.b.buscar("zzzz qqqq"), [])
        self.assertEqual(self.b.buscar(""), [])


# ============================================================ espacio
class TestEspacio(Base):
    def setUp(self):
        super().setUp()
        self.raiz = os.path.join(self.d, "usb")
        self.datos = os.path.join(self.raiz, "datos")
        for r in ["cerebro/checkpoints", "cerebro/core/__pycache__", "datos/diario", "datos/cuarentena",
                  "datos/biblioteca", "datos/robots"]:
            os.makedirs(os.path.join(self.raiz, r))
        self.modelo = os.path.join(self.raiz, "cerebro/checkpoints/best.npz")
        for f, c in [("cerebro/checkpoints/best.npz", "MODELO"), ("datos/memoria.json", "{}"),
                     ("datos/ajustes.json", "{}"), ("datos/biblioteca/a__es.txt", "x"),
                     ("datos/robots/r.json", "{}"), ("cerebro/core/__pycache__/m.pyc", "x" * 1000),
                     ("datos/guardado.json.tmp", "tmp")]:
            with open(os.path.join(self.raiz, f), "w") as fh:
                fh.write(c)
        self.uso = [(1000 * 1024 * 1024, 100 * 1024 * 1024, 900 * 1024 * 1024)]
        self.t = time.time()

    def gestor(self, memoria=None, **aj):
        ajustes = dict(AJ["espacio"])
        ajustes.update(aj)
        return GestorEspacio(self.raiz, self.datos, ajustes, memoria=memoria,
                             uso_disco=lambda p: self.uso[0], reloj=lambda: self.t)

    def viejo(self, ruta, dias):
        t = self.t - dias * 86400
        os.utime(ruta, (t, t))

    def test_alerta_por_poco_espacio(self):
        g = self.gestor()
        self.assertFalse(g.uso()["alerta"])
        self.uso[0] = (1000 * 1024 * 1024, 960 * 1024 * 1024, 40 * 1024 * 1024)
        self.assertTrue(g.uso()["alerta"])

    def test_nunca_propone_lo_protegido(self):
        g = self.gestor()
        for c in g.candidatos():
            for tabu in ["best.npz", "memoria.json", "ajustes.json", "biblioteca", "robots", "checkpoints"]:
                self.assertNotIn(tabu, c["ruta"])
        self.assertTrue(g.es_protegido(self.modelo))
        self.assertTrue(g.es_protegido(os.path.join(self.datos, "biblioteca", "a__es.txt")))

    def test_liberar_exige_confirmacion(self):
        g = self.gestor()
        ids = [c["id"] for c in g.candidatos()]
        self.assertTrue(ids)
        with self.assertRaises(PermissionError):
            g.liberar(ids)
        with self.assertRaises(PermissionError):
            g.liberar(ids, confirmado="si")
        self.assertTrue(os.path.exists(os.path.join(self.raiz, "cerebro/core/__pycache__")))

    def test_liberar_caches_y_temporales(self):
        g = self.gestor()
        r = g.liberar([c["id"] for c in g.candidatos()], confirmado=True)
        self.assertGreaterEqual(r["liberado"], 1000)
        self.assertFalse(os.path.exists(os.path.join(self.raiz, "cerebro/core/__pycache__")))
        self.assertFalse(os.path.exists(os.path.join(self.datos, "guardado.json.tmp")))
        self.assertTrue(os.path.exists(self.modelo))

    def test_ids_desconocidos_o_rutas_no_hacen_nada(self):
        g = self.gestor()
        r = g.liberar(["../../../etc/passwd", "zzz", self.modelo], confirmado=True)
        self.assertEqual(r["hechos"], [])
        self.assertEqual(len(r["desconocidos"]), 3)
        self.assertTrue(os.path.exists(self.modelo))

    def test_diario_viejo_se_comprime_sin_perder(self):
        ruta = os.path.join(self.datos, "diario", "2020-01-01.jsonl")
        contenido = '{"t":"10:00","rol":"usuario","texto":"hola"}\n' * 200
        with open(ruta, "w") as f:
            f.write(contenido)
        self.viejo(ruta, 400)
        g = self.gestor()
        c = [x for x in g.candidatos() if x["tipo"] == "diario"]
        self.assertEqual(len(c), 1)
        r = g.liberar([c[0]["id"]], confirmado=True)
        self.assertGreater(r["liberado"], 0)
        self.assertFalse(os.path.exists(ruta))
        with gzip.open(ruta + ".gz", "rt") as f:
            self.assertEqual(f.read(), contenido)

    def test_cuarentena_olvidada_y_recuerdos_viejos(self):
        q = os.path.join(self.datos, "cuarentena", "x__es.txt")
        open(q, "w").write("x")
        self.viejo(q, 30)
        sys.path.insert(0, os.path.join(RAIZ, "cerebro"))
        from memory.advanced_memory import AdvancedMemoryManager        # de Cerebro
        mem = AdvancedMemoryManager(filepath=os.path.join(self.d, "m.json"))
        mem.guardar_largo_plazo("dato_viejo", "v", importancia=1)
        mem.guardar_largo_plazo("dato_importante", "v", importancia=3)
        mem.long_term_memory["dato_viejo"]["fecha"] = "2000-01-01 00:00:00"
        mem.long_term_memory["dato_importante"]["fecha"] = "2000-01-01 00:00:00"
        g = self.gestor(memoria=mem)
        tipos = {c["tipo"]: c for c in g.candidatos()}
        self.assertIn("cuarentena", tipos)
        self.assertIn("recuerdo", tipos)
        self.assertEqual(tipos["recuerdo"]["ruta"], "dato_viejo")        # el importante nunca se propone
        g.liberar([tipos["recuerdo"]["id"], tipos["cuarentena"]["id"]], confirmado=True)
        self.assertIsNone(mem.recuperar_largo_plazo("dato_viejo"))
        self.assertEqual(mem.recuperar_largo_plazo("dato_importante"), "v")
        self.assertFalse(os.path.exists(q))

    def test_limpieza_automatica_solo_si_hay_alerta_y_solo_lo_seguro(self):
        q = os.path.join(self.datos, "cuarentena", "x__es.txt")
        open(q, "w").write("x")
        self.viejo(q, 30)
        g = self.gestor()
        self.assertEqual(g.limpieza_automatica_segura()["liberado"], 0)   # sin alerta: nada
        self.uso[0] = (1000 * 1024 * 1024, 990 * 1024 * 1024, 10 * 1024 * 1024)
        g.limpieza_automatica_segura()
        self.assertFalse(os.path.exists(os.path.join(self.raiz, "cerebro/core/__pycache__")))   # seguro: sí
        self.assertTrue(os.path.exists(q))                                # cuarentena: pide permiso
        self.assertTrue(os.path.exists(self.modelo))
        g2 = self.gestor(auto_limpieza_segura=False)
        os.makedirs(os.path.join(self.raiz, "cerebro/core/__pycache__"))
        g2.limpieza_automatica_segura()
        self.assertTrue(os.path.exists(os.path.join(self.raiz, "cerebro/core/__pycache__")))


# ============================================================ diario
class TestDiario(Base):
    def test_anotar_ultimos_y_exportar(self):
        dr = Diario(os.path.join(self.d, "di"), os.path.join(self.d, "re"))
        dr.anotar("usuario", "hola")
        dr.anotar("ia", "¡Hola! ¿En qué ayudo?")
        dr.anotar("usuario", "/estado")
        dr.anotar("ia", "=== ESTADO ===")
        dr.anotar("usuario", "qué es un byte")
        dr.anotar("ia", "Un grupo de ocho bits.")
        self.assertEqual(len(dr.ultimos(10)), 6)
        r = dr.exportar_para_revision()
        self.assertEqual(r["pares"], 2)                                  # los comandos no se exportan
        txt = open(os.path.join(self.d, "re", "dialogos_pendientes.txt"), encoding="utf-8").read()
        self.assertIn("usuario: qué es un byte\ncerebro: Un grupo de ocho bits.", txt)
        self.assertNotIn("/estado", txt)

    def test_diario_vacio_y_directorio_imposible(self):
        dr = Diario(os.path.join(self.d, "di"), os.path.join(self.d, "re"))
        self.assertEqual(dr.exportar_para_revision()["pares"], 0)
        bloqueo = os.path.join(self.d, "archivo")
        open(bloqueo, "w").write("x")
        Diario(os.path.join(bloqueo, "dentro"), self.d).anotar("usuario", "x")   # no debe lanzar


# ============================================================ protocolo y robot
AYUDA_OK = ["CAZEL 1 mi_robot", "ORDEN avanzar cm:0:50", "ORDEN girar grados:-180:180", "ORDEN parar",
            "LECTURA distancia cm", "FIN"]


class TestProtocolo(unittest.TestCase):
    def test_parsear_ayuda_valida(self):
        p = protocolo.parsear_ayuda(AYUDA_OK)
        self.assertEqual(p["nombre"], "mi_robot")
        self.assertEqual(p["ordenes"]["avanzar"], {"parametro": "cm", "min": 0.0, "max": 50.0})
        self.assertEqual(p["ordenes"]["parar"]["parametro"], None)
        self.assertEqual(p["lecturas"]["distancia"]["unidad"], "cm")

    def test_ayuda_invalida(self):
        casos = [
            [], ["hola"], ["CAZEL 2 x", "FIN"], ["CAZEL 1 mi robot", "FIN"] if False else ["CAZEL 1 Mi-Robot!", "FIN"],
            AYUDA_OK[:-1],                                                # sin FIN
            ["CAZEL 1 r", "ORDEN avanzar cm:50:0", "FIN"],                # rango invertido
            ["CAZEL 1 r", "ORDEN avanzar cm:0", "FIN"],                   # parámetro mal declarado
            ["CAZEL 1 r", "ORDEN avanzar cm:0:nan", "FIN"],
            ["CAZEL 1 r", "ORDEN avanzar cm:0:inf", "FIN"],
            ["CAZEL 1 r", "ORDEN ayuda", "FIN"],                          # nombre reservado
            ["CAZEL 1 r", "ORDEN Av-anzar", "FIN"],
            ["CAZEL 1 r"] + [f"ORDEN o{i}" for i in range(60)] + ["FIN"],  # demasiadas
        ]
        for c in casos:
            with self.assertRaises(protocolo.ErrorProtocolo, msg=str(c)):
                protocolo.parsear_ayuda(c)

    def test_construir_orden_valida_rango_y_numeros(self):
        p = protocolo.parsear_ayuda(AYUDA_OK)
        self.assertEqual(protocolo.construir_orden(p, "avanzar", "20"), "avanzar 20")
        self.assertEqual(protocolo.construir_orden(p, "AVANZAR", 12.5), "avanzar 12.5")
        self.assertEqual(protocolo.construir_orden(p, "girar", "-90"), "girar -90")
        self.assertEqual(protocolo.construir_orden(p, "parar"), "PARAR")
        for n, v in [("avanzar", "51"), ("avanzar", "-1"), ("avanzar", "nan"), ("avanzar", "inf"), ("avanzar", "1e400"),
                     ("avanzar", "10\nPARAR"), ("avanzar", "10; apagar"), ("avanzar", ""), ("avanzar", None),
                     ("saltar", "1"), ("", None), ("avanzar", "0x10"), ("avanzar", "١٢")]:
            with self.assertRaises(protocolo.ErrorProtocolo, msg=f"{n} {v!r}"):
                protocolo.construir_orden(p, n, v)

    def test_orden_sin_parametro_no_acepta_valor(self):
        p = protocolo.validar_perfil({"nombre": "r", "ordenes": {"saludar": {"parametro": None}}})
        self.assertEqual(protocolo.construir_orden(p, "saludar"), "saludar")
        with self.assertRaises(protocolo.ErrorProtocolo):
            protocolo.construir_orden(p, "saludar", "5")

    def test_validar_perfil_rechaza_basura(self):
        for malo in [None, [], {"nombre": "A b"}, {"nombre": "r", "baudios": 123},
                     {"nombre": "r", "ordenes": {"ok": {"parametro": "x", "min": 5, "max": 1}}},
                     {"nombre": "r", "ordenes": {"x y": {}}}, {"nombre": "r", "lecturas": {"ayuda": {}}}]:
            with self.assertRaises(protocolo.ErrorProtocolo, msg=str(malo)):
                protocolo.validar_perfil(malo)

    def test_respuestas(self):
        self.assertEqual(protocolo.parsear_respuesta("OK"), ("ok", None))
        self.assertEqual(protocolo.parsear_respuesta("err algo malo"), ("err", "algo malo"))
        self.assertEqual(protocolo.parsear_respuesta("VAL 12.5"), ("val", 12.5))
        self.assertEqual(protocolo.parsear_respuesta("VAL nan")[0], "err")
        self.assertEqual(protocolo.parsear_respuesta("basura")[0], "otro")

    def test_formatear_numero(self):
        self.assertEqual(protocolo.formatear_numero(20.0), "20")
        self.assertEqual(protocolo.formatear_numero(0.5), "0.5")
        self.assertEqual(protocolo.formatear_numero(-3.1), "-3.1")


def crear_gestor(d, **aj):
    ajustes = json.loads(json.dumps(AJ["robot"]))
    ajustes.update(aj)
    ajustes["timeout_respuesta_s"] = 0.2
    inst = []

    def abrir(puerto, baudios):
        tr = transporte.SimTransporte()
        inst.append(tr)
        return tr
    return GestorRobots(os.path.join(d, "robots"), ajustes, abrir_transporte=abrir), inst


class TestRobot(Base):
    def conectar(self, **aj):
        g, inst = crear_gestor(self.d, **aj)
        det = g.detectar("simulado")
        g.conectar("simulado", det["perfil"])
        return g, inst[-1]

    def test_escanear_no_envia_nada(self):
        g, inst = crear_gestor(self.d)
        puertos = g.escanear()
        self.assertIn("simulado", [p["puerto"] for p in puertos])
        self.assertEqual(inst, [])                                       # no se abrió ningún puerto

    def test_detectar_envia_solo_ayuda(self):
        g, inst = crear_gestor(self.d)
        r = g.detectar("simulado")
        self.assertTrue(r["encontrado"])
        self.assertEqual(inst[0].historial, ["AYUDA"])

    def test_detectar_dispositivo_mudo_o_que_no_habla_cazel(self):
        class Mudo(transporte.SimTransporte):
            def escribir_linea(self, t):
                self.historial.append(t)

        class Otro(transporte.SimTransporte):
            def escribir_linea(self, t):
                self.historial.append(t)
                self._salida.extend(["Marlin 2.0", "ok"])
        for clase in (Mudo, Otro):
            g = GestorRobots(os.path.join(self.d, "r"), dict(AJ["robot"], timeout_respuesta_s=0.1),
                             abrir_transporte=lambda p, b, c=clase: c())
            r = g.detectar("simulado")
            self.assertFalse(r["encontrado"])

    def test_puertos_no_validos(self):
        g, _ = crear_gestor(self.d)
        for p in ["/dev/sda", "/etc/passwd", "/dev/mem", "COM1000", "../../dev/ttyUSB0", "/dev/ttyUSB0/../sda", ""]:
            with self.assertRaises(ErrorRobot, msg=p):
                g.detectar(p)

    def test_ordenes_validas_e_invalidas(self):
        g, sim = self.conectar()
        self.assertEqual(g.ejecutar("avanzar", "20"), "Hecho: avanzar 20")
        self.assertEqual(g.leer("distancia")["valor"], 80)
        enviadas = len(sim.historial)
        for n, v in [("avanzar", "999"), ("avanzar", "nan"), ("saltar", "1"), ("avanzar", "5\nPARAR"), ("girar", None)]:
            with self.assertRaises(ErrorRobot, msg=f"{n} {v}"):
                g.ejecutar(n, v)
        self.assertEqual(len(sim.historial), enviadas)                   # nada inválido llegó al robot
        self.assertNotIn("avanzar 999", sim.historial)

    def test_lectura_desconocida(self):
        g, _ = self.conectar()
        with self.assertRaises(ErrorRobot):
            g.leer("temperatura")

    def test_sin_robot_conectado(self):
        g, _ = crear_gestor(self.d)
        for f in (lambda: g.ejecutar("avanzar", "1"), g.parar, lambda: g.leer("distancia")):
            with self.assertRaises(ErrorRobot):
                f()

    def test_limite_de_ritmo_pero_parar_siempre_pasa(self):
        g, sim = self.conectar(limite_ordenes=[3, 60])
        for _ in range(3):
            g.ejecutar("avanzar", "1")
        with self.assertRaises(ErrorRobot) as cm:
            g.ejecutar("avanzar", "1")
        self.assertIn("Demasiadas", str(cm.exception))
        g.parar()
        self.assertEqual(sim.paradas, 1)

    def test_desconectar_envia_parar_antes(self):
        g, sim = self.conectar()
        self.assertTrue(g.desconectar())
        self.assertEqual(sim.paradas, 1)
        self.assertFalse(g.estado()["conectado"])
        self.assertFalse(g.desconectar())

    def test_una_sola_conexion(self):
        g, _ = self.conectar()
        with self.assertRaises(ErrorRobot):
            g.conectar("simulado", g.perfiles()[0] if g.perfiles() else g._perfil)

    def test_perdida_de_conexion_se_gestiona(self):
        g, sim = self.conectar()
        sim.cerrar()
        with self.assertRaises(ErrorRobot):
            g.ejecutar("avanzar", "1")
        self.assertFalse(g.estado()["conectado"])

    def test_perfiles_guardar_listar_borrar_y_corruptos(self):
        g, _ = crear_gestor(self.d)
        p = g.detectar("simulado")["perfil"]
        g.guardar_perfil(p)
        self.assertEqual([x["nombre"] for x in g.perfiles()], ["robot_simulado"])
        with open(os.path.join(g.dir, "roto.json"), "w") as f:
            f.write("{no json")
        with open(os.path.join(g.dir, "malo.json"), "w") as f:
            json.dump({"nombre": "a b"}, f)
        self.assertEqual(len(g.perfiles()), 1)                           # los dañados se ignoran
        self.assertTrue(g.borrar_perfil("robot_simulado"))
        with self.assertRaises(protocolo.ErrorProtocolo):
            g.guardar_perfil({"nombre": "../../x", "ordenes": {}})


# ============================================================ puerto serie real (con un pty)
@unittest.skipUnless(sys.platform.startswith("linux") and transporte.termios is not None, "solo Linux")
class TestSerieTermios(Base):
    def test_detectar_y_controlar_por_un_puerto_real(self):
        import pty

        maestro, esclavo = pty.openpty()
        ruta = os.path.realpath(os.ttyname(esclavo))
        os.environ["CAZEL_PERMITIR_PTY"] = "1"
        self.addCleanup(os.environ.pop, "CAZEL_PERMITIR_PTY", None)
        recibido, parar = [], threading.Event()

        def robot():
            buf = b""
            import select
            while not parar.is_set():
                if not select.select([maestro], [], [], 0.05)[0]:
                    continue
                try:
                    buf += os.read(maestro, 256)
                except OSError:
                    return
                while b"\n" in buf:
                    linea, _, buf = buf.partition(b"\n")
                    t = linea.decode().strip()
                    recibido.append(t)
                    if t == "AYUDA":
                        respuesta = "\r\n".join(AYUDA_OK) + "\r\n"
                    elif t.startswith("avanzar") or t == "PARAR":
                        respuesta = "OK\r\n"
                    elif t == "LEER distancia":
                        respuesta = "VAL 42\r\n"
                    else:
                        respuesta = "ERR ?\r\n"
                    os.write(maestro, respuesta.encode())
        hilo = threading.Thread(target=robot, daemon=True)
        hilo.start()
        self.addCleanup(lambda: (parar.set(), hilo.join(2), os.close(maestro), os.close(esclavo)))

        ajustes = dict(AJ["robot"], espera_arranque_s=0.0, timeout_respuesta_s=1.5)
        g = GestorRobots(os.path.join(self.d, "r"), ajustes)
        det = g.detectar(ruta)
        self.assertTrue(det["encontrado"], det)
        g.conectar(ruta, det["perfil"])
        self.assertEqual(g.ejecutar("avanzar", "10"), "Hecho: avanzar 10")
        self.assertEqual(g.leer("distancia")["valor"], 42)
        g.desconectar()
        for _ in range(40):
            if "PARAR" in recibido:
                break
            time.sleep(0.05)
        self.assertIn("PARAR", recibido)
        self.assertEqual(recibido[0], "AYUDA")

    def test_puerto_inexistente_o_no_permitido(self):
        with self.assertRaises(transporte.ErrorTransporte):
            transporte.SerieTransporte("/dev/sda")
        with self.assertRaises(transporte.ErrorTransporte):
            transporte.SerieTransporte("/dev/ttyUSB99", espera_arranque=0)


# ============================================================ analizador de código
CODIGO = open(os.path.join(RAIZ, "ejemplos", "mi_robot_original.ino"), encoding="utf-8").read()


class TestAnalizador(unittest.TestCase):
    def test_encuentra_lo_esperado(self):
        i = analizador.analizar_codigo(CODIGO)
        plan = i["plan"]
        self.assertEqual(plan["servos"][0]["pin"], "9")
        self.assertEqual([x["pin"] for x in plan["pwm"]], ["5"])
        self.assertIn("13", [x["pin"] for x in plan["digitales"]])
        self.assertEqual(plan["ultrasonico"], {"echo": "8", "trig": "7"})
        self.assertEqual(i["baudios"], 9600)
        self.assertIn("avanzar", i["ordenes_existentes"])
        self.assertIn("distancia", i["propuesta"]["lecturas"])
        protocolo.validar_perfil(dict(i["propuesta"], nombre="mi_robot"))   # la propuesta es un perfil válido

    def test_ignora_comentarios(self):
        i = analizador.analizar_codigo("// pinMode(3, OUTPUT); analogWrite(3, 5);\n/* Servo s; s.attach(4); */\nvoid setup(){}")
        self.assertEqual(i["plan"]["pwm"], [])
        self.assertEqual(i["plan"]["servos"], [])

    def test_entradas_malas(self):
        for malo in ["", "   ", None, 5, "x" * 300000]:
            with self.assertRaises(ValueError, msg=str(malo)[:20]):
                analizador.analizar_codigo(malo)

    def test_baudios_raros_se_avisan(self):
        i = analizador.analizar_codigo("void setup(){ Serial.begin(250000); pinMode(3,OUTPUT); analogWrite(3,1);}")
        self.assertEqual(i["baudios"], 115200)
        self.assertTrue(any("250000" in n for n in i["notas"]))

    def test_adaptador_contenido_y_nombre(self):
        i = analizador.analizar_codigo(CODIGO)
        s = analizador.generar_adaptador(i, "brazo_uno")
        for esperado in ['"CAZEL 1 "', "ORDEN servo_9 grados:0:180", "ORDEN pwm_5 valor:0:255", "ORDEN pin_13 estado:0:1",
                         "LECTURA distancia cm", "LECTURA analogico_a0", '"FIN"', "pararTodo", "WATCHDOG_MS"]:
            self.assertIn(esperado, s)
        for malo in ["Mi Robot", "ayuda", "../x", "", "1robot", "a" * 40]:
            with self.assertRaises(ValueError, msg=malo):
                analizador.generar_adaptador(i, malo)

    @unittest.skipUnless(shutil.which("g++"), "g++ no disponible")
    def test_adaptador_compila_como_c_plus_plus(self):
        d = tmp()
        self.addCleanup(shutil.rmtree, d, ignore_errors=True)
        with open(os.path.join(d, "Arduino.h"), "w") as f:
            f.write("""#pragma once
#include <stdlib.h>
#include <string.h>
#define HIGH 1
#define LOW 0
#define OUTPUT 1
#define INPUT 0
#define A0 14
typedef unsigned char byte;
struct SerialT { void begin(long); int available(); int read(); void print(const char*); void print(long);
  void println(const char*); void println(long); void println(int); };
extern SerialT Serial;
void pinMode(int,int); void digitalWrite(int,int); void analogWrite(int,int); int analogRead(int);
unsigned long millis(); void delayMicroseconds(unsigned int); long pulseIn(int,int,unsigned long);
""")
        with open(os.path.join(d, "Servo.h"), "w") as f:
            f.write("#pragma once\nstruct Servo { void attach(int); void write(int); };\n")
        casos = [CODIGO, "void setup(){ pinMode(3, OUTPUT); analogWrite(3, 1); }",
                 "#include <Servo.h>\nServo a; Servo b;\nvoid setup(){ a.attach(3); b.attach(4); }"]
        for n, codigo in enumerate(casos):
            sketch = analizador.generar_adaptador(analizador.analizar_codigo(codigo), "robot_x")
            ruta = os.path.join(d, f"t{n}.cpp")
            with open(ruta, "w") as f:
                f.write("#include <Arduino.h>\n" + sketch + "\nint main(){ setup(); loop(); }\n")
            r = subprocess.run(["g++", "-fsyntax-only", "-Wall", "-Wextra", "-I", d, ruta],
                               capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr)


# ============================================================ motor externo
class TestMotorExterno(unittest.TestCase):
    ACTIVO = {"activo": True, "host": "http://127.0.0.1:11434/v1", "modelo": "qwen", "timeout_segundos": 5}

    def test_apagado_por_defecto_y_solo_local(self):
        with self.assertRaises(motor_externo.ErrorMotor):
            motor_externo.consultar(AJ["motor_externo"], "hola")
        for host in ["http://evil.com/v1", "https://127.0.0.1/v1", "http://127.0.0.1.evil.com/v1",
                     "http://user@127.0.0.1/v1", "http://192.168.1.5:11434/v1", "ftp://localhost/"]:
            with self.assertRaises(motor_externo.ErrorMotor, msg=host):
                motor_externo.consultar(dict(self.ACTIVO, host=host), "hola")
        with self.assertRaises(motor_externo.ErrorMotor):
            motor_externo.consultar(dict(self.ACTIVO, modelo=""), "hola")

    def test_respuesta_correcta_y_formato_roto(self):
        vistas = []

        def ok(req):
            vistas.append((req.full_url, json.loads(req.data)))
            return json.dumps({"choices": [{"message": {"content": "  Hola  "}}]}).encode()
        self.assertEqual(motor_externo.consultar(self.ACTIVO, "¿qué haces?", abridor=ok), "Hola")
        self.assertEqual(vistas[0][0], "http://127.0.0.1:11434/v1/chat/completions")
        self.assertEqual(vistas[0][1]["model"], "qwen")
        with self.assertRaises(motor_externo.ErrorMotor):
            motor_externo.consultar(self.ACTIVO, "x", abridor=lambda r: b"[]")
        with self.assertRaises(motor_externo.ErrorMotor):
            motor_externo.consultar(self.ACTIVO, "x", abridor=lambda r: b"no json")
        with self.assertRaises(motor_externo.ErrorMotor):
            motor_externo.consultar(self.ACTIVO, "")


# ============================================================ núcleo (todo junto)
class TestNucleo(Base):
    def crear(self, respuestas=None, **kw):
        self.ab = wiki_falso(respuestas or {})
        c = Cazel(datos=self.d, abridor_web=self.ab, abrir_transporte=lambda p, b: transporte.SimTransporte(),
                  dormir=lambda s: None, **kw)
        return c

    def test_conversacion_de_cerebro_y_memoria(self):
        c = self.crear()
        self.assertTrue(c.estado()["modelo"]["cargado"])
        self.assertIn("84", c.chat("cuánto es 12 por 7")[0])
        c.chat("me llamo Danny")
        self.assertIn("Danny", c.chat("cómo me llamo")[0])
        self.assertEqual(c.memoria.recuperar_largo_plazo("nombre"), "Danny")
        self.assertTrue(os.path.isfile(os.path.join(self.d, "memoria.json")))   # escribe en datos/, no en cerebro/

    def test_cerebro_no_escribe_fuera_de_datos(self):
        antes = set()
        for base, _, fs in os.walk(os.path.join(RAIZ, "cerebro")):
            antes |= {os.path.join(base, f) for f in fs if not f.endswith(".pyc")}
        c = self.crear()
        c.chat("me llamo Ana")
        c.chat("/escribir nota.txt hola")
        despues = set()
        for base, _, fs in os.walk(os.path.join(RAIZ, "cerebro")):
            despues |= {os.path.join(base, f) for f in fs if not f.endswith(".pyc")}
        self.assertEqual(antes, despues)
        self.assertTrue(os.path.isfile(os.path.join(self.d, "workspace", "nota.txt")))

    def test_sin_modelo_los_comandos_siguen_funcionando(self):
        c = self.crear(cargar_modelo=False)
        self.assertIn("no está cargado", c.chat("hola")[0])
        self.assertIn("Comandos de CAZEL", c.chat("/ayuda")[0])
        self.assertIn("Modelo: no cargado", c.chat("/estado")[0])

    def test_ayuda_incluye_cazel_y_cerebro(self):
        t = self.crear().chat("/ayuda")[0]
        self.assertIn("/internet", t)
        self.assertIn("/recordar", t)

    def test_investigar_en_internet_con_permiso_y_cuarentena(self):
        c = self.crear({"list=search": RESP_BUSCAR, "prop=extracts": RESP_PAGINA})
        self.assertIn("cerrada", c.chat("/wiki robot")[0])
        c.chat("/internet 5")
        self.assertIn("Robot", c.chat("busca en wikipedia robot")[0])
        self.assertIn("cuarentena", c.chat("/traer Robot")[0])
        self.assertIn("No tengo nada", c.chat("investiga máquina fábricas")[0])    # aún sin aprobar
        self.assertIn("robot__es.txt", c.chat("/cuarentena")[0])
        c.chat("/casa")
        self.assertIn("cerrada", c.chat("/wiki robot")[0])
        self.assertIn("ya está en mi biblioteca", c.chat("/aprobar robot__es.txt")[0])
        r = c.chat("investiga máquina fábricas")[0]
        self.assertIn("Se usa en fábricas", r)
        self.assertIn("wikipedia.org/wiki/Robot", r)

    def test_robot_de_extremo_a_extremo_y_parar_natural(self):
        c = self.crear()
        self.assertIn("no hay ningún robot", c.chat("para")[0].lower())
        self.assertIn("Encontré", c.chat("/detectar simulado")[0])
        self.assertIn("Conectado", c.chat("/conectar simulado")[0])
        self.assertIn("Hecho", c.chat("/orden avanzar 10")[0])
        self.assertIn("distancia", c.chat("/sensor distancia")[0])
        self.assertIn("acepta de 0 a 50", c.chat("/orden avanzar 500")[0])
        self.assertIn("PARAR", c.chat("STOP!")[0])
        self.assertIn("Desconectado", c.chat("/desconectar")[0])

    def test_descarga_rechazada_si_no_hay_espacio(self):
        c = self.crear({"prop=extracts": RESP_PAGINA}, uso_disco=lambda p: (100 * 2**20, 100 * 2**20 - 1000, 1000))
        c.chat("/internet")
        self.assertIn("No hay espacio", c.chat("/traer Robot")[0])
        self.assertEqual(self.ab.llamadas, [])

    def test_diario_registra_la_conversacion(self):
        c = self.crear()
        c.chat("hola")
        filas = c.diario.ultimos(5)
        self.assertEqual([f["rol"] for f in filas], ["usuario", "ia"])

    def test_cierre_envia_parar_y_cierra_puerta(self):
        c = self.crear()
        c.chat("/internet")
        c.chat("/conectar simulado")
        c.cerrar()
        self.assertFalse(c.puerta.estado()["abierta"])
        self.assertFalse(c.robots.estado()["conectado"])

    def test_mensajes_vacios_o_enormes(self):
        c = self.crear()
        self.assertEqual(c.chat("   ")[0], "")
        self.assertIn("demasiado largo", c.chat("a" * 5000)[0])

    def test_consulta_sin_motor_explica_como_activarlo(self):
        self.assertIn("apagado", self.crear().chat("/consulta hola")[0])


# ============================================================ servidor web
class TestServidor(Base):
    def setUp(self):
        super().setUp()
        self.cazel = Cazel(datos=self.d, abrir_transporte=lambda p, b: transporte.SimTransporte())
        self.srv = Servidor(self.cazel, puerto=0, abrir_navegador=False)
        self.hilo = threading.Thread(target=self.srv.servir, daemon=True)
        self.hilo.start()
        self.addCleanup(self._parar)
        self.host = f"127.0.0.1:{self.srv.puerto}"

    def _parar(self):
        self.srv.parar()
        self.hilo.join(5)

    def pedir(self, metodo, ruta, cuerpo=None, cabeceras=None, token=True, ctype="application/json", host=None):
        con = http.client.HTTPConnection("127.0.0.1", self.srv.puerto, timeout=10)
        h = {"Host": host or self.host}
        if token:
            h["X-Cazel-Token"] = self.srv.token
        if cuerpo is not None:
            h["Content-Type"] = ctype
        h.update(cabeceras or {})
        data = cuerpo if isinstance(cuerpo, (bytes, type(None))) else json.dumps(cuerpo).encode()
        con.request(metodo, ruta, body=data, headers=h)
        r = con.getresponse()
        cuerpo_r = r.read()
        con.close()
        return r.status, cuerpo_r, r

    def api(self, accion, datos=None, **kw):
        s, b, _ = self.pedir("POST", "/api/" + accion, datos or {}, **kw)
        return s, json.loads(b)

    def test_pagina_y_archivos_estaticos(self):
        s, b, r = self.pedir("GET", "/", token=False)
        self.assertEqual(s, 200)
        self.assertIn(self.srv.token, b.decode())
        self.assertNotIn("__TOKEN__", b.decode())
        self.assertIn("script-src 'self'", r.getheader("Content-Security-Policy"))
        self.assertEqual(r.getheader("Cache-Control"), "no-store")
        for ruta in ("/app.js", "/app.css"):
            self.assertEqual(self.pedir("GET", ruta, token=False)[0], 200)
        self.assertEqual(self.pedir("GET", "/../servidor.py", token=False)[0], 404)
        self.assertEqual(self.pedir("GET", "/web/../../iniciar.py", token=False)[0], 404)

    def test_studio_comparte_api_y_protege_los_cambios(self):
        self.assertIn(b"CAZEL Studio", self.pedir("GET", "/studio", token=False)[1])
        self.assertEqual(self.pedir("GET", "/studio.js", token=False)[0], 200)
        self.assertEqual(self.api("core2/sessions", token=False)[0], 401)
        self.assertEqual(self.api("core2/sessions", cabeceras={"Origin": "https://otro.test"})[0], 403)
        proyecto = tmp()
        self.addCleanup(shutil.rmtree, proyecto, True)
        status, opened = self.api("core2/open", {"path": proyecto})
        self.assertEqual(status, 200)
        session = {"session": opened["session"]}
        status, proposed = self.api("core2/stage", {**session, "path": "main.py", "content": "x = 1"})
        self.assertEqual(status, 200)
        self.assertIn("+x = 1", proposed["diff"])
        ruta = os.path.join(proyecto, "main.py")
        self.assertFalse(os.path.exists(ruta))
        change = {**session, "id": proposed["id"]}
        self.assertEqual(self.api("core2/accept", change)[0], 200)
        self.assertTrue(os.path.isfile(ruta))
        self.assertEqual(self.api("core2/read", {**session, "path": "../main.py"})[0], 400)
        self.assertEqual(self.api("core2/undo", change)[0], 200)
        self.assertFalse(os.path.exists(ruta))

    def test_sin_token_o_con_token_falso(self):
        self.assertEqual(self.pedir("GET", "/api/estado", token=False)[0], 401)
        self.assertEqual(self.pedir("GET", "/api/estado", token=False, cabeceras={"X-Cazel-Token": "falso"})[0], 401)
        self.assertEqual(self.api("chat", {"texto": "hola"}, token=False)[0], 401)
        self.assertEqual(self.pedir("GET", "/api/estado")[0], 200)

    def test_host_y_origin_protegen_de_paginas_ajenas(self):
        self.assertEqual(self.pedir("GET", "/", host="evil.com", token=False)[0], 403)
        self.assertEqual(self.pedir("GET", "/", host=f"evil.com:{self.srv.puerto}", token=False)[0], 403)
        self.assertEqual(self.api("chat", {"texto": "x"}, cabeceras={"Origin": "http://evil.com"})[0], 403)
        self.assertEqual(self.api("chat", {"texto": "x"}, cabeceras={"Origin": f"http://{self.host}"})[0], 200)
        self.assertEqual(self.api("chat", {"texto": "x"}, host="localhost:%d" % self.srv.puerto)[0], 200)

    def test_solo_json_y_tamano_limitado(self):
        self.assertEqual(self.pedir("POST", "/api/chat", b'{"texto":"x"}', ctype="text/plain")[0], 415)
        self.assertEqual(self.pedir("POST", "/api/chat", b"{no json")[0], 400)
        self.assertEqual(self.pedir("POST", "/api/chat", b"[1,2]")[0], 400)
        self.assertEqual(self.pedir("POST", "/api/chat", b"x" * 500_000)[0], 413)
        self.assertEqual(self.pedir("POST", "/api/no_existe", {})[0], 404)
        self.assertEqual(self.pedir("POST", "/otra", {})[0], 404)

    def test_chat_robot_y_errores_sin_traceback(self):
        self.assertIn("84", self.api("chat", {"texto": "cuánto es 12 por 7"})[1]["respuesta"])
        self.assertEqual(self.api("robots_escanear")[0], 200)
        self.assertTrue(self.api("robots_conectar", {"puerto": "simulado"})[1]["conectado"])
        self.assertEqual(self.api("robots_orden", {"nombre": "avanzar", "valor": 12})[0], 200)
        s, d = self.api("robots_orden", {"nombre": "avanzar", "valor": 9999})
        self.assertEqual(s, 400)
        self.assertNotIn("Traceback", json.dumps(d))
        self.assertEqual(self.api("robots_orden", {"nombre": "avanzar", "valor": {"a": 1}})[0], 200 if False else 400)
        self.assertEqual(self.api("chat", {"texto": 5})[0], 400)
        self.assertEqual(self.api("robots_conectar", {"puerto": "/dev/sda"})[0], 400)
        self.assertTrue(self.api("estado")[1]["robot"]["conectado"])
        self.assertEqual(self.api("robots_parar")[0], 200)

    def test_puerta_y_cuarentena_por_api(self):
        self.assertFalse(self.api("estado")[1]["puerta"]["abierta"])
        self.assertTrue(self.api("puerta", {"accion": "abrir", "minutos": 5})[1]["abierta"])
        self.assertFalse(self.api("puerta", {"accion": "cerrar"})[1]["abierta"])
        self.assertEqual(self.api("puerta", {"accion": "hackear"})[0], 400)
        for nombre in ["../../etc/passwd", "a/b.txt", "..\\x"]:
            self.assertEqual(self.api("aprobar", {"archivo": nombre})[0], 400)
            self.assertEqual(self.api("cuarentena_ver", {"archivo": nombre})[0], 400)
        self.assertEqual(self.api("wiki_buscar", {"consulta": "robot"})[0], 400)          # puerta cerrada

    def test_espacio_por_api_exige_confirmacion(self):
        p = self.api("espacio")[1]
        ids = [c["id"] for c in p["candidatos"]]
        s, _ = self.api("espacio_liberar", {"ids": ids})
        self.assertEqual(s, 400)
        self.assertEqual(self.api("espacio_liberar", {"ids": "todo", "confirmado": True})[0], 400)
        self.assertEqual(self.api("espacio_liberar", {"ids": ids, "confirmado": True})[0], 200)
        self.assertTrue(os.path.exists(os.path.join(RAIZ, "cerebro", "checkpoints", "best.npz")))

    def test_codigo_por_api(self):
        s, d = self.api("codigo_adaptador", {"codigo": CODIGO, "nombre": "brazo_uno"})
        self.assertEqual(s, 200)
        self.assertIn("CAZEL 1", d["sketch"])
        self.assertEqual(self.api("codigo_adaptador", {"codigo": CODIGO, "nombre": "Mal Nombre"})[0], 400)
        self.assertEqual(self.api("codigo_analizar", {"codigo": ""})[0], 400)

    def test_parada_independiente_de_una_tarea_activa(self):
        self.assertTrue(self.api("robots_conectar", {"puerto": "simulado"})[1]["conectado"])
        robot = self.cazel.robots._tr
        proyecto = tmp()
        self.addCleanup(shutil.rmtree, proyecto, True)
        _, opened = self.api("core2/open", {"path": proyecto})
        data = {"session": opened["session"]}
        started, release = threading.Event(), threading.Event()

        def model(*args):
            started.set()
            release.wait(5)
            return '{"tool":"finish","args":{"summary":"Fin de la prueba"}}', "offline"

        with patch.object(self.srv.studio.agent.router, "chat", side_effect=model):
            try:
                self.assertEqual(self.api("core2/start", {**data, "prompt": "Revisa el proyecto"})[0], 200)
                self.assertTrue(started.wait(3))
                self.assertTrue(self.api("core2/status", data)[1]["active"])
                self.assertEqual(self.api("robots_parar")[0], 200)
                self.assertEqual(robot.historial[-1], "PARAR")
                self.assertTrue(self.api("core2/status", data)[1]["active"])
            finally:
                release.set()
                deadline = time.monotonic() + 3
                while self.api("core2/status", data)[1]["active"] and time.monotonic() < deadline:
                    time.sleep(0.05)
            self.assertFalse(self.api("core2/status", data)[1]["active"])

    def test_apagar_envia_parar_al_robot(self):
        self.api("robots_conectar", {"puerto": "simulado"})
        self.assertTrue(self.api("apagar")[1]["apagando"])
        self.hilo.join(5)
        self.assertFalse(self.hilo.is_alive())
        self.assertFalse(self.cazel.robots.estado()["conectado"])

    def test_se_apaga_sola_por_inactividad(self):
        self.srv.inactividad_s = 0.2
        self.srv.ultima_actividad = time.monotonic() - 10
        self.hilo.join(8)
        self.assertFalse(self.hilo.is_alive())

    def test_solo_escucha_en_local(self):
        self.assertEqual(self.srv.httpd.server_address[0], "127.0.0.1")


if __name__ == "__main__":
    unittest.main(verbosity=2)
