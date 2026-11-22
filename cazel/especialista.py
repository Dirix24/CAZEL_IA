"""Adaptador JSON v1 de CAZEL para coordinación local."""

import argparse
import json
import re
from pathlib import Path
import sys
from threading import Event
from time import monotonic

from . import config
from .core.agent import Task
from .core.interface import Interface

from .core.analysis import context, inspect_file
from .core.runner import run_tests
from .core.workspace import Workspace

VERSION = 1


def proponer(proyecto, objetivo, datos):
    rutas = config.rutas(datos)
    local = config.cargar_ajustes(rutas["ajustes"])["motor_externo"]
    base = {"version": VERSION, "especialista": "CAZEL", "accion": "proponer"}
    if not local.get("activo"):
        return {**base, "estado": "no_disponible", "error": "Configura un modelo local en CAZEL."}
    interfaz = Interface(rutas["datos"], config.RAIZ, local)
    sesion = interfaz.agent.open(proyecto)
    tarea = Task(Event(), monotonic() + 65)

    def dejar_pendiente(cambio, _):
        return {"state": "pending", "id": cambio["id"], "path": cambio["path"],
                "nota": "La propuesta quedó pendiente de aprobación en CAZEL Studio."}

    resultado = interfaz.agent.run(
        sesion, objetivo + "\nPlanifica como máximo tres pasos. Usa write_file o apply_patch para "
        "dejar al menos una edición pendiente de revisión antes de finish. "
        "No puedes ejecutar pruebas en esta fase.", tarea, dejar_pendiente, steps=6,
    )
    propuestas = [{"tipo": "propuesta", "id": item["id"], "path": item["path"]}
                  for item in interfaz.store.changes(sesion) if item["state"] == "pending"]
    return {**base, "estado": "parcial" if propuestas else "no_disponible", "sesion": sesion,
            "evidencia": propuestas, "fase": resultado["state"],
            **({} if propuestas else {"error": "El motor local no produjo una propuesta revisable."})}


def coordinar(peticion, proyecto=None, *, permitir_pruebas=False, permitir_propuestas=False, datos=None):
    if not isinstance(peticion, dict) or type(peticion.get("version")) is not int or peticion["version"] != VERSION:
        raise ValueError("Se espera una solicitud versión 1.")
    base = {"version": VERSION, "especialista": "CAZEL"}
    accion = peticion.get("accion")
    if accion == "capacidades":
        return {**base, "estado": "ok", "capacidades": ["analizar", "probar", "proponer", "evidencia"]}
    objetivo = peticion.get("objetivo")
    if not isinstance(objetivo, str) or not 1 <= len(objetivo.strip()) <= 600:
        raise ValueError("Indica un objetivo de hasta 600 caracteres.")
    if accion not in ("analizar", "probar", "proponer", "evidencia"):
        raise ValueError("Acción CAZEL desconocida.")
    if proyecto is None:
        return {**base, "estado": "no_disponible", "error": "Selecciona previamente un proyecto CAZEL."}
    if accion == "proponer":
        if not permitir_propuestas:
            return {**base, "estado": "no_disponible", "error": "Las propuestas requieren permiso explícito."}
        return proponer(proyecto, objetivo, datos)
    ws = Workspace(proyecto, config.rutas(datos)["datos"])
    evidencia = []
    if accion == "evidencia":
        if not re.fullmatch(r"[0-9a-f]{32}", objetivo):
            raise ValueError("Identificador de sesión inválido.")
        interfaz = Interface(config.rutas(datos)["datos"], config.RAIZ, {})
        clave, _ = interfaz.store.session(objetivo)
        if clave != interfaz.store.project_key(ws.root):
            return {**base, "estado": "no_disponible", "error": "La sesión pertenece a otro proyecto."}
        evidencia = [{"tipo": "prueba_registrada", "state": evento["state"],
                      "returncode": evento["returncode"], "profile": evento["profile"]}
                     for evento in interfaz.store.history(objetivo) if evento["kind"] == "test"][-5:]
    elif accion == "probar":
        if not permitir_pruebas:
            return {**base, "estado": "no_disponible", "error": "Las pruebas requieren permiso explícito."}
        resultado = run_tests(ws, "python-unittest", "isolated", Event(), timeout=20)
        resultado["output"] = resultado["output"][:1500]
        evidencia.append({"tipo": "prueba", **resultado})
    else:
        for item in context(ws, objetivo):
            if item["language"] == "Texto":
                continue
            try:
                dato = inspect_file(item["path"], ws.read(item["path"]))
            except (OSError, ValueError):
                continue
            evidencia.append({"tipo": "analisis", **item,
                              "errores": dato.get("confirmed", [])[:8],
                              "simbolos": dato.get("symbols", [])[:12]})
            if len(evidencia) == 8:
                break
    estado = "ok" if evidencia else "parcial"
    if accion == "probar" and evidencia[0]["state"] != "passed":
        estado = "parcial"
    return {**base, "estado": estado, "accion": accion, "evidencia": evidencia}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proyecto", type=Path, help="Carpeta autorizada por el operador")
    parser.add_argument("--permitir-pruebas", action="store_true")
    parser.add_argument("--permitir-propuestas", action="store_true")
    parser.add_argument("--datos", type=Path)
    args = parser.parse_args()
    try:
        bruto = sys.stdin.buffer.read(32_769)
        if len(bruto) > 32_768:
            raise ValueError("Solicitud demasiado grande.")
        resultado = coordinar(json.loads(bruto.decode("utf-8")), args.proyecto,
                              permitir_pruebas=args.permitir_pruebas,
                              permitir_propuestas=args.permitir_propuestas, datos=args.datos)
    except (ValueError, OSError) as error:
        resultado = {"version": VERSION, "especialista": "CAZEL", "estado": "error", "error": str(error)}
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
