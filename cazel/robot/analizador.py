# -*- coding: utf-8 -*-
"""
«Entender» el código de un Arduino y proponer un adaptador.

Honestidad por delante: esto NO es inteligencia artificial. Es un analizador
por reglas (expresiones regulares) que busca en tu sketch lo que casi todos
tienen: pines, servos, sensores de distancia, velocidad del puerto serie y
palabras de órdenes que ya recibes. Con eso:

  1. te enseña lo que encontró, para que tú confirmes si es correcto;
  2. propone un perfil de órdenes (p. ej. «servo_pin9 grados 0..180»);
  3. genera el texto de un sketch ADAPTADOR que habla el protocolo CAZEL-1.

CAZEL nunca sube código a la placa. El adaptador es un texto para que tú lo
leas, lo cambies si hace falta y lo subas con el Arduino IDE.

Límite: si tu código usa clases, macros raras o librerías de motores
propias, el analizador puede no verlo todo. Por eso el resultado es una
PROPUESTA que revisas, no una verdad.
"""

import re

from .protocolo import NOMBRE_VALIDO, RESERVADOS

MAX_CODIGO = 200_000

_RE_COMENTARIOS = re.compile(r"//[^\n]*|/\*.*?\*/", re.S)
_RE_DEFINE = re.compile(r"^\s*#define\s+([A-Za-z_]\w*)\s+(A?\d{1,3})\b", re.M)
_RE_CONST = re.compile(r"\b(?:const\s+)?(?:byte|int|uint8_t|short|unsigned\s+int)\s+([A-Za-z_]\w*)\s*=\s*(A?\d{1,3})\s*;")
_RE_INCLUDE = re.compile(r"#include\s*[<\"]([\w./+-]+)[>\"]")
_RE_BAUD = re.compile(r"Serial\s*\.\s*begin\s*\(\s*(\d{3,7})\s*\)")
_RE_PINMODE = re.compile(r"pinMode\s*\(\s*([A-Za-z_]\w*|A?\d{1,3})\s*,\s*(OUTPUT|INPUT_PULLUP|INPUT)\s*\)")
_RE_SERVO_DECL = re.compile(r"\bServo\s+([A-Za-z_]\w*)\s*(?:,\s*([A-Za-z_]\w*)\s*)*;")
_RE_SERVO_ATTACH = re.compile(r"([A-Za-z_]\w*)\s*\.\s*attach\s*\(\s*([A-Za-z_]\w*|\d{1,3})")
_RE_ANALOGWRITE = re.compile(r"analogWrite\s*\(\s*([A-Za-z_]\w*|\d{1,3})\s*,")
_RE_DIGITALWRITE = re.compile(r"digitalWrite\s*\(\s*([A-Za-z_]\w*|\d{1,3})\s*,")
_RE_ANALOGREAD = re.compile(r"analogRead\s*\(\s*([A-Za-z_]\w*|A\d{1,2}|\d{1,2})\s*\)")
_RE_DIGITALREAD = re.compile(r"digitalRead\s*\(\s*([A-Za-z_]\w*|\d{1,3})\s*\)")
_RE_PULSEIN = re.compile(r"pulseIn\s*\(\s*([A-Za-z_]\w*|\d{1,3})\s*,")
_RE_CMD_STR = re.compile(r"(?:==|strcmp\s*\([^,]+,)\s*\"([A-Za-z_][\w ]{0,23})\"")
_RE_CASE_CHAR = re.compile(r"case\s+'(\w)'\s*:")

_PLACAS = (
    ("ESP32", ("ESP32", "ESP32Servo.h", "WiFi.h")),
    ("ESP8266", ("ESP8266", "ESP8266WiFi.h")),
    ("Raspberry Pi Pico / RP2040", ("RP2040", "pico/stdlib.h", "Adafruit_TinyUSB.h")),
    ("STM32", ("STM32", "stm32")),
    ("Arduino Mega", ("Mega2560", "ATmega2560")),
    ("Arduino Uno/Nano", ("ATmega328P", "ARDUINO_AVR_UNO", "ARDUINO_AVR_NANO")),
)


def detectar_placas(texto, librerias):
    """Identifica familias probables por indicios; no sustituye la selección de placa del IDE."""
    fuente = (texto + "\n" + "\n".join(librerias)).lower()
    halladas = []
    for nombre, pistas in _PLACAS:
        if any(p.lower() in fuente for p in pistas):
            halladas.append(nombre)
    if not halladas:
        halladas.append("Arduino compatible (familia no identificada)")
    return halladas


