"""Ejecuta únicamente perfiles predefinidos y con autorización explícita."""

import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

PROFILES = {"python-unittest": ("-B", "-m", "unittest", "discover", "-v")}
MAX_OUTPUT = 48_000


def run_tests(root, profile, permission, cancel, timeout=30):
    args = PROFILES.get(profile)
    if args is None:
        raise ValueError("Perfil de pruebas desconocido.")
    if permission not in ("isolated", "trusted"):
        raise ValueError("La ejecución requiere permiso.")
    with tempfile.TemporaryDirectory(prefix="cazel-test-") as tmp:
        env = {"PATH": os.defpath, "HOME": tmp, "TMPDIR": tmp, "TEMP": tmp,
               "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""), "PYTHONIOENCODING": "utf-8"}
        command = [sys.executable, *args]
        if permission == "isolated":
            bwrap = shutil.which("bwrap")
            prlimit = shutil.which("prlimit")
            if sys.platform != "linux" or not bwrap or not prlimit:
                raise ValueError("El aislamiento requiere Bubblewrap y prlimit en Linux.")
            exe = Path(sys.executable).resolve()
            if Path("/usr") not in exe.parents:
                raise ValueError("El perfil aislado requiere un intérprete en /usr.")
            command = [bwrap, "--unshare-all", "--die-with-parent", "--new-session",
                       "--cap-drop", "ALL", "--ro-bind", "/usr", "/usr"]
            for lib in ("/lib", "/lib64"):
                if Path(lib).exists():
                    command += ["--ro-bind", lib, lib]
            command += ["--proc", "/proc", "--dev", "/dev", "--tmpfs", "/tmp",
                        "--ro-bind", str(root), "/project", "--chdir", "/project",
                        "--setenv", "HOME", "/tmp", "--setenv", "TMPDIR", "/tmp",
                        "--", prlimit, "--cpu=20", "--as=536870912", "--fsize=1048576",
                        "--nofile=128", "--", str(exe), *args]
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
        return {"profile": profile, "returncode": code, "isolation": permission,
                "state": reason or ("passed" if code == 0 and len(bruto) <= MAX_OUTPUT else "failed"),
                "output": bruto[:MAX_OUTPUT].decode("utf-8", errors="replace"),
                "truncated": len(bruto) > MAX_OUTPUT}
