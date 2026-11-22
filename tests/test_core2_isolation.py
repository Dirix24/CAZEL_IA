"""Prueba nativa del perfil aislado, con omisión explícita en hosts incompatibles."""

import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import unittest

from cazel.core.runner import run_tests
from cazel.core.workspace import Workspace


class BubblewrapIntegration(unittest.TestCase):
    def test_profile_blocks_host_files_and_network_and_obeys_limits(self):
        executable = Path(sys.executable).resolve()
        bwrap = shutil.which("bwrap")
        reason = None
        if sys.platform != "linux" or not bwrap or not shutil.which("prlimit") or Path("/usr") not in executable.parents:
            reason = "Se requieren Linux, bwrap, prlimit y el intérprete del sistema bajo /usr."
        else:
            probe = subprocess.run(
                [bwrap, "--unshare-all", "--ro-bind", "/", "/", "/usr/bin/true"],
                timeout=10, capture_output=True, text=True,
            )
            if probe.returncode:
                reason = probe.stderr.strip()
        if reason is not None:
            if os.getenv("CAZEL_REQUIRE_BWRAP") == "1":
                self.fail(reason)
            self.skipTest(reason)

        with tempfile.TemporaryDirectory() as tmp, socket.socket() as host:
            base = Path(tmp)
            project = base / "project"
            project.mkdir()
            sentinel = base / "host-only.txt"
            sentinel.write_text("fuera del proyecto", encoding="utf-8")
            host.bind(("127.0.0.1", 0))
            host.listen()
            port = host.getsockname()[1]
            test = project / "test_isolation.py"
            test.write_text(
                'import socket, unittest\n'
                'class Isolation(unittest.TestCase):\n'
                '    def test_host_unreachable(self):\n'
                '        with self.assertRaises(FileNotFoundError):\n'
                f'            open({str(sentinel)!r}).close()\n'
                '        with self.assertRaises(OSError):\n'
                f'            socket.create_connection(("127.0.0.1", {port}), timeout=1).close()\n',
                encoding="utf-8",
            )
            ws = Workspace(project, base / "data")
            cancel = threading.Event()
            outcome = run_tests(ws, "python-unittest", "isolated", cancel)
            self.assertEqual(outcome["state"], "passed", outcome)
            self.assertIn("Ran 1 test", outcome["output"])
            test.write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
            self.assertEqual(run_tests(ws, "python-unittest", "isolated", cancel, timeout=0.5)["state"],
                             "timeout")
            timer = threading.Timer(0.5, cancel.set)
            timer.start()
            try:
                self.assertEqual(run_tests(ws, "python-unittest", "isolated", cancel)["state"], "cancelled")
            finally:
                timer.cancel()
                timer.join()