_CONOCIDAS = {
    "Servo.h": "servomotores", "AFMotor.h": "driver de motores (Adafruit Motor Shield v1)",
    "Adafruit_MotorShield.h": "driver de motores (Adafruit Motor Shield v2)",
    "NewPing.h": "sensor de distancia ultrasónico", "Wire.h": "bus I2C",
    "SoftwareSerial.h": "puerto serie por software (p. ej. Bluetooth)",
    "DHT.h": "sensor de temperatura/humedad", "Stepper.h": "motor paso a paso",
    "AccelStepper.h": "motor paso a paso", "IRremote.h": "mando infrarrojo",
    "LiquidCrystal.h": "pantalla LCD", "SPI.h": "bus SPI",
}


def _resolver(token, constantes):
    """Pin como texto: 'A0', '9' o el valor de una constante."""
    if token in constantes:
        return constantes[token]
    if re.fullmatch(r"A?\d{1,3}", token):
        return token
    return None


def analizar_codigo(texto):
    """Devuelve un informe con lo encontrado y una propuesta de perfil."""
    if not isinstance(texto, str) or not texto.strip():
        raise ValueError("No hay código que analizar.")
    if len(texto) > MAX_CODIGO:
        raise ValueError("El código es demasiado largo (máximo 200 000 caracteres).")
    limpio = _RE_COMENTARIOS.sub("", texto)

    constantes = {}
    for nombre, valor in _RE_DEFINE.findall(limpio) + _RE_CONST.findall(limpio):
        constantes.setdefault(nombre, valor)

    librerias = sorted({i for i in _RE_INCLUDE.findall(limpio)})
    baud = next((int(b) for b in _RE_BAUD.findall(limpio)), None)

    modos = {}                                  # pin -> OUTPUT/INPUT/INPUT_PULLUP
    for tok, modo in _RE_PINMODE.findall(limpio):
        p = _resolver(tok, constantes)
        if p is not None:
            modos[p] = modo

    servos = []
    for var, tok in _RE_SERVO_ATTACH.findall(limpio):
        p = _resolver(tok, constantes)
        if p is not None and p not in [s["pin"] for s in servos]:
            servos.append({"variable": var, "pin": p})

    def pines(regex):
        vistos = []
        for tok in regex.findall(limpio):
            p = _resolver(tok, constantes)
            if p is not None and p not in vistos:
                vistos.append(p)
        return vistos

    pwm = pines(_RE_ANALOGWRITE)
    digitales = [p for p in pines(_RE_DIGITALWRITE) if p not in pwm]
    analogicos = pines(_RE_ANALOGREAD)
    echo = pines(_RE_PULSEIN)
    ultra = None
    if echo:
        salidas = [p for p, m in modos.items() if m == "OUTPUT" and p not in pwm and p not in echo]
        ultra = {"echo": echo[0], "trig": salidas[0] if salidas else None}
    ordenes_existentes = sorted({c for c in _RE_CMD_STR.findall(limpio)}
                                | {f"'{c}'" for c in _RE_CASE_CHAR.findall(limpio)})
    servo_pines = {s["pin"] for s in servos}
    digitales = [p for p in digitales if p not in servo_pines]
    pwm = [p for p in pwm if p not in servo_pines]
    if ultra and ultra["trig"]:
        digitales = [p for p in digitales if p != ultra["trig"]]

    # --- propuesta ---
    ordenes, lecturas = {}, {}
    plan = {"servos": [], "pwm": [], "digitales": [], "lecturas_analogicas": [], "ultrasonico": None}
    for s in servos:
        n = f"servo_{s['pin'].lower()}"
        ordenes[n] = {"parametro": "grados", "min": 0, "max": 180}
        plan["servos"].append({"orden": n, **s})
    for p in pwm:
        n = f"pwm_{p.lower()}"
        ordenes[n] = {"parametro": "valor", "min": 0, "max": 255}
        plan["pwm"].append({"orden": n, "pin": p})
    for p in digitales:
        n = f"pin_{p.lower()}"
        ordenes[n] = {"parametro": "estado", "min": 0, "max": 1}
        plan["digitales"].append({"orden": n, "pin": p})
    for p in analogicos:
        if not p.upper().startswith("A") and not p.isdigit():
            continue
        n = f"analogico_{p.lower()}"
        lecturas[n] = {"unidad": "0-1023"}
        plan["lecturas_analogicas"].append({"lectura": n, "pin": p})
    if ultra and ultra["trig"]:
        lecturas["distancia"] = {"unidad": "cm"}
        plan["ultrasonico"] = ultra
    ordenes["parar"] = {"parametro": None, "min": None, "max": None}

    notas = []
    if "AFMotor.h" in librerias or "Adafruit_MotorShield.h" in librerias or "Stepper.h" in librerias \
            or "AccelStepper.h" in librerias:
        notas.append("Usas una librería de motores. El adaptador solo controla pines sueltos; "
                     "los motores de esa librería los tendrás que enlazar a mano en el adaptador.")
    if ordenes_existentes:
        notas.append("Tu código ya reconoce estas órdenes: " + ", ".join(ordenes_existentes)
                     + ". Puedes dejarlas como están y añadir el adaptador aparte.")
    if len(ordenes) == 1 and not lecturas:
        notas.append("No encontré pines ni servos que controlar. ¿Es un sketch completo?")
    if baud and baud not in (9600, 19200, 38400, 57600, 115200):
        notas.append(f"Tu código usa {baud} baudios; CAZEL admite 9600, 19200, 38400, 57600 y 115200.")

    placas = detectar_placas(limpio, librerias)
    notas.append("Placa(s) probable(s): " + ", ".join(placas) +
                 ". Comprueba la placa y el mapa de pines en el IDE antes de cargar el adaptador.")

    return {"placas_probables": placas,
            "baudios": baud if baud in (9600, 19200, 38400, 57600, 115200) else 115200,
            "baudios_codigo": baud,
            "librerias": [{"nombre": l, "descripcion": _CONOCIDAS.get(l, "")} for l in librerias],
            "modos_pin": modos, "plan": plan, "ordenes_existentes": ordenes_existentes,
            "propuesta": {"nombre": "mi_robot", "ordenes": ordenes, "lecturas": lecturas,
                          "origen": "codigo", "baudios": baud if baud in (9600, 19200, 38400, 57600, 115200) else 115200},
            "notas": notas}


