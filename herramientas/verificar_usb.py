"""Comprueba las dos interfaces de un paquete y su persistencia en el SO actual."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener


def smoke(package):
    windows = os.name == "nt"
    py = package / "python_portatil" / ("python.exe" if windows else "bin/python3")
    entry = package / "iniciar.py"
    env = os.environ.copy()
    for name in ("PYTHONPATH", "PYTHONHOME", "CAZEL_DATOS"):
        env.pop(name, None)
    env["PATH"] = str(Path(env["SYSTEMROOT"]) / "System32") if windows else "/bin:/usr/bin"
    env["PYTHONIOENCODING"] = "utf-8"
    client = build_opener(ProxyHandler({}))
    with tempfile.TemporaryDirectory(prefix="cazel-usb-") as tmp:
        root = Path(tmp)
        project = root / "project"
        project.mkdir()
        options = [str(py), "-u", str(entry), "--datos", str(root / "data")]
        logfile = root / "studio.log"
        with logfile.open("w", encoding="utf-8") as log:
            studio = subprocess.Popen([*options, "--interfaz", "studio", "--sin-navegador"],
                                      cwd=package, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            page = None
            for _ in range(80):
                output = logfile.read_text(encoding="utf-8", errors="replace")
                if studio.poll() is not None:
                    raise RuntimeError(output)
                found = re.search(r"http://127\.0\.0\.1:\d+/studio", output)
                if found:
                    url = found[0]
                    try:
                        with client.open(url, timeout=2) as reply:
                            page = reply.read().decode("utf-8")
                        break
                    except URLError:
                        pass
                time.sleep(0.25)
            if page is None or "CAZEL Studio" not in page:
                raise RuntimeError("Studio no respondió con su interfaz.")
            token = re.search(r'name="cazel-token" content="([^"]+)"', page)[1]

            def api(action, data):
                request = Request(url.removesuffix("/studio") + "/api/" + action,
                                  json.dumps(data).encode("utf-8"),
                                  {"Content-Type": "application/json", "X-Cazel-Token": token})
                with client.open(request, timeout=5) as reply:
                    return json.load(reply)

            session = api("core2/open", {"path": str(project)})["session"]
            data = {"session": session}
            change = api("core2/stage", {**data, "path": "demo.py", "content": "valor = 42\n"})
            if "+valor = 42" not in change["diff"] or (project / "demo.py").exists():
                raise RuntimeError("La propuesta debe previsualizarse antes de escribirse.")
            api("core2/accept", {**data, "id": change["id"]})
            api("core2/learn", {**data, "language": "Python", "note": "Usa enteros para los contadores."})
            api("apagar", {})
            if studio.wait(timeout=10):
                raise RuntimeError("Studio no se cerró correctamente.")
        finally:
            if studio.poll() is None:
                studio.terminate()
                studio.wait(timeout=10)
        terminal = subprocess.run([*options, "--interfaz", "terminal"], cwd=package, env=env,
                                  input=f"/session {session}\n/diff\n/lessons\n/exit\n",
                                  encoding="utf-8", stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  timeout=20, check=True)
        for evidence in ("CAZEL Terminal", "+valor = 42", "Usa enteros para los contadores."):
            if evidence not in terminal.stdout:
                raise RuntimeError(terminal.stdout)
        if (project / "demo.py").read_text(encoding="utf-8") != "valor = 42\n":
            raise RuntimeError("El cambio no se conservó después del reinicio.")
        print("Studio y Terminal compartieron sesión, parche y lección después del reinicio.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    smoke(parser.parse_args().package.resolve(strict=True))
