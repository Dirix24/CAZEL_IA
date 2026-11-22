#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CAZEL IA — arranque.

    python3 iniciar.py                 abre la interfaz en tu navegador
    python3 iniciar.py --sin-navegador  solo muestra la dirección
    python3 iniciar.py --puerto 9000    usa otro puerto
    python3 iniciar.py --datos /ruta    guarda memoria y descargas en otra carpeta

Normalmente no se ejecuta a mano: haz doble clic en INICIAR.bat (Windows),
INICIAR.command (Mac) o INICIAR.sh / INICIAR.desktop (Linux).
"""

import argparse
import os
import sys

RAIZ = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, RAIZ)


def _salir(mensaje):
    print("\n[!] " + mensaje + "\n")
    if os.name == "nt" or os.environ.get("CAZEL_ESPERAR"):
        input("Pulsa Enter para cerrar...")
    sys.exit(1)


def main():
    if sys.version_info < (3, 9):
        _salir(f"Necesito Python 3.9 o más nuevo y tienes {sys.version.split()[0]}.")
    ap = argparse.ArgumentParser(description="CAZEL IA")
    ap.add_argument("--sin-navegador", action="store_true")
    ap.add_argument("--puerto", type=int, default=None)
    ap.add_argument("--datos", default=None)
    ap.add_argument("--interfaz", choices=("terminal", "studio", "clasica"))
    ap.add_argument("--proyecto")
    args = ap.parse_args()
    if args.interfaz is None and sys.stdin.isatty() and not args.sin_navegador:
        print("1. CAZEL Terminal\n2. CAZEL Studio\n3. CAZEL clásico")
        args.interfaz = {"1": "terminal", "2": "studio", "3": "clasica"}.get(
            input("Interfaz [2]: ").strip(), "studio")

    from cazel import config as cfg          # añade libs/ al path si existe
    if args.interfaz == "terminal":
        from cazel.core.interface import Interface
        from cazel.core.terminal import terminal

        rutas = cfg.rutas(args.datos)
        ui = Interface(rutas["datos"], RAIZ, cfg.cargar_ajustes(rutas["ajustes"])["motor_externo"])
        try:
            terminal(ui, args.proyecto)
        finally:
            ui.close()
        return
    try:
        import numpy                          # noqa: F401
    except ImportError:
        _salir("Falta NumPy (lo usa Cerebro).\n    Con internet, ejecuta PREPARAR_USB una vez "
               "(o escribe: python3 -m pip install numpy).")
    from cazel.nucleo import Cazel, ErrorCazel
    from cazel.servidor import Servidor

    try:
        cazel = Cazel(datos=args.datos)
    except ErrorCazel as e:
        _salir(str(e))
    aj = cazel.ajustes
    srv = Servidor(cazel, puerto=args.puerto or aj["puerto_web"], abrir_navegador=not args.sin_navegador,
                   minutos_inactividad=aj.get("minutos_inactividad", 20),
                   pagina="/studio" if args.interfaz == "studio" else "/")
    print("=" * 56)
    print("  CAZEL IA está funcionando")
    print(f"  Dirección:  {srv.url}")
    print("  (si no se abrió sola, copia esa dirección en tu navegador)")
    print("  Para apagar: usa «Apagar CAZEL» en el menú ⋮ o pulsa Ctrl+C aquí.")
    print("=" * 56)
    srv.servir()
    print("CAZEL se apagó. Ya puedes quitar el USB con seguridad.")


if __name__ == "__main__":
    main()