def _pin_cpp(p):
    return p if p.upper().startswith("A") else str(int(p))


def generar_adaptador(informe, nombre_robot="mi_robot"):
    """Texto de un sketch .ino que habla CAZEL-1 con los pines detectados."""
    nombre_robot = str(nombre_robot).lower()
    if not NOMBRE_VALIDO.fullmatch(nombre_robot) or nombre_robot in RESERVADOS:
        raise ValueError("Nombre de robot no válido (usa a-z, 0-9 y _; empieza por letra).")
    plan = informe["plan"]
    servos = plan["servos"]
    pwm = [x["pin"] for x in plan["pwm"]]
    dig = [x["pin"] for x in plan["digitales"]]
    ana, ultra = plan["lecturas_analogicas"], plan["ultrasonico"]
    baud = int(informe["baudios"])

    L = []
    add = L.append
    add("// ============================================================")
    add("// CAZEL IA - ADAPTADOR (generado automáticamente)")
    add("// REVÍSALO antes de subirlo: comprueba que cada pin es el correcto.")
    add("// CAZEL no sube código a tu placa; súbelo tú con el Arduino IDE.")
    add("// ============================================================")
    if servos:
        add("#include <Servo.h>")
    add("")
    add(f'const char NOMBRE[] = "{nombre_robot}";')
    add(f"const long BAUDIOS = {baud};")
    add("// Si no llega ninguna orden en este tiempo, las salidas PWM y digitales se apagan.")
    add("const unsigned long WATCHDOG_MS = 3000;")
    add("")
    for s in servos:
        add(f"Servo servo_{s['pin'].lower()};           // pin {s['pin']}")
    for p in pwm:
        add(f"const int PIN_PWM_{p.upper()} = {_pin_cpp(p)};")
    for p in dig:
        add(f"const int PIN_{p.upper()} = {_pin_cpp(p)};")
    for a in ana:
        add(f"const int PIN_ANALOGICO_{a['pin'].upper()} = {_pin_cpp(a['pin'])};")
    if ultra:
        add(f"const int PIN_TRIG = {_pin_cpp(ultra['trig'])};")
        add(f"const int PIN_ECHO = {_pin_cpp(ultra['echo'])};")
    add("")
    add("char linea[40];")
    add("byte largo = 0;")
    add("unsigned long ultimaOrden = 0;")
    add("bool salidasActivas = false;")
    add("")
    add("void pararTodo() {")
    for p in pwm:
        add(f"  analogWrite(PIN_PWM_{p.upper()}, 0);")
    for p in dig:
        add(f"  digitalWrite(PIN_{p.upper()}, LOW);")
    add("  salidasActivas = false;")
    add("}")
    add("")
    add("void setup() {")
    add("  Serial.begin(BAUDIOS);")
    for p in pwm:
        add(f"  pinMode(PIN_PWM_{p.upper()}, OUTPUT);")
    for p in dig:
        add(f"  pinMode(PIN_{p.upper()}, OUTPUT);")
    for s in servos:
        add(f"  servo_{s['pin'].lower()}.attach({_pin_cpp(s['pin'])});")
    if ultra:
        add("  pinMode(PIN_TRIG, OUTPUT);")
        add("  pinMode(PIN_ECHO, INPUT);")
    add("  pararTodo();")
    add("}")
    add("")
    add("void responderAyuda() {")
    add('  Serial.print("CAZEL 1 "); Serial.println(NOMBRE);')
    for s in servos:
        add(f'  Serial.println("ORDEN servo_{s["pin"].lower()} grados:0:180");')
    for p in pwm:
        add(f'  Serial.println("ORDEN pwm_{p.lower()} valor:0:255");')
    for p in dig:
        add(f'  Serial.println("ORDEN pin_{p.lower()} estado:0:1");')
    add('  Serial.println("ORDEN parar");')
    for a in ana:
        add(f'  Serial.println("LECTURA analogico_{a["pin"].lower()} 0-1023");')
    if ultra:
        add('  Serial.println("LECTURA distancia cm");')
    add('  Serial.println("FIN");')
    add("}")
    add("")
    if ultra:
        add("long leerDistanciaCm() {")
        add("  digitalWrite(PIN_TRIG, LOW);  delayMicroseconds(2);")
        add("  digitalWrite(PIN_TRIG, HIGH); delayMicroseconds(10);")
        add("  digitalWrite(PIN_TRIG, LOW);")
        add("  long us = pulseIn(PIN_ECHO, HIGH, 30000UL);   // tope: ~5 m")
        add("  if (us == 0) return -1;                       // sin eco")
        add("  return us / 58;")
        add("}")
        add("")
    add("void procesar(char *texto) {")
    add('  char *nombre = strtok(texto, " ");')
    add("  if (nombre == NULL) return;")
    add('  char *valorTxt = strtok(NULL, " ");')
    add("  long valor = valorTxt ? atol(valorTxt) : 0;")
    add("")
    add('  if (strcmp(nombre, "AYUDA") == 0) { responderAyuda(); return; }')
    add('  if (strcmp(nombre, "PARAR") == 0 || strcmp(nombre, "parar") == 0) { pararTodo(); Serial.println("OK"); return; }')
    add('  if (strcmp(nombre, "LEER") == 0) {')
    add('    if (valorTxt == NULL) { Serial.println("ERR falta la lectura"); return; }')
    first = True
    for a in ana:
        add(f'    {"" if first else "else "}if (strcmp(valorTxt, "analogico_{a["pin"].lower()}") == 0) '
            f'{{ Serial.print("VAL "); Serial.println(analogRead(PIN_ANALOGICO_{a["pin"].upper()})); return; }}')
        first = False
    if ultra:
        add(f'    {"" if first else "else "}if (strcmp(valorTxt, "distancia") == 0) {{')
        add("      long d = leerDistanciaCm();")
        add('      if (d < 0) Serial.println("ERR sin eco");')
        add('      else { Serial.print("VAL "); Serial.println(d); }')
        add("      return;")
        add("    }")
        first = False
    add('    Serial.println("ERR lectura desconocida");')
    add("    return;")
    add("  }")
    add("")
    add('  if (valorTxt == NULL) { Serial.println("ERR falta el valor"); return; }')
    add("  ultimaOrden = millis();")
    for s in servos:
        n = s["pin"].lower()
        add(f'  if (strcmp(nombre, "servo_{n}") == 0) {{')
        add('    if (valor < 0 || valor > 180) { Serial.println("ERR fuera de rango"); return; }')
        add(f"    servo_{n}.write((int)valor); Serial.println(\"OK\"); return;")
        add("  }")
    for p in pwm:
        add(f'  if (strcmp(nombre, "pwm_{p.lower()}") == 0) {{')
        add('    if (valor < 0 || valor > 255) { Serial.println("ERR fuera de rango"); return; }')
        add(f"    analogWrite(PIN_PWM_{p.upper()}, (int)valor); salidasActivas = true; Serial.println(\"OK\"); return;")
        add("  }")
    for p in dig:
        add(f'  if (strcmp(nombre, "pin_{p.lower()}") == 0) {{')
        add('    if (valor != 0 && valor != 1) { Serial.println("ERR fuera de rango"); return; }')
        add(f"    digitalWrite(PIN_{p.upper()}, valor ? HIGH : LOW); salidasActivas = true; Serial.println(\"OK\"); return;")
        add("  }")
    add('  Serial.println("ERR orden desconocida");')
    add("}")
    add("")
    add("void loop() {")
    add("  while (Serial.available() > 0) {")
    add("    char c = Serial.read();")
    add("    if (c == '\\r') continue;")
    add("    if (c == '\\n') { linea[largo] = 0; procesar(linea); largo = 0; }")
    add("    else if (largo < sizeof(linea) - 1) { linea[largo++] = c; }")
    add("    else { largo = 0; }                    // línea demasiado larga: se descarta")
    add("  }")
    add("  if (salidasActivas && millis() - ultimaOrden > WATCHDOG_MS) pararTodo();")
    add("}")
    return "\n".join(L) + "\n"
