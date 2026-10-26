# -*- coding: utf-8 -*-
"""
Transportes: la "tubería" por la que hablan CAZEL y el robot.

  SerieTransporte  puerto serie real. Usa pyserial si está instalado; si no,
                   en Linux y macOS usa `termios` (viene con Python), así que
                   en MX Linux funciona sin instalar nada.
  SimTransporte    un robot SIMULADO que habla el protocolo CAZEL-1. Sirve para
                   probar la interfaz sin hardware y para las pruebas.

Todos ofrecen: escribir_linea(texto), leer_linea(timeout) -> str|None, cerrar().
"""

import glob
import os
import re
import sys
import time

try:                                    # opcional
    import serial as _pyserial          # type: ignore
    from serial.tools import list_ports as _list_ports   # type: ignore
except Exception:                       # pragma: no cover - depende del equipo
    _pyserial = None
    _list_ports = None

try:
    import termios
    import select
except ImportError:                     # Windows
    termios = None
    select = None

_BAUDIOS_TERMIOS = {}
if termios is not None:
    for _b in (9600, 19200, 38400, 57600, 115200):
        _c = getattr(termios, f"B{_b}", None)
        if _c is not None:
            _BAUDIOS_TERMIOS[_b] = _c

_PUERTO_LINUX = re.compile(r"/dev/(ttyUSB\d+|ttyACM\d+)")
_PUERTO_MAC = re.compile(r"/dev/(cu|tty)\.(usbserial|usbmodem|wchusbserial)[\w.\-]*")
_PUERTO_WIN = re.compile(r"COM\d{1,3}")


def _familia_usb(vid, pid):
    """Pistas de identificación USB comunes; no garantizan el modelo exacto."""
    conocidos = {
        (0x2341, 0x0043): "Arduino Uno R3",
        (0x2A03, 0x0043): "Arduino Uno compatible",
        (0x2341, 0x0010): "Arduino Mega 2560",
        (0x2E8A, 0x0005): "Raspberry Pi Pico",
        (0x2E8A, 0x000A): "Raspberry Pi Pico W",
        (0x303A, 0x1001): "USB serie Espressif (posible ESP32)",
        (0x1A86, 0x7523): "Puente CH340 (común en clones Arduino)",
        (0x10C4, 0xEA60): "Puente CP210x (común en placas ESP)",
        (0x0483, 0x5740): "USB serie STM32 (posible placa STM32)",
    }
    return conocidos.get((vid, pid), "dispositivo USB serie; placa no identificada")


class ErrorTransporte(OSError):
    pass


def puerto_permitido(ruta):
    """Solo se abren puertos con forma de puerto USB-serie. Evita que alguien
    haga abrir /dev/sda, /dev/mem, un archivo cualquiera, etc."""
    r = str(ruta)
    return bool(_PUERTO_LINUX.fullmatch(r) or _PUERTO_MAC.fullmatch(r) or _PUERTO_WIN.fullmatch(r)
                or r == "simulado" or (os.environ.get("CAZEL_PERMITIR_PTY") and r.startswith("/dev/pts/")))


def listar_puertos():
    """[{puerto, descripcion}] sin enviar nada a ningún dispositivo."""
    salida = []
    if _list_ports is not None:
        try:
            for p in _list_ports.comports():
                if puerto_permitido(p.device):
                    detalle = (p.description or "")[:60]
                    fabricante = (getattr(p, "manufacturer", None) or "")[:40]
                    producto = (getattr(p, "product", None) or "")[:40]
                    vid, pid = getattr(p, "vid", None), getattr(p, "pid", None)
                    if vid is not None and pid is not None:
                        detalle += f" · USB {vid:04X}:{pid:04X} · " + _familia_usb(vid, pid)
                    elif producto or fabricante:
                        detalle += " · " + " ".join(x for x in (fabricante, producto) if x)
                    salida.append({"puerto": p.device, "descripcion": detalle[:160]})
            return sorted(salida, key=lambda x: x["puerto"])
        except Exception:
            salida = []
    candidatos = []
    if sys.platform.startswith("linux"):
        candidatos = glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
    elif sys.platform == "darwin":
        candidatos = glob.glob("/dev/cu.usb*") + glob.glob("/dev/cu.wchusb*")
    for c in sorted(candidatos):
        if puerto_permitido(c):
            salida.append({"puerto": c, "descripcion": "puerto USB-serie"})
    return salida


