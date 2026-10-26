# -*- coding: utf-8 -*-
"""Acceso de solo lectura a repositorios públicos de GitHub, iniciado por el usuario."""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

_EXT = {".ino", ".cpp", ".c", ".h", ".hpp", ".py", ".js", ".ts", ".java", ".rs",
        ".pde", ".yaml", ".yml", ".toml", ".md", ".xml", ".txt"}
_MAX_BLOB = 40_000
_MAX_TOTAL = 150_000
_MAX_FILES = 24


class ErrorGitHub(Exception):
    pass


class _SinRedireccion(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ErrorGitHub("GitHub redirigió la petición; vuelve a probar con la dirección principal del repositorio.")


def _repo(url):
    p = urllib.parse.urlsplit(str(url).strip())
    if p.scheme != "https" or p.hostname != "github.com" or p.username or p.password or p.query or p.fragment:
        raise ErrorGitHub("Usa una URL https://github.com/propietario/repositorio pública.")
    partes = [x for x in p.path.split("/") if x]
    if len(partes) != 2 or any(not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", x) for x in partes):
        raise ErrorGitHub("Pega la página principal del repositorio, sin ruta de archivo o rama.")
    return partes[0], partes[1].removesuffix(".git")


def _json(path):
    url = "https://api.github.com" + path
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json",
                                               "User-Agent": "CAZEL-IA/0.2 (read-only repository review)",
                                               "X-GitHub-Api-Version": "2022-11-28"})
    try:
        opener = urllib.request.build_opener(_SinRedireccion())
        with opener.open(req, timeout=12) as r:
            if urllib.parse.urlsplit(r.geturl()).hostname != "api.github.com":
                raise ErrorGitHub("La respuesta se salió del dominio de la API de GitHub.")
            data = r.read(8_000_000)
        return json.loads(data.decode("utf-8"))
    except ErrorGitHub:
        raise
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise ErrorGitHub("No encuentro ese repositorio público. Los repositorios privados no están disponibles aquí.")
        if e.code == 403:
            raise ErrorGitHub("GitHub limitó las consultas anónimas. Espera un rato y vuelve a probar.")
        raise ErrorGitHub(f"GitHub respondió con error HTTP {e.code}.")
    except (urllib.error.URLError, OSError, ValueError, UnicodeError) as e:
        raise ErrorGitHub(f"No pude leer GitHub: {getattr(e, 'reason', e)}")


def descargar(url):
    """Lee un número pequeño de archivos fuente públicos; jamás ejecuta ni escribe código."""
    owner, repo = _repo(url)
    base = f"/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(repo)}"
    meta = _json(base)
    branch = str(meta.get("default_branch", "main"))
    ref = _json(base + "/branches/" + urllib.parse.quote(branch, safe=""))
    tree_sha = ref.get("commit", {}).get("commit", {}).get("tree", {}).get("sha")
    if not tree_sha:
        raise ErrorGitHub("GitHub no devolvió el árbol de archivos de esa rama.")
    tree = _json(base + "/git/trees/" + urllib.parse.quote(str(tree_sha), safe="" ) + "?recursive=1")
    entradas = tree.get("tree", [])
    entradas.sort(key=lambda e: (0 if e.get("path", "").lower().endswith(("readme.md", "platformio.ini", "package.json", "requirements.txt")) else 1,
                                e.get("path", "")))
    archivos, total, vistos = [], 0, 0
    for e in entradas:
        path = str(e.get("path", ""))
        if e.get("type") != "blob" or not path or path.startswith((".git/", "node_modules/", "vendor/")):
            continue
        if path.rsplit("/", 1)[-1].startswith(".") or "." not in path.rsplit("/", 1)[-1]:
            continue
        if "." + path.rsplit(".", 1)[-1].lower() not in _EXT or int(e.get("size", 0) or 0) > _MAX_BLOB:
            continue
        if total >= _MAX_TOTAL or len(archivos) >= _MAX_FILES or vistos >= 35:
            break
        vistos += 1
        blob = _json(base + "/git/blobs/" + urllib.parse.quote(str(e.get("sha", "")), safe=""))
        if blob.get("encoding") != "base64":
            continue
        try:
            bruto = base64.b64decode(blob.get("content", ""), validate=False)
            texto = bruto.decode("utf-8")
        except (ValueError, UnicodeError):
            continue
        texto = texto[:min(_MAX_BLOB, _MAX_TOTAL-total)]
        if not texto:
            continue
        archivos.append({"ruta": path, "texto": texto})
        total += len(texto)
    return {"repositorio": f"{owner}/{repo}", "url": f"https://github.com/{owner}/{repo}",
            "rama": branch, "privado": bool(meta.get("private")), "truncado": bool(tree.get("truncated")),
            "archivos": archivos, "caracteres": total}
