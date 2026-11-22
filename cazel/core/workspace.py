"""Operaciones acotadas sobre un proyecto seleccionado por el usuario."""

import difflib
import os
from pathlib import Path, PureWindowsPath
import re
import stat
import tempfile

from cazel.seguridad import ruta_dentro

MAX_FILE = 128 * 1024
IGNORADOS = {"node_modules", "vendor", "target", "build", "dist", "__pycache__", "libs"}
SECRETOS = {"credentials", "secrets", "id_rsa", "id_ed25519", "token", "tokens"}


def visible(nombre):
    partes = re.split(r"[._-]", nombre.lower())
    return (not nombre.startswith(".") and nombre.lower() not in IGNORADOS
            and not SECRETOS.intersection(partes) and nombre.lower() not in SECRETOS
            and not nombre.lower().startswith(("id_rsa", "id_ed25519"))
            and Path(nombre).suffix.lower() not in {".pem", ".key", ".pfx", ".p12", ".gguf"})


class Workspace:
    def __init__(self, ruta, protegida):
        self.root = Path(ruta).resolve(strict=True)
        if not self.root.is_dir() or self.root == Path(self.root.anchor):
            raise ValueError("Selecciona una carpeta de proyecto concreta.")
        self.protegida = Path(protegida).resolve()
        if self.protegida == self.root or self.protegida in self.root.parents:
            raise ValueError("La memoria de CAZEL está protegida.")

    def path(self, nombre):
        if not isinstance(nombre, str) or len(nombre) > 500:
            raise ValueError("Ruta inválida.")
        partes = nombre.split("/")
        if any(not p or not visible(p) or p.endswith((" ", ".")) or
               PureWindowsPath(p).is_reserved() or re.search(r'[\\:*?"<>|\x00-\x1f]', p)
               for p in partes):
            raise ValueError("Ruta bloqueada.")
        ruta = self.root
        for p in partes:
            ruta /= p
            try:
                info = ruta.lstat()
            except FileNotFoundError:
                continue
            if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 1024:
                raise ValueError("Enlace bloqueado.")
            if ruta != self.root.joinpath(*partes) and not stat.S_ISDIR(info.st_mode):
                raise ValueError("La ruta intermedia no es una carpeta.")
        if not ruta_dentro(self.root, ruta) or ruta == self.protegida or self.protegida in ruta.parents:
            raise ValueError("Ruta bloqueada.")
        return ruta

    def read(self, nombre, missing=False):
        ruta = self.path(nombre)
        try:
            info = ruta.lstat()
        except FileNotFoundError:
            if missing:
                return None
            raise
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_FILE:
            raise ValueError("Archivo especial, enlazado o demasiado grande.")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        with os.fdopen(os.open(ruta, flags), "rb") as archivo:
            bruto = archivo.read(MAX_FILE + 1)
        if len(bruto) > MAX_FILE or b"\0" in bruto:
            raise ValueError("Solo se permiten archivos de texto UTF-8 acotados.")
        return bruto.decode("utf-8")

    def files(self, limite=500):
        archivos = []
        visitados = 0
        for carpeta, dirs, nombres in os.walk(self.root):
            dirs[:] = sorted(d for d in dirs if visible(d)
                             and Path(carpeta, d).resolve() != self.protegida)
            for nombre in sorted(nombres):
                visitados += 1
                if visitados > 3000 or len(archivos) >= limite:
                    return archivos
                relativo = Path(carpeta, nombre).relative_to(self.root).as_posix()
                try:
                    ruta = self.path(relativo)
                    info = ruta.lstat()
                    if stat.S_ISREG(info.st_mode) and info.st_nlink == 1 and info.st_size <= MAX_FILE:
                        archivos.append(relativo)
                except (OSError, ValueError):
                    continue
        return archivos

    def replace(self, nombre, esperado, nuevo):
        if self.read(nombre, missing=True) != esperado:
            raise ValueError("El archivo cambió desde la previsualización.")
        ruta = self.path(nombre)
        if nuevo is None:
            ruta.unlink()
            return
        bruto = nuevo.encode("utf-8")
        if len(bruto) > MAX_FILE or b"\0" in bruto:
            raise ValueError("Contenido inválido o demasiado grande.")
        ruta.parent.mkdir(parents=True, exist_ok=True)
        ruta = self.path(nombre)
        fd, temporal = tempfile.mkstemp(prefix=".cazel-", dir=ruta.parent)
        try:
            with os.fdopen(fd, "wb") as archivo:
                archivo.write(bruto)
                archivo.flush()
                os.fsync(archivo.fileno())
            if esperado is not None:
                os.chmod(temporal, stat.S_IMODE(ruta.stat().st_mode) & 0o777)
            os.replace(temporal, ruta)
        finally:
            Path(temporal).unlink(missing_ok=True)


def diferencia(nombre, antes, despues):
    lineas = difflib.unified_diff(
        (antes or "").splitlines(keepends=True), (despues or "").splitlines(keepends=True),
        fromfile="/dev/null" if antes is None else "a/" + nombre,
        tofile="/dev/null" if despues is None else "b/" + nombre,
    )
    return "".join(l if l.endswith("\n") else l + "\n\\ No newline at end of file\n" for l in lineas)


def aplicar_hunks(texto, parche):
    """Parche unificado de un solo archivo. Verifica contexto y tamaños."""
    original = (texto or "").splitlines(keepends=True)
    lineas = parche.splitlines(keepends=True)
    if len(lineas) < 3 or not lineas[0].startswith("--- ") or not lineas[1].startswith("+++ "):
        raise ValueError("Se esperaba un parche unificado.")
    # El destino se elige en el parámetro path. Las cabeceras son informativas.
    resultado = []
    cursor = 0
    i = 2
    while i < len(lineas):
        hunk = re.fullmatch(r"@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@[^\n]*\n?", lineas[i])
        if not hunk:
            raise ValueError("Cabecera de parche inválida.")
        inicio, quitar, destino, poner = (int(v) if v is not None else 1 for v in hunk.groups())
        inicio -= bool(quitar)
        destino -= bool(poner)
        if not cursor <= inicio <= len(original):
            raise ValueError("Posición del parche inválida.")
        resultado.extend(original[cursor:inicio])
        if destino != len(resultado):
            raise ValueError("Posición nueva del parche inválida.")
        cursor = inicio
        i += 1
        while quitar or poner:
            if i >= len(lineas) or lineas[i][:1] not in {" ", "+", "-"}:
                raise ValueError("Parche incompleto.")
            marca, contenido = lineas[i][0], lineas[i][1:]
            i += 1
            if i < len(lineas) and lineas[i].rstrip("\n") == "\\ No newline at end of file":
                contenido = contenido.removesuffix("\n")
                i += 1
            if marca in {" ", "-"}:
                if quitar <= 0 or cursor >= len(original) or original[cursor] != contenido:
                    raise ValueError("El contexto del parche no coincide.")
                cursor += 1
                quitar -= 1
            if marca in {" ", "+"}:
                if poner <= 0:
                    raise ValueError("El tamaño del parche no coincide.")
                resultado.append(contenido)
                poner -= 1
    return "".join(resultado + original[cursor:])
