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

    def test_propuesta_pendiente_no_escribe_archivos(self):
        import json

        from cazel.core.interface import Interface

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "proyecto"
            datos = root / "datos"
            project.mkdir()
            datos.mkdir()
            (datos / "ajustes.json").write_text('{"motor_externo":{"activo":true}}')
            peticion = {"version": 1, "accion": "proponer", "objetivo": "Escribe demo.py"}
            self.assertEqual(coordinar(peticion, project)["estado"], "no_disponible")
            respuestas = [
                (json.dumps({"tool": "write_file", "args": {"path": "demo.py", "content": "x = 1\n"}}), "offline"),
                (json.dumps({"tool": "finish", "args": {"summary": "Propuesto"}}), "offline"),
            ]
            with patch("cazel.core.models.Router.chat", side_effect=respuestas):
                informe = coordinar(peticion, project, permitir_propuestas=True, datos=datos)
            interfaz = Interface(datos, root, {})
            propuesta = interfaz.store.changes(informe["sesion"])[0]
            self.assertEqual(propuesta["state"], "pending")
            self.assertFalse((project / "demo.py").exists())

    def test_evidencia_registrada_solo_para_el_proyecto_seleccionado(self):
        from cazel.core.interface import Interface
        from cazel.config import RAIZ

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            project = root / "proyecto"
            other = root / "otro"
            project.mkdir()
            other.mkdir()
            datos = root / "datos"
            interfaz = Interface(datos, RAIZ, {})
            sesion = interfaz.agent.open(project)
            interfaz.store.event(sesion, "test", state="passed", returncode=0,
                                  profile="python-unittest", output="contenido reservado")
            peticion = {"version": 1, "accion": "evidencia", "objetivo": sesion}
            resultado = coordinar(peticion, project, datos=datos)
            self.assertEqual(resultado["evidencia"], [
                {"tipo": "prueba_registrada", "state": "passed", "returncode": 0, "profile": "python-unittest"}])
            self.assertEqual(coordinar(peticion, other, datos=datos)["estado"], "no_disponible")
