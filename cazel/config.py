# -*- coding: utf-8 -*-
"""
Configuración de CAZEL IA.

Todo es PORTABLE: las rutas se calculan desde la carpeta donde está CAZEL
(el USB), así que al mover la carpeta a otro equipo sigue funcionando y
todo lo que escribe queda dentro de ella.

Los ajustes se pueden cambiar editando `datos/ajustes.json`; lo que no
aparezca ahí toma el valor por defecto de AJUSTES_POR_DEFECTO.
"""

import copy
import json
import os
import sys

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Si existe la carpeta `libs/` (creada con `pip install --target libs numpy`),
# se usa antes que lo instalado en el equipo: así el USB lleva sus propias
# dependencias. Solo vale para el mismo sistema operativo y versión de Python.
_LIBS = os.path.join(RAIZ, "libs")
if os.path.isdir(_LIBS) and _LIBS not in sys.path:
    sys.path.insert(0, _LIBS)

DIR_CEREBRO = os.path.join(RAIZ, "cerebro")
DIR_DATOS = os.environ.get("CAZEL_DATOS") or os.path.join(RAIZ, "datos")

RUTA_AJUSTES = os.path.join(DIR_DATOS, "ajustes.json")


def rutas(datos=None):
    """Todas las carpetas/archivos de trabajo, derivadas de la carpeta de datos."""
    d = os.path.abspath(datos or DIR_DATOS)
    return {
        "datos": d,
        "memoria": os.path.join(d, "memoria.json"),
        "workspace": os.path.join(d, "workspace"),
        "diario": os.path.join(d, "diario"),
        "revision": os.path.join(d, "revision"),
        "cuarentena": os.path.join(d, "cuarentena"),
        "biblioteca": os.path.join(d, "biblioteca"),
        "robots": os.path.join(d, "robots"),
        "auditoria": os.path.join(d, "auditoria.log"),
        "ajustes": os.path.join(d, "ajustes.json"),
    }


AJUSTES_POR_DEFECTO = {
    "puerto_web": 8765,
    "minutos_inactividad": 20,      # sin usar la interfaz este tiempo -> se apaga sola (con PARAR)
    "internet": {
        # Solo estos dominios. Cualquier otro se rechaza en el código.
        "dominios": ["es.wikipedia.org", "en.wikipedia.org"],
        "minutos_permiso": 15,
        "max_minutos_permiso": 60,
        "max_paginas_por_permiso": 20,
        "max_bytes_pagina": 200000,
        "segundos_entre_peticiones": 1.0,
        "timeout_segundos": 15,
    },
    "espacio": {
        "aviso_porcentaje_usado": 90,
        "aviso_libre_mb": 50,
        "dias_cuarentena": 14,
        "dias_diario": 60,
        "dias_recuerdos_poco_importantes": 180,
        # Solo lo que se puede regenerar (cachés) o comprimir sin perder nada.
        "auto_limpieza_segura": True,
        # Bajo este mínimo, además de cachés, se pueden olvidar recuerdos triviales.
        "umbral_recuerdos_urgente_mb": 20,
        "auto_olvidar_recuerdos_triviales": True,
    },
    "robot": {
        "baudios": [115200, 9600],
        "espera_arranque_s": 2.0,       # los Arduino se reinician al abrir el puerto
        "timeout_respuesta_s": 2.0,
        "limite_ordenes": [20, 10],     # máximo 20 órdenes cada 10 segundos
        "tope_valor_absoluto": 100000,
    },
    # Motor de lenguaje más grande (Ollama, LM Studio...) SOLO en este mismo
    # equipo (127.0.0.1). Apagado por defecto.
    "motor_externo": {
        "activo": False,
        "auto_chat": True,  # con motor activo, conversación híbrida y respaldo offline
        "host": "http://127.0.0.1:11434/v1",
        "modelo": "",
        "timeout_segundos": 120,
    },
}


def _fusionar(base, extra):
    """Mezcla `extra` sobre `base` conservando el tipo de cada valor."""
    for clave, valor in (extra or {}).items():
        if clave not in base:
            continue
        if isinstance(base[clave], dict) and isinstance(valor, dict):
            _fusionar(base[clave], valor)
        elif type(valor) is type(base[clave]) or (
                isinstance(base[clave], float) and isinstance(valor, int)
                and not isinstance(valor, bool)):
            base[clave] = valor
    return base


def cargar_ajustes(ruta=None):
    """Ajustes por defecto + lo que haya en ajustes.json. Nunca lanza error:
    un archivo ausente o corrupto simplemente se ignora."""
    ajustes = copy.deepcopy(AJUSTES_POR_DEFECTO)
    try:
        with open(ruta or RUTA_AJUSTES, "r", encoding="utf-8") as f:
            _fusionar(ajustes, json.load(f))
    except (OSError, ValueError):
        pass
    return ajustes
