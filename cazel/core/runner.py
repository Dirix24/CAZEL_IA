"""Ejecuta únicamente perfiles predefinidos y con autorización explícita."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PROFILES = {"python-unittest": ("-I", "-B", "-m", "unittest", "discover", "-s", ".", "-t", ".", "-v")}
MAX_OUTPUT = 48_000


def run_tests(workspace, profile, permission, cancel, timeout=30):
    root = workspace.root
    args = PROFILES.get(profile)
    if args is None:
        raise ValueError("Perfil de pruebas desconocido.")
    if permission not in ("isolated", "trusted"):
        raise ValueError("La ejecución requiere permiso.")
    with tempfile.TemporaryDirectory(prefix="cazel-test-") as tmp:
        env = {"PATH": os.defpath, "HOME": tmp, "TMPDIR": tmp, "TEMP": tmp,
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONIOENCODING": "utf-8"}
        prlimit = shutil.which("prlimit") if sys.platform == "linux" else None
        limits = [prlimit, "--cpu=20", "--as=536870912", "--fsize=1048576",
                  "--nofile=128", "--"] if prlimit else []
        command = [*limits, sys.executable, *args]
        if permission == "isolated":
            bwrap = shutil.which("bwrap")
            if sys.platform != "linux" or not bwrap or not prlimit:
                raise ValueError("El aislamiento requiere Bubblewrap y prlimit en Linux.")
            exe = Path(sys.executable).resolve()
            if Path("/usr") not in exe.parents:
                raise ValueError("El perfil aislado requiere un intérprete en /usr.")
            snapshot = Path(tmp) / "project"
            snapshot.mkdir()
            paths = workspace.files(limite=1501)
            if len(paths) > 1500:
                raise ValueError("El proyecto supera el máximo de archivos para pruebas aisladas.")
            total_bytes = 0
            for path in paths:
                if cancel.is_set():
                    raise ValueError("Tarea cancelada.")
                try:
                    content = workspace.read(path).encode("utf-8")
                except UnicodeError:
                    continue
                total_bytes += len(content)
                if total_bytes > 16 * 1024 * 1024:
                    raise ValueError("El proyecto supera el tamaño para pruebas aisladas.")
                dest = snapshot / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(content)
            command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                       "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr"]
            for lib in ("/lib", "/lib64"):
                if Path(lib).exists():
                    command += ["--ro-bind", lib, lib]
            command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                        "--ro-bind", str(snapshot), "/project", "--chdir", "/project",
                        "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
                        "--", *limits, str(exe), *args]
        with tempfile.TemporaryFile() as output:
            with subprocess.Popen(command, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                  stdout=output, stderr=subprocess.STDOUT,
                                  start_new_session=(os.name == "posix")) as process:
                plazo = time.monotonic() + timeout
                reason = None
                try:
                    while process.poll() is None:
                        if cancel.is_set():
                            reason = "cancelled"
                        elif time.monotonic() >= plazo:
                            reason = "timeout"
                        elif os.fstat(output.fileno()).st_size > MAX_OUTPUT:
                            reason = "output_limit"
                        if reason:
                            break
                        time.sleep(0.05)
                finally:
                    if os.name == "posix":
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                    elif process.poll() is None:
                        process.kill()
                code = process.wait()
            output.seek(0)
            bruto = output.read(MAX_OUTPUT + 1)
        decoded = bruto[:MAX_OUTPUT].decode("utf-8", errors="replace")
        if not reason and code in {0, 5} and "Ran 0 tests" in decoded:
            reason = "no_tests"
        return {"profile": profile, "returncode": code, "isolation": permission,
                "state": reason or ("passed" if code == 0 and len(bruto) <= MAX_OUTPUT else "failed"),
                "output": decoded,
                "truncated": len(bruto) > MAX_OUTPUT}
