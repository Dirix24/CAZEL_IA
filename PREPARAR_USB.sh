#!/bin/sh
# Descarga NumPy y pyserial DENTRO del USB (carpeta libs/). Necesita internet UNA vez.
# Ojo: lo descargado sirve solo para este sistema operativo y esta versión de Python.
cd "$(dirname "$0")" || exit 1
python3 -m pip install --upgrade --target libs numpy pyserial && echo "Listo: libs/ preparada."
printf "Pulsa Enter para cerrar..."; read _
