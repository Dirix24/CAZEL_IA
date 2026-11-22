from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from cazel.especialista import coordinar


class Especialista(unittest.TestCase):
    def test_analisis_real_y_permiso_de_pruebas(self):
        with tempfile.TemporaryDirectory() as temp:
            project = Path(temp)
            (project / "robot.py").write_text("def roto(:\n", encoding="utf-8")
            (project / ".env").write_text("no leer", encoding="utf-8")
            request = {"version": 1, "accion": "analizar", "objetivo": "robot"}
            self.assertEqual(coordinar(request)["estado"], "no_disponible")
            report = coordinar(request, project)
            self.assertEqual([item["path"] for item in report["evidencia"]], ["robot.py"])
            self.assertEqual(report["evidencia"][0]["errores"][0]["line"], 1)
            with patch("cazel.especialista.run_tests") as runner:
                request["accion"] = "probar"
                self.assertEqual(coordinar(request, project)["estado"], "no_disponible")
                runner.assert_not_called()
