"""Pruebas de seguridad del motor híbrido, sin depender de Ollama ni internet."""
import unittest
import urllib.error
from unittest.mock import patch

from cazel.motor_externo import ErrorMotor, _SinRedirecciones, validar_host


class SeguridadMotorExternoTests(unittest.TestCase):
    def test_solo_hosts_locales(self):
        self.assertEqual(validar_host("http://127.0.0.1:11434/v1"), "http://127.0.0.1:11434/v1")
        for host in (
            "https://127.0.0.1:11434/v1",
            "http://example.com/v1",
            "http://127.0.0.1:11434/v1?token=abc",
            "http://localhost:11434/v1#fragmento",
            "http://usuario:clave@localhost:11434/v1",
        ):
            with self.subTest(host=host), self.assertRaises(ErrorMotor):
                validar_host(host)

    def test_redireccion_no_permitida(self):
        handler = _SinRedirecciones()
        with self.assertRaisesRegex(ErrorMotor, "redirigir"):
            handler.redirect_request(None, None, 302, "Found", {}, "https://example.com")


if __name__ == "__main__":
    unittest.main()
