"""Ensamblado nativo con un CPython portable y dependencias preparadas."""

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python-portatil", type=Path, required=True)
    parser.add_argument("--libs", type=Path, required=True)
    parser.add_argument("--salida", type=Path, required=True)
    args = parser.parse_args()
    runtime = args.python_portatil.resolve(strict=True)
    libs = args.libs.resolve(strict=True)
    destination = args.salida.resolve()
    interpreter = "python.exe" if os.name == "nt" else "bin/python3"
    if not (runtime / interpreter).is_file() or not (libs / "numpy").is_dir():
        parser.error("Se requiere un CPython portable nativo y una carpeta de ruedas con NumPy.")
    if destination.exists():
        parser.error("La carpeta de salida ya existe.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    print("Preparando", platform.system(), platform.machine())
    with tempfile.TemporaryDirectory(dir=destination.parent, prefix=".cazel-usb-") as temp:
        staging = Path(temp) / "CAZEL"
        staging.mkdir()
        source = Path(temp) / "fuentes.zip"
        subprocess.run(["git", "archive", "-o", str(source), "HEAD"], cwd=ROOT, check=True)
        shutil.unpack_archive(source, staging)
        if os.name != "nt":
            for launcher in staging.glob("CAZEL_*.sh"):
                launcher.chmod(0o755)
        shutil.copytree(runtime, staging / "python_portatil", symlinks=False)
        shutil.copytree(libs, staging / "libs", symlinks=False)
        python = staging / "python_portatil" / interpreter
        imports = ("import sys; sys.path.insert(0, '.'); "
                   "import cazel.config, numpy, serial, sqlite3")
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1",
               "PYTHONNOUSERSITE": "1", "PYTHONPATH": "", "PYTHONHOME": ""}
        env.pop("CAZEL_DATOS", None)
        subprocess.run([str(python), "-B", "-c", imports], cwd=staging, env=env, check=True)
        subprocess.run([str(python), "-B", "iniciar.py", "--interfaz", "terminal"], input="/exit\n",
                       text=True, cwd=staging, env=env, check=True)
        database = staging / "datos" / "core2.sqlite3"
        database.unlink(missing_ok=True)
        staging.rename(destination)
    print(destination)


if __name__ == "__main__":
    main()
