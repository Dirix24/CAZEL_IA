"""Adaptador JSON v1 de CAZEL para coordinación local."""

import argparse
import json
from pathlib import Path
import sys
from threading import Event

from .core.analysis import context, inspect_file
from .core.runner import run_tests
from .core.workspace import Workspace

VERSION = 1


def coordinar(peticion, proyecto=None, *, permitir_pruebas=False):
    if not isinstance(peticion, dict) or type(peticion.get("version")) is not int or peticion["version"] != VERSION:
        raise ValueError("Se espera una solicitud versión 1.")
    base = {"version": VERSION, "especialista": "CAZEL"}
    accion = peticion.get("accion")
    if accion == "capacidades":
        return {**base, "estado": "ok", "capacidades": ["analizar", "probar"]}
    objetivo = peticion.get("objetivo")
    if not isinstance(objetivo, str) or not 1 <= len(objetivo.strip()) <= 600:
        raise ValueError("Indica un objetivo de hasta 600 caracteres.")
    if accion not in ("analizar", "probar"):
        raise ValueError("Acción CAZEL desconocida.")
    if proyecto is None:
        return {**base, "estado": "no_disponible", "error": "Selecciona previamente un proyecto CAZEL."}
    ws = Workspace(proyecto, Path(__file__).resolve().parents[1] / "datos")
    evidencia = []
    if accion == "probar":
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
    args = parser.parse_args()
    try:
        bruto = sys.stdin.buffer.read(32_769)
        if len(bruto) > 32_768:
            raise ValueError("Solicitud demasiado grande.")
        resultado = coordinar(json.loads(bruto.decode("utf-8")), args.proyecto,
                              permitir_pruebas=args.permitir_pruebas)
    except (ValueError, OSError) as error:
        resultado = {"version": VERSION, "especialista": "CAZEL", "estado": "error", "error": str(error)}
    print(json.dumps(resultado, ensure_ascii=True))


if __name__ == "__main__":
    main()
