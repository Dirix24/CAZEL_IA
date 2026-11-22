"""Router para servidores de chat compatibles con OpenAI."""

import json
import os
from urllib import error, parse, request

from cazel.motor_externo import ErrorMotor, MAX_RESPUESTA, SinRedireccion, validar_host


class Router:
    def __init__(self, configuracion, ruta):
        self.local = configuracion
        self.ruta = ruta

    def remote(self):
        try:
            data = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ErrorMotor("Configura el proveedor en datos/core2-modelos.json.") from exc
        if not isinstance(data, dict):
            raise ErrorMotor("La configuración remota debe ser un objeto JSON.")
        return data

    def chat(self, mode, authorized, messages, timeout):
        if mode == "online" and not authorized:
            raise ErrorMotor("Se requiere autorización para enviar contexto al proveedor remoto.")
        if mode in ("online", "auto") and authorized:
            try:
                return self.send(self.remote(), messages, timeout, remote=True), "online"
            except ErrorMotor:
                if mode == "online":
                    raise
        if not self.local.get("activo"):
            raise ErrorMotor("Activa motor_externo en ajustes.json y prepara un modelo local.")
        return self.send(self.local, messages, timeout), "offline"

    @staticmethod
    def send(config, messages, timeout, remote=False):
        host = config.get("host", "")
        model = config.get("modelo", "")
        if not isinstance(host, str) or not isinstance(model, str) or not model.strip():
            raise ErrorMotor("Configura la dirección y el nombre del modelo.")
        headers = {"Content-Type": "application/json"}
        try:
            url = parse.urlsplit(host)
            if url.query or url.fragment or url.username or url.password:
                raise ErrorMotor("Dirección de modelo inválida.")
            if remote:
                if url.scheme != "https" or not url.hostname:
                    raise ErrorMotor("El proveedor remoto requiere HTTPS.")
                key_name = config.get("clave_env")
                key = os.environ.get(key_name) if isinstance(key_name, str) else None
                if not key:
                    raise ErrorMotor("La clave remota debe estar en la variable configurada.")
                headers["Authorization"] = "Bearer " + key
            else:
                validar_host(host)
            opener = request.build_opener(request.ProxyHandler({}), SinRedireccion())
            body = json.dumps({"model": model, "messages": messages, "temperature": 0.1,
                               "stream": False, "max_tokens": 4096}).encode()
            req = request.Request(host.rstrip("/") + "/chat/completions", body, headers)
            configured_timeout = config.get("timeout_segundos", 30 if remote else 120)
            if type(configured_timeout) not in (int, float) or not 1 <= configured_timeout <= 120:
                raise ErrorMotor("El tiempo del modelo debe estar entre 1 y 120 segundos.")
            with opener.open(req, timeout=max(0.1, min(timeout, configured_timeout))) as reply:
                raw = reply.read(MAX_RESPUESTA + 1)
            if len(raw) > MAX_RESPUESTA:
                raise ErrorMotor("Respuesta del modelo demasiado grande.")
            content = json.loads(raw)["choices"][0]["message"]["content"]
            if not isinstance(content, str) or len(content) > 100_000:
                raise ErrorMotor("Respuesta del modelo inválida.")
            return content
        except (error.URLError, OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            raise ErrorMotor("El modelo no respondió con un mensaje de chat válido.") from exc
