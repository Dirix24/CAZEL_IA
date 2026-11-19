"""Pruebas del enrutamiento híbrido sin cargar el modelo ni usar red."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from cazel.nucleo import Cazel
from cazel.motor_externo import ErrorMotor


class EnrutamientoHibridoTests(unittest.TestCase):
    def setUp(self):
        self.cazel = Cazel.__new__(Cazel)
        self.cazel.conversacion = SimpleNamespace(procesar=Mock(return_value=("offline", False)))
        self.cazel.auditoria = SimpleNamespace(registrar=Mock())

    def test_sin_motor_usa_modelo_integrado(self):
        self.cazel.ajustes = {"motor_externo": {"activo": False}}
        self.assertEqual(self.cazel._enrutar("hola"), ("offline", False))

    @patch("cazel.nucleo.motor_externo.consultar", return_value="respuesta local")
    def test_motor_activo_responde(self, consultar):
        self.cazel.ajustes = {"motor_externo": {"activo": True}}
        self.assertEqual(self.cazel._enrutar("hola"), ("respuesta local", False))
        consultar.assert_called_once()
        self.cazel.conversacion.procesar.assert_not_called()

    @patch("cazel.nucleo.motor_externo.consultar", side_effect=ErrorMotor("no disponible"))
    def test_error_motor_recurre_al_modelo_integrado(self, consultar):
        self.cazel.ajustes = {"motor_externo": {"activo": True}}
        self.assertEqual(self.cazel._enrutar("hola"), ("offline", False))
        self.cazel.auditoria.registrar.assert_called_once()

    @patch("cazel.nucleo.motor_externo.consultar", return_value="")
    def test_respuesta_vacia_recurre_al_modelo_integrado(self, consultar):
        self.cazel.ajustes = {"motor_externo": {"activo": True}}
        self.assertEqual(self.cazel._enrutar("hola"), ("offline", False))

    @patch("cazel.nucleo.motor_externo.consultar")
    def test_auto_chat_desactivado(self, consultar):
        self.cazel.ajustes = {"motor_externo": {"activo": True, "auto_chat": False}}
        self.assertEqual(self.cazel._enrutar("hola"), ("offline", False))
        consultar.assert_not_called()


if __name__ == "__main__":
    unittest.main()
