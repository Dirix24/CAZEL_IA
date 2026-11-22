"""Regresión de Core 2. El modelo de guion es un doble de integración."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from cazel.core.agent import Task, decode_tool, validate
from cazel.core.analysis import inspect_file
from cazel.core.interface import Interface
from cazel.core.models import Router
from cazel.core.runner import run_tests
from cazel.core.workspace import Workspace
from cazel.motor_externo import ErrorMotor


CALCULATOR = "def sumar(a, b):\n    return a - b\n"
TEST = """import unittest
from calculadora import sumar

class CalculadoraTests(unittest.TestCase):
    def test_sumar(self):
        self.assertEqual(sumar(2, 3), 5)
"""


class Core2(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.project = self.root / "project"
        self.project.mkdir()
        self.data = self.root / "data"
        self.ui = Interface(self.data, self.root, {})
        self.addCleanup(self.ui.close)
        self.session = self.ui.action("open", {"path": "./project"})["session"]
        self.ws = self.ui.agent.workspace(self.session)

    def call(self, name, **args):
        return self.ui.action(name, {"session": self.session, **args})

    def test_read_excludes_escapes_and_secrets(self):
        (self.project / "main.py").write_text("x = 1\n", encoding="utf-8")
        outside = self.root / "outside.py"
        outside.write_text("no leer", encoding="utf-8")
        for name in ("../outside.py", str(outside), ".env", "config/token.txt", "x:ads", "CON"):
            with self.assertRaises(ValueError, msg=name):
                self.ws.read(name)
        self.assertEqual(self.call("read", path="main.py")["content"], "x = 1\n")
        self.assertEqual(self.call("files"), ["main.py"])
        try:
            (self.project / "alias.py").symlink_to(outside)
        except OSError:
            self.skipTest("Los enlaces simbólicos requieren permisos en esta plataforma.")
        with self.assertRaises(ValueError):
            self.ws.read("alias.py")
        self.assertEqual(self.call("files"), ["main.py"])

    def test_changes_are_staged_and_shared_and_conflict_safe(self):
        c = self.call("stage", path="src/main.py", content="a = 1")
        self.assertIn("+a = 1", c["diff"])
        self.assertFalse((self.project / "src").exists())
        other = Interface(self.data, self.root, {})
        self.assertEqual(other.action("sessions", {})[0]["project"], "./project")
        with self.assertRaises(ValueError):
            other.action("accept", {"session": other.agent.open(self.project), "id": c["id"]})
        other.action("accept", {"session": self.session, "id": c["id"]})
        self.assertEqual(self.ws.read("src/main.py"), "a = 1")
        conflict = self.call("stage", path="src/main.py", content="a = 2")
        self.call("undo", id=c["id"])
        self.assertIsNone(self.ws.read("src/main.py", missing=True))
        with self.assertRaisesRegex(ValueError, "archivo cambió"):
            self.call("accept", id=conflict["id"])
        self.call("reject", id=conflict["id"])

    def test_patch_and_undo_keep_bytes(self):
        path = self.project / "hello.py"
        path.write_bytes(b"line\r\nlast")
        patch_text = "--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n line\r\n-last\n\\ No newline at end of file\n+new\n"
        c = self.ui.agent.stage(self.session, self.ws, "hello.py", patch=patch_text)
        self.call("accept", id=c["id"])
        self.assertEqual(path.read_bytes(), b"line\r\nnew\n")
        self.call("undo", id=c["id"])
        self.assertEqual(path.read_bytes(), b"line\r\nlast")
        with self.assertRaises(ValueError):
            self.ui.agent.stage(self.session, self.ws, "hello.py", patch=patch_text.replace("-last", "-other"))

    def test_patch_preserves_crlf_and_rejects_mismatched_headers(self):
        path = self.project / "original.txt"
        path.write_bytes("línea\r\nantes\r\n".encode())
        patch_text = "--- a/original.txt\n+++ b/original.txt\n@@ -1,2 +1,2 @@\n línea\n-antes\n+después\n"
        with self.assertRaisesRegex(ValueError, "cabeceras"):
            self.call("patch", path="original.txt", patch=patch_text.replace("b/original.txt", "b/otro.txt"))
        change = self.call("patch", path="original.txt", patch=patch_text)
        self.call("accept", id=change["id"])
        self.assertEqual(path.read_bytes(), "línea\r\ndespués\r\n".encode())
        self.call("undo", id=change["id"])
        self.assertEqual(path.read_bytes(), "línea\r\nantes\r\n".encode())

    def test_project_lessons_are_shared_and_stay_local(self):
        note = "Para los enteros usa nombres descriptivos."
        created = self.call("learn", language="Rust", note=note)
        self.assertEqual(self.call("learn", language="Rust", note=note), created)
        reopened = Interface(self.data, self.root, {})
        second = reopened.agent.open(self.project)
        self.assertEqual(reopened.action("lessons", {"session": second})[0]["note"], note)
        elsewhere = self.root / "otro"
        elsewhere.mkdir()
        third = reopened.agent.open(elsewhere)
        self.assertEqual(reopened.action("lessons", {"session": third}), [])
        with self.assertRaises(ValueError):
            reopened.action("forget", {"session": third, **created})
        model_output = ('{"tool":"finish","args":{"summary":"ok"}}', "offline")
        for mode, remote in [("offline", False), ("auto", True), ("online", True)]:
            self.call("mode", mode=mode)
            task = Task(threading.Event(), time.monotonic() + 3, remote=remote)
            with patch.object(self.ui.agent.router, "chat", return_value=model_output) as chat:
                self.ui.agent.run(self.session, "Escribe Rust", task, None)
                self.assertEqual(note in chat.call_args.args[2][1]["content"], mode == "offline")
        self.call("forget", **created)
        self.assertEqual(reopened.action("lessons", {"session": second}), [])

    def test_schema_and_inspection(self):
        for payload in ({}, {"tool": "shell", "args": {}}, {"tool": "run_tests", "args": {"command": "ls"}},
                        {"tool": "read_file", "args": {"path": "x", "start": True, "end": 1}}):
            with self.assertRaises(ValueError):
                validate(payload)
        result = inspect_file("a.py", "import sys\nclass A:\n    pass\n")
        self.assertEqual(result["imports"], ["sys"])
        self.assertEqual(result["symbols"][0]["name"], "A")
        self.assertEqual(inspect_file("a.py", "def x!")["confirmed"][0]["line"], 1)
        self.assertEqual(inspect_file("a.html", "<main></main>")["language"], "HTML")

    def test_model_tool_decoding_accepts_only_one_json_object(self):
        raw = '{"tool":"git_status","args":{}}'
        self.assertEqual(decode_tool(raw), ("git_status", {}))
        self.assertEqual(decode_tool("```json\n" + raw + "\n```"), ("git_status", {}))
        for invalid in (raw + raw, "Explicación ```json\n" + raw + "\n```"):
            with self.assertRaises(ValueError):
                decode_tool(invalid)

    def test_tests_require_permission_and_bound_time(self):
        with self.assertRaises(ValueError):
            run_tests(self.ws, "python-unittest", "", threading.Event())
        empty = run_tests(self.ws, "python-unittest", "trusted", threading.Event())
        self.assertEqual(empty["state"], "no_tests")
        (self.project / "test_wait.py").write_text("import time\ntime.sleep(20)\n", encoding="utf-8")
        timed = run_tests(self.ws, "python-unittest", "trusted", threading.Event(), timeout=0.2)
        self.assertEqual(timed["state"], "timeout")
        stop = threading.Event()
        timer = threading.Timer(0.15, stop.set)
        timer.start()
        self.addCleanup(timer.join)
        self.assertEqual(run_tests(self.ws, "python-unittest", "trusted", stop)["state"], "cancelled")

    def test_router_modes(self):
        router = Router({"activo": True}, self.data / "remote.json")
        router.ruta.write_text("{}", encoding="utf-8")
        with patch.object(router, "send", side_effect=[ErrorMotor("error"), "local"]) as send:
            self.assertEqual(router.chat("auto", True, [], 1), ("local", "offline"))
            self.assertEqual(send.call_count, 2)
        with patch.object(router, "send", return_value="local") as send:
            self.assertEqual(router.chat("offline", True, [], 1), ("local", "offline"))
            self.assertEqual(router.chat("auto", False, [], 1), ("local", "offline"))
            with self.assertRaises(ErrorMotor):
                router.chat("online", False, [], 1)
            self.assertEqual(send.call_count, 2)

    def test_calculator_tool_loop_with_scripted_model(self):
        commands = [
            ("plan", {"steps": ["Crear calculadora", "Probar", "Corregir"]}),
            ("write_file", {"path": "calculadora.py", "content": CALCULATOR}),
            ("write_file", {"path": "test_calculadora.py", "content": TEST}),
            ("run_tests", {"profile": "python-unittest"}),
            ("apply_patch", {"path": "calculadora.py", "patch":
                             "--- a/calculadora.py\n+++ b/calculadora.py\n@@ -1,2 +1,2 @@\n"
                             " def sumar(a, b):\n-    return a - b\n+    return a + b\n"}),
            ("run_tests", {"profile": "python-unittest"}),
            ("finish", {"summary": "Corrección aplicada y comprobada."}),
        ]

        def approve(change, _):
            self.assertTrue(change["diff"])
            return self.call("accept", id=change["id"])

        task = Task(threading.Event(), time.monotonic() + 20, "trusted")
        replies = [(json.dumps({"tool": name, "args": args}), "offline") for name, args in commands]
        with patch.object(self.ui.agent.router, "chat", side_effect=replies):
            outcome = self.ui.agent.run(
                self.session,
                "Crea una calculadora en Python con pruebas automáticas. Ejecuta las pruebas, "
                "detecta un error introducido deliberadamente, corrígelo y vuelve a comprobar el programa.",
                task, approve)
        self.assertEqual(outcome["state"], "verified")
        self.assertIn("return a + b", self.ws.read("calculadora.py"))
        self.assertEqual(self.ws.read("test_calculadora.py"), TEST)
        history = self.call("status")["events"]
        tests = [item for item in history if item["kind"] == "test"]
        self.assertEqual([item["returncode"] for item in tests], [1, 0])
        self.assertIn("AssertionError: -1 != 5", tests[0]["output"])
        self.assertIn("Ran 1 test", tests[1]["output"])
        self.call("undo", id=self.call("changes")[0]["id"])
        self.assertEqual(self.ws.read("calculadora.py"), CALCULATOR)

    def test_no_tests_overrides_unverified_model_claim(self):
        replies = [
            ('{"tool":"run_tests","args":{"profile":"python-unittest"}}', "offline"),
            ('{"tool":"finish","args":{"summary":"Han pasado todas las pruebas."}}', "offline"),
        ]
        task = Task(threading.Event(), time.monotonic() + 5, "trusted")
        with patch.object(self.ui.agent.router, "chat", side_effect=replies):
            outcome = self.ui.agent.run(self.session, "Comprueba las pruebas", task, None)
        self.assertEqual(outcome["state"], "failed")
        self.assertEqual(outcome["summary"], "No se descubrieron pruebas.")
        self.assertIn("Han pasado", self.ui.store.history(self.session)[-1]["model_summary"])

    def test_cancellation_before_model(self):
        cancel = threading.Event()
        cancel.set()
        with patch.object(self.ui.agent.router, "chat") as model:
            outcome = self.ui.agent.run(self.session, "resume", Task(cancel, time.monotonic() + 1), None)
            model.assert_not_called()
        self.assertEqual(outcome["state"], "cancelled")

    def test_terminal_uses_shared_session(self):
        starts = Path(__file__).resolve().parents[1] / "iniciar.py"
        terminal = subprocess.run([sys.executable, str(starts), "--interfaz", "terminal", "--datos", str(self.data)],
                                  input=f"/session {self.session}\n/status\n/help\n/exit\n",
                                  encoding="utf-8", capture_output=True, timeout=10, check=True)
        self.assertIn("CAZEL Terminal", terminal.stdout)
        self.assertIn("./project", terminal.stdout)
        self.assertIn("/undo", terminal.stdout)
