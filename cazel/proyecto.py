# -*- coding: utf-8 -*-
"""Análisis local, orientativo y multilenguaje de proyectos de robótica.

No ejecuta ni modifica el código. Solo extrae símbolos y dependencias conocidas
para ayudar a revisar un repositorio, incluidos repositorios públicos de GitHub.
"""
import os
import re

MAX_ARCHIVOS = 24
MAX_TOTAL = 150_000
EXTENSIONES = {".ino", ".cpp", ".c", ".h", ".hpp", ".py", ".js", ".ts",
               ".java", ".rs", ".ino", ".pde", ".yaml", ".yml", ".json", ".toml",
               ".md", ".xml", ".txt"}

_PATTERNS = [
    ("ESP32", r"\bESP32\b|ESP32Servo|ARDUINO_ARCH_ESP32"),
    ("ESP8266", r"\bESP8266\b|ESP8266WiFi"),
    ("Arduino AVR", r"ARDUINO_AVR_|ATmega(?:328|2560)"),
    ("RP2040 / Raspberry Pi Pico", r"RP2040|pico/stdlib|pico-sdk"),
    ("STM32", r"\bSTM32\b|ARDUINO_ARCH_STM32"),
    ("micro:bit", r"micro:bit|microbit"),
    ("Raspberry Pi / Linux", r"gpiozero|RPi\.GPIO|rclpy|rospy"),
    ("ROS / ROS 2", r"\brospy\b|\brclpy\b|ros2|rosserial"),
]
_COMPONENTS = [
    ("Servomotores", r"Servo\s*\(|Servo\.h|ESP32Servo"),
    ("Motores paso a paso", r"AccelStepper|Stepper\.h|stepper"),
    ("Controladores de motor", r"L298N?|TB6612|DRV8833|Adafruit_MotorShield|AFMotor"),
    ("Sensor ultrasónico", r"HC[-_ ]?SR04|NewPing|pulseIn\s*\("),
    ("Temperatura/humedad", r"DHT\d*|BME280|SHT3\d"),
    ("IMU/acelerómetro", r"MPU6050|MPU9250|LSM6|Adafruit_MPU"),
    ("GPS", r"TinyGPS|GPS\.h|NEO-6M"),
    ("LED direccionable", r"NeoPixel|FastLED|WS2812|SK6812"),
    ("Cámara", r"esp_camera|ArduCAM|Camera\.h"),
    ("LiDAR", r"LiDAR|VL53L\d|RPLidar"),
    ("Bluetooth", r"BluetoothSerial|BLEDevice|SoftwareSerial|NimBLE"),
    ("Wi-Fi", r"WiFi\.h|ESP8266WiFi|WiFiClient"),
    ("Bus I2C", r"Wire\.h|I2C"),
    ("Bus SPI", r"SPI\.h|SPIClass"),
    ("Bus CAN", r"CAN\.h|TWAI|MCP2515"),
]


def _extraer_archivos(archivos):
    aceptados, total = [], 0
    if not isinstance(archivos, list):
        raise ValueError("La lista de archivos no es válida.")
    for f in archivos:
        if not isinstance(f, dict):
            continue
        ruta, texto = str(f.get("ruta", "")), f.get("texto", "")
        if not isinstance(texto, str) or os.path.splitext(ruta)[1].lower() not in EXTENSIONES:
            continue
        # No se necesitan rutas locales; bloquea rutas absolutas y traversal.
        ruta = ruta.replace("\\", "/").lstrip("/")
        if any(p == ".." for p in ruta.split("/")):
            continue
        texto = texto[:40_000]
        if total + len(texto) > MAX_TOTAL:
            texto = texto[:MAX_TOTAL-total]
        if texto:
            aceptados.append({"ruta": ruta[:200], "texto": texto})
            total += len(texto)
        if len(aceptados) >= MAX_ARCHIVOS or total >= MAX_TOTAL:
            break
    return aceptados


