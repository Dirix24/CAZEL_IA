"""Acciones compartidas por Terminal y la API local de Studio."""

import threading
import time
from pathlib import Path

from cazel import github_repo, proyecto

from .agent import Agent, Task
from .models import Router
from .store import Store


def text(data, key, size=500):
    value = data.get(key)
    if not isinstance(value, str) or not value.strip() or len(value) > size:
        raise ValueError(f"Campo inválido: {key}.")
    return value


class Interface:
    def __init__(self, datos, root, local):
        self.store = Store(datos, root)
        self.agent = Agent(self.store, Router(local, Path(datos) / "core2-modelos.json"))
        self.tasks = {}
        self.lock = threading.RLock()

    def action(self, operation, data):
        if operation == "sessions":
            return self.store.sessions()
        if operation == "open":
            path = Path(text(data, "path", 2000)).expanduser()
            return {"session": self.agent.open(self.store.base / path)}
        session = text(data, "session", 32)
        project, mode = self.store.session(session)
        if operation == "status":
            with self.lock:
                active = session in self.tasks
            return {"project": project, "mode": mode, "active": active,
                    "events": self.store.history(session)}
        if operation == "cancel":
            with self.lock:
                task = self.tasks.get(session)
                if task:
                    task.cancel.set()
            return {"cancelled": task is not None}
        ws = self.agent.workspace(session)
        if operation == "research":
            if data.get("authorized") is not True:
                raise ValueError("Autoriza primero la consulta de ese repositorio público.")
            try:
                remote = github_repo.descargar(text(data, "url", 300))
                result = {"repository": remote["repositorio"], "url": remote["url"],
                          "report": proyecto.analizar(remote["archivos"]),
                          "truncated": remote["truncado"]}
            except github_repo.ErrorGitHub as error:
                raise ValueError(str(error)) from error
            self.store.event(session, "research", **result)
            return result
        if operation == "files":
            return ws.files()
        if operation == "read":
            return {"content": ws.read(text(data, "path"))}
        if operation == "changes":
            return self.store.changes(session)
        if operation == "mode":
            selected = text(data, "mode")
            if selected not in ("offline", "online", "auto"):
                raise ValueError("Modo inválido.")
            with self.lock:
                if session in self.tasks:
                    raise ValueError("Espera a que termine la tarea para cambiar el modo.")
                self.store.mode(session, selected)
            return {"mode": selected}
        if operation == "stage":
            return self.agent.stage(session, ws, text(data, "path"), content=data.get("content"))
        if operation in {"accept", "reject", "undo"}:
            change = text(data, "id", 32)
            outcome = self.store.transition(session, ws, change, operation)
            self.store.event(session, "change", **outcome)
            return outcome
        if operation in {"start", "test"}:
            permission = data.get("testing", "")
            if permission not in ("", "isolated", "trusted"):
                raise ValueError("Permiso de pruebas inválido.")
            if operation == "test" and not permission:
                raise ValueError("Autoriza el perfil de pruebas primero.")
            prompt = text(data, "prompt", 8000) if operation == "start" else ""
            task = Task(threading.Event(), time.monotonic() + 240, permission,
                        data.get("remote") is True)
            with self.lock:
                if session in self.tasks:
                    raise ValueError("Ya hay una tarea activa en esta sesión.")
                self.tasks[session] = task
            threading.Thread(target=self._execute, args=(session, ws, task, prompt), daemon=True).start()
            return {"active": True}
        raise ValueError("Acción de Studio desconocida.")

    def _execute(self, session, ws, task, prompt):
        def approval(change, active):
            while not active.cancel.is_set() and time.monotonic() < active.deadline:
                outcome = self.store.change_state(session, change["id"])
                if outcome in {"applied", "rejected", "undone"}:
                    return {"state": outcome, **change}
                active.cancel.wait(0.2)
            return {"state": "pending", **change}

        try:
            if prompt:
                self.agent.run(session, prompt, task, approval)
            else:
                self.agent.tests(session, ws, task, "python-unittest")
        except (OSError, ValueError) as error:
            self.store.event(session, "result", state="failed", summary=str(error))
        finally:
            with self.lock:
                self.tasks.pop(session, None)

    def close(self):
        with self.lock:
            for task in self.tasks.values():
                task.cancel.set()
