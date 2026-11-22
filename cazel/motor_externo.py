# -*- coding: utf-8 -*-
"""
Motor de lenguaje externo OPCIONAL (Ollama, LM Studio, llama.cpp...).

Cerebro es un modelo diminuto: sirve para aprender y para conversar sobre lo
que está en su corpus, pero no entiende código ni razona. Si quieres que
CAZEL entienda programación de verdad, puedes conectar un modelo grande que
corra en ESTE MISMO equipo (idea tomada de Arquitectura-Arus).

Seguridad:
  * apagado por defecto (ajustes.json -> motor_externo.activo);
  * solo acepta direcciones locales (127.0.0.1, localhost, ::1) por http:
    nada sale del equipo por aquí;
  * habla el protocolo estilo OpenAI (/chat/completions), que usan los tres
    programas anteriores.
"""

import json
import urllib.error
import urllib.parse
import urllib.request

LOCALES = {"127.0.0.1", "localhost", "::1"}
MAX_RESPUESTA = 1_000_000
SISTEMA = ("Eres CAZEL IA, un asistente que ayuda a una persona que está aprendiendo a programar "
           "y a construir robots con Arduino. Responde en español, con frases cortas y claras, "
           "explica paso a paso y no des por hecho que ya sabe términos técnicos.")


class ErrorMotor(Exception):
    pass


class SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validar_host(host):
    try:
        p = urllib.parse.urlsplit(str(host))
        _ = p.port
    except ValueError:
        raise ErrorMotor("La dirección del motor no es válida.")
    if p.scheme != "http" or (p.hostname or "").lower() not in LOCALES or p.username or p.password or p.query or p.fragment:
        raise ErrorMotor("Solo se admiten motores en este mismo equipo (http://127.0.0.1:...).")
    return str(host).rstrip("/")


def consultar(ajustes, pregunta, contexto="", abridor=None):
    """Envía la pregunta al motor local y devuelve su texto."""
    if not ajustes.get("activo"):
        raise ErrorMotor("El motor externo está apagado. Actívalo en datos/ajustes.json "
                         "(motor_externo.activo = true) si tienes Ollama o LM Studio en este equipo.")
    host = validar_host(ajustes.get("host", ""))
    modelo = str(ajustes.get("modelo", "")).strip()
    if not modelo:
        raise ErrorMotor("Falta el nombre del modelo (motor_externo.modelo en ajustes.json).")
    pregunta = str(pregunta).strip()
    if not pregunta or len(pregunta) > 20000:
        raise ErrorMotor("La pregunta debe tener entre 1 y 20 000 caracteres.")
    mensajes = [{"role": "system", "content": SISTEMA}]
    if contexto:
        mensajes.append({"role": "user", "content": "Contexto:\n" + str(contexto)[:20000]})
    mensajes.append({"role": "user", "content": pregunta})
    cuerpo = json.dumps({"model": modelo, "messages": mensajes, "stream": False,
                         "temperature": 0.3}).encode("utf-8")
    req = urllib.request.Request(host + "/chat/completions", data=cuerpo, method="POST",
                                 headers={"Content-Type": "application/json"})
    try:
        if abridor is not None:
            bruto = abridor(req)
        else:
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), SinRedireccion())
            with opener.open(req, timeout=float(ajustes.get("timeout_segundos", 120))) as r:
                bruto = r.read(MAX_RESPUESTA + 1)
        if len(bruto) > MAX_RESPUESTA:
            raise ErrorMotor("La respuesta del motor es demasiado grande.")
        datos = json.loads(bruto.decode("utf-8", errors="replace"))
        return str(datos["choices"][0]["message"]["content"]).strip()[:20000]
    except ErrorMotor:
        raise
    except urllib.error.URLError as e:
        raise ErrorMotor(f"No pude conectar con el motor local ({getattr(e, 'reason', e)}). "
                         "¿Está abierto Ollama o LM Studio?")
    except (OSError, ValueError, KeyError, IndexError, TypeError) as e:
        raise ErrorMotor(f"Respuesta inesperada del motor: {e}")
