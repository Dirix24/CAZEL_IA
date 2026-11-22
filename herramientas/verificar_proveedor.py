"""Comprueba un proveedor configurado con una petición sintética."""

import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cazel.core.models import Router
from cazel.motor_externo import ErrorMotor


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("configuracion", type=Path, help="Ruta a core2-modelos.json")
    parser.add_argument("--autorizar-envio", action="store_true",
                        help="Autoriza el envío del ejercicio sintético al proveedor configurado")
    args = parser.parse_args()
    if not args.autorizar_envio:
        parser.error("Indica --autorizar-envio para enviar el ejercicio sintético.")
    router = Router({}, args.configuracion)
    try:
        response, mode = router.chat("online", True, [
            {"role": "user", "content": "¿Cuánto es 19 + 23? Responde únicamente con el número."},
        ], 30)
    except ErrorMotor as error:
        parser.exit(1, f"Verificación remota fallida. {error}\n")
    if mode != "online" or response.strip() != "42":
        parser.exit(1, "El proveedor respondió, pero no devolvió el valor de control esperado.\n")
    print("Proveedor remoto verificado. Respondió 42 al ejercicio sintético.")


if __name__ == "__main__":
    main()