class SerieTransporte:
    def __init__(self, puerto, baudios=115200, espera_arranque=2.0):
        if not puerto_permitido(puerto):
            raise ErrorTransporte("Ese no parece un puerto de robot (esperaba ttyUSB, ttyACM, COM...).")
        self.puerto, self.baudios = puerto, int(baudios)
        self._buf = b""
        self._fd = None
        self._ser = None
        if _pyserial is not None:
            try:
                self._ser = _pyserial.Serial(puerto, self.baudios, timeout=0.1, write_timeout=1.0)
            except Exception as e:
                raise ErrorTransporte(self._explicar(e))
        elif termios is not None:
            self._abrir_termios()
        else:
            raise ErrorTransporte("En Windows hace falta pyserial: ejecuta PREPARAR_USB una vez "
                                  "con internet (o «pip install pyserial»).")
        if espera_arranque > 0:
            time.sleep(espera_arranque)         # un Arduino se reinicia al abrir el puerto
        self.vaciar()

    @staticmethod
    def _explicar(e):
        t = str(e)
        if "ermission" in t or "13" in t:
            return (f"Sin permiso para usar el puerto. En Linux añade tu usuario al grupo dialout: "
                    f"sudo usermod -aG dialout $USER (y vuelve a iniciar sesión). Detalle: {t}")
        if "busy" in t.lower() or "16" in t:
            return f"El puerto está ocupado (¿tienes abierto el Arduino IDE o el monitor serie?). {t}"
        return f"No pude abrir el puerto: {t}"

    def _abrir_termios(self):
        if self.baudios not in _BAUDIOS_TERMIOS:
            raise ErrorTransporte("Velocidad no soportada.")
        try:
            fd = os.open(self.puerto, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as e:
            raise ErrorTransporte(self._explicar(e))
        try:
            attrs = termios.tcgetattr(fd)
            attrs[0] = termios.IGNPAR                               # iflag
            attrs[1] = 0                                            # oflag
            attrs[2] = (termios.CS8 | termios.CREAD | termios.CLOCAL)   # cflag (8N1)
            attrs[3] = 0                                            # lflag: modo crudo
            attrs[4] = attrs[5] = _BAUDIOS_TERMIOS[self.baudios]
            attrs[6][termios.VMIN] = 0
            attrs[6][termios.VTIME] = 0
            termios.tcsetattr(fd, termios.TCSANOW, attrs)
        except Exception as e:
            os.close(fd)
            raise ErrorTransporte(f"No pude configurar el puerto: {e}")
        self._fd = fd

    def vaciar(self):
        self._buf = b""
        try:
            if self._ser is not None:
                self._ser.reset_input_buffer()
            elif self._fd is not None:
                termios.tcflush(self._fd, termios.TCIFLUSH)
        except Exception:
            pass

    def escribir_linea(self, texto):
        datos = (str(texto).replace("\r", "").replace("\n", " ") + "\n").encode("ascii", "replace")
        try:
            if self._ser is not None:
                self._ser.write(datos)
                self._ser.flush()
            elif self._fd is not None:
                restante = datos
                limite = time.monotonic() + 1.0
                while restante and time.monotonic() < limite:
                    try:
                        n = os.write(self._fd, restante)
                        restante = restante[n:]
                    except BlockingIOError:
                        select.select([], [self._fd], [], 0.05)
                if restante:
                    raise ErrorTransporte("El puerto no aceptó los datos a tiempo.")
            else:
                raise ErrorTransporte("Puerto cerrado.")
        except OSError as e:
            raise ErrorTransporte(f"Se perdió la conexión con el robot: {e}")

    def _leer_bytes(self, espera):
        if self._ser is not None:
            self._ser.timeout = max(0.0, espera)
            return self._ser.read(256)
        if self._fd is None:
            raise ErrorTransporte("Puerto cerrado.")
        r, _, _ = select.select([self._fd], [], [], max(0.0, espera))
        if not r:
            return b""
        try:
            return os.read(self._fd, 256)
        except BlockingIOError:
            return b""

    def leer_linea(self, timeout=2.0):
        limite = time.monotonic() + timeout
        try:
            while True:
                if b"\n" in self._buf:
                    linea, _, self._buf = self._buf.partition(b"\n")
                    return linea.decode("ascii", "replace").strip("\r ")
                if len(self._buf) > 512:            # basura sin fin de línea
                    self._buf = b""
                falta = limite - time.monotonic()
                if falta <= 0:
                    return None
                self._buf += self._leer_bytes(min(falta, 0.1))
        except OSError as e:
            raise ErrorTransporte(f"Se perdió la conexión con el robot: {e}")

    def cerrar(self):
        try:
            if self._ser is not None:
                self._ser.close()
            elif self._fd is not None:
                os.close(self._fd)
        except OSError:
            pass
        self._ser, self._fd = None, None


class SimTransporte:
    """Robot simulado: avanza, gira, para y mide una distancia."""

    NOMBRE = "robot_simulado"

    def __init__(self):
        self.x = 0.0
        self.angulo = 0.0
        self.paradas = 0
        self.historial = []
        self._salida = []
        self._abierto = True

    def escribir_linea(self, texto):
        if not self._abierto:
            raise ErrorTransporte("Puerto cerrado.")
        t = str(texto).strip()
        self.historial.append(t)
        p = t.split()
        if not p:
            return
        c = p[0].lower()
        r = self._salida.append
        if c == "ayuda":
            for l in (f"CAZEL 1 {self.NOMBRE}", "ORDEN avanzar cm:0:50",
                      "ORDEN girar grados:-180:180", "ORDEN parar", "LECTURA distancia cm", "FIN"):
                r(l)
        elif c == "parar":
            self.paradas += 1
            r("OK")
        elif c == "leer" and len(p) == 2 and p[1].lower() == "distancia":
            r(f"VAL {max(0.0, 100.0 - self.x):g}")
        elif c in ("avanzar", "girar") and len(p) == 2:
            try:
                v = float(p[1])
            except ValueError:
                r("ERR valor no numerico")
                return
            if c == "avanzar" and 0 <= v <= 50:
                self.x += v
                r("OK")
            elif c == "girar" and -180 <= v <= 180:
                self.angulo = (self.angulo + v) % 360
                r("OK")
            else:
                r("ERR fuera de rango")
        else:
            r("ERR orden desconocida")

    def leer_linea(self, timeout=2.0):
        return self._salida.pop(0) if self._salida else None

    def vaciar(self):
        self._salida.clear()

    def cerrar(self):
        self._abierto = False
