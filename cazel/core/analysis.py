"""Análisis acotado de archivos fuente."""

import ast
from pathlib import Path

from cazel.proyecto import analizar

LANGUAGES = {
    ".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
    ".tsx": "TypeScript", ".html": "HTML", ".css": "CSS", ".c": "C", ".h": "C/C++",
    ".cpp": "C++", ".hpp": "C++", ".ino": "Arduino", ".java": "Java", ".rs": "Rust",
}


def inspect_file(path, text):
    language = LANGUAGES.get(Path(path).suffix.lower(), "Texto")
    result = {"language": language}
    if language == "Python":
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as error:
            return {**result, "confirmed": [{"line": error.lineno, "message": error.msg}]}
        result["symbols"] = [{"name": node.name, "line": node.lineno} for node in ast.walk(tree)
                             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))][:100]
        result["imports"] = sorted({
            name for node in ast.walk(tree)
            for name in ([a.name for a in node.names] if isinstance(node, ast.Import)
                         else [(node.level * ".") + (node.module or "")] if isinstance(node, ast.ImportFrom)
                         else [])
        })[:100]
    result["heuristics"] = analizar([{"ruta": path, "contenido": text}])
    return result


def context(ws, prompt):
    tokens = {s.lower() for s in prompt.split() if len(s) >= 3}
    files = ws.files()
    files.sort(key=lambda p: (-sum(t in p.lower() for t in tokens), p.count("/"), p))
    return [{"path": p, "language": LANGUAGES.get(Path(p).suffix.lower(), "Texto")}
            for p in files[:60]]
