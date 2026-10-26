#!/bin/sh
# CAZEL IA - arranque en Linux / macOS
cd "$(dirname "$0")" || exit 1
for py in ./python_portatil/bin/python3 python3 python; do
  if [ -x "$py" ] || command -v "$py" >/dev/null 2>&1; then
    exec "$py" iniciar.py "$@"
  fi
done
echo "No encontré Python 3. Instálalo (en MX/Debian/Ubuntu: sudo apt install python3 python3-numpy)."
printf "Pulsa Enter para cerrar..."; read _