def _mejoras(ruta, texto):
    """Reglas locales explicables: solo señalan patrones concretos con línea."""
    mejoras = []
    lineas = texto.splitlines()
    for n, linea in enumerate(lineas, 1):
        if re.search(r"\bdelay\s*\(\s*(?:[1-9][0-9]{3,})", linea):
            mejoras.append({"ruta": ruta, "linea": n, "nivel": "media",
                "mensaje": "Espera larga con delay() bloquea lecturas de sensores y órdenes mientras dura.",
                "propuesta": "Usa millis() y una marca de tiempo para actualizar por intervalos sin bloquear el loop."})
        if re.search(r"\b(?:eval|exec)\s*\(", linea):
            mejoras.append({"ruta": ruta, "linea": n, "nivel": "alta",
                "mensaje": "Se ejecuta texto dinámicamente; una entrada no confiable puede convertirse en código.",
                "propuesta": "Reemplaza la ejecución de texto por comandos permitidos y parámetros validados."})
        if re.search(r"\bsystem\s*\(", linea):
            mejoras.append({"ruta": ruta, "linea": n, "nivel": "alta",
                "mensaje": "Se llama a un comando del sistema; verifica y restringe completamente la entrada.",
                "propuesta": "Usa una lista fija de ejecutables/argumentos o elimina la llamada si no es necesaria."})
        if re.search(r"""(?:password|passwd|api[_-]?key|secret|token)\s*[:=]\s*['"][^'"]{4,}['"]""", linea, re.I):
            mejoras.append({"ruta": ruta, "linea": n, "nivel": "alta",
                "mensaje": "Parece haber una credencial escrita directamente en el código.",
                "propuesta": "Elimina el secreto del repositorio y cárgalo desde una configuración local fuera del control de versiones."})
        if re.search(r"readStringUntil\s*\(|read_until\s*\(", linea):
            mejoras.append({"ruta": ruta, "linea": n, "nivel": "media",
                "mensaje": "La lectura serie puede esperar hasta agotar el timeout y retrasar otras tareas del robot.",
                "propuesta": "Usa un búfer por caracteres con límite de longitud y tiempo máximo explícito."})
    if re.search(r"\bwhile\s*\(\s*(?:true|1)\s*\)", texto, re.I) and not re.search(r"\b(?:yield|sleep|delay)\s*\(", texto, re.I):
        mejoras.append({"ruta": ruta, "linea": next((i for i,x in enumerate(lineas,1) if re.search(r"\bwhile\s*\(\s*(?:true|1)\s*\)",x,re.I)), 1),
            "nivel": "media", "mensaje": "Bucle aparentemente infinito sin pausa detectable; puede monopolizar CPU o watchdog.",
            "propuesta": "Añade yield()/sleep() en Python/ESP o divide el trabajo en ciclos no bloqueantes."})
    if re.search(r"(?:analogWrite|digitalWrite)\s*\(", texto) and not re.search(r"(?:watchdog|WATCHDOG|millis\s*\(.*(?:stop|parar|timeout))", texto, re.I):
        mejoras.append({"ruta": ruta, "linea": 1, "nivel": "media",
            "mensaje": "Hay salidas de control, pero no encontré un watchdog/parada por timeout con estas reglas.",
            "propuesta": "Añade una parada segura si se pierde la comunicación y prueba el paro antes de mover motores."})
    return mejoras[:30]


def analizar(archivos):
    """Devuelve un resumen reproducible sin ejecutar el contenido descargado."""
    archivos = _extraer_archivos(archivos)
    if not archivos:
        raise ValueError("No encontré archivos de código compatibles en el proyecto.")
    texto_total = "\n".join(f["texto"] for f in archivos)
    placas = [nombre for nombre, patron in _PATTERNS if re.search(patron, texto_total, re.I)]
    componentes = [nombre for nombre, patron in _COMPONENTS if re.search(patron, texto_total, re.I)]
    lista = []
    mejoras = []
    for f in archivos:
        txt = f["texto"]
        ext = os.path.splitext(f["ruta"])[1].lower()
        lineas = txt.count("\n") + (1 if txt else 0)
        if ext == ".py":
            patron = r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)\s*\("
        elif ext in {".js", ".ts"}:
            patron = r"(?:function\s+|(?:const|let|var)\s+)([A-Za-z_$][\w$]*)\s*(?:=\s*(?:async\s*)?)?\("
        else:
            patron = r"(?:\b(?:void|int|bool|float|double|long|String|char|auto)\s+)([A-Za-z_]\w*)\s*\([^;{}]*\)\s*\{"
        funciones = list(dict.fromkeys(re.findall(patron, txt, re.M)))[:30]
        avisos = []
        if re.search(r"\bdelay\s*\(\s*\d{4,}", txt):
            avisos.append("Hay esperas largas con delay(); pueden bloquear la lectura de sensores y órdenes.")
        if re.search(r"\b(?:eval|exec)\s*\(", txt):
            avisos.append("Hay ejecución dinámica de texto; revisa cuidadosamente el origen de esos datos.")
        if re.search(r"\bsystem\s*\(", txt):
            avisos.append("Hay una llamada a system(); valida cualquier texto que llegue a esa llamada.")
        if re.search(r"\bwhile\s*\(\s*(?:true|1)\s*\)", txt) and not re.search(r"\b(?:yield|sleep|delay)\s*\(", txt):
            avisos.append("Hay un bucle aparentemente infinito sin pausa/yield detectable.")
        sugerencias = _mejoras(f["ruta"], txt)
        mejoras.extend(sugerencias)
        lista.append({"ruta": f["ruta"], "lineas": lineas, "funciones": funciones,
                      "avisos": avisos, "mejoras": sugerencias, "caracteres": len(txt)})
    dependencias = sorted(set(re.findall(r"#\s*include\s*[<\"]([^>\"]+)[>\"]", texto_total))
                         | set(re.findall(r"^\s*(?:import|from)\s+([\w.]+)", texto_total, re.M)))[:50]
    if not placas:
        placas = ["No identificada automáticamente"]
    if not componentes:
        componentes = ["No identificados por nombre de librería/protocolo"]
    return {"archivos": lista, "mejoras": mejoras[:100], "cantidad": len(lista), "lineas": sum(x["lineas"] for x in lista),
            "placas": placas, "componentes": componentes, "dependencias": dependencias,
            "nota": "Análisis heurístico: informa indicios, no compila ni ejecuta el proyecto."}
