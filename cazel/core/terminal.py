"""Consola interactiva de CAZEL Core 2."""

import json
import re
import threading
import time

from .agent import Task

HELP = """/project [ruta]   Abrir proyecto o listar sesiones
/session ID       Recuperar una sesión de Terminal o Studio
/model [modo]     offline, online o auto
/status           Historial y estado
/diff             Cambios de la sesión
/accept ID        Aplicar una propuesta
/reject ID        Rechazar una propuesta
/undo [ID]        Deshacer la edición indicada o la última aplicada
/test             Ejecutar unittest con permiso
/learn LENGUAJE | NOTA  Guardar una corrección del proyecto
/lessons          Mostrar las correcciones guardadas
/forget ID        Eliminar una corrección
/research URL     Analizar un repositorio público de GitHub con permiso
/clear            Limpiar pantalla
/help             Mostrar comandos
/exit             Salir
Escribe una petición de programación para iniciar una tarea."""


def show(value):
    rendered = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2)
    print(re.sub(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]", "?", rendered))


def test_permission():
    answer = input("Pruebas unittest [i: aisladas, c: proyecto confiable sin aislamiento, Enter: denegar] ")
    return {"i": "isolated", "c": "trusted"}.get(answer.strip().lower(), "")


def terminal(ui, project=None):
    print("CAZEL Terminal · /help")
    session = ui.action("open", {"path": project})["session"] if project else None
    while True:
        try:
            line = input("CAZEL > ").strip()
            if not line:
                continue
            command, _, argument = line.partition(" ")
            argument = argument.strip()
            if command == "/exit":
                return
            if command == "/help":
                print(HELP)
                continue
            if command == "/clear":
                print("\033[2J\033[H", end="")
                continue
            if command == "/project":
                if argument:
                    session = ui.action("open", {"path": argument})["session"]
                    print("Proyecto seleccionado.")
                else:
                    show(ui.action("sessions", {}))
                continue
            if command == "/session":
                ui.store.session(argument)
                session = argument
                continue
            if not session:
                print("Selecciona un proyecto con /project ruta.")
                continue
            data = {"session": session}
            if command == "/status" or (command == "/model" and not argument):
                show(ui.action("status", data))
            elif command == "/model":
                show(ui.action("mode", {**data, "mode": argument}))
            elif command == "/diff":
                for change in ui.action("changes", data):
                    show(f"{change['id']} · {change['state']}\n{change['diff']}")
            elif command in {"/undo", "/accept", "/reject"}:
                if command == "/undo" and not argument:
                    argument = next((c["id"] for c in ui.store.changes(session)
                                     if c["state"] == "applied"), "")
                show(ui.action(command[1:], {**data, "id": argument}))
            elif command == "/test":
                permission = test_permission()
                if permission:
                    task = Task(threading.Event(), time.monotonic() + 30, permission)
                    show(ui.agent.tests(session, ui.agent.workspace(session), task, "python-unittest"))
            elif command == "/learn":
                language, _, note = argument.partition("|")
                show(ui.action("learn", {**data, "language": language, "note": note}))
            elif command == "/lessons":
                show(ui.action("lessons", data))
            elif command == "/forget":
                show(ui.action("forget", {**data, "id": int(argument)}))
            elif command == "/research":
                if input("¿Consultar esta URL en GitHub? [s/N] ").lower() == "s":
                    show(ui.action("research", {**data, "url": argument, "authorized": True}))
            elif command.startswith("/"):
                print("Comando desconocido. Usa /help.")
            else:
                mode = ui.store.session(session)[1]
                remote = mode != "offline" and input("¿Autorizar envío de contexto al proveedor remoto? [s/N] ").lower() == "s"
                task = Task(threading.Event(), time.monotonic() + 240, test_permission(), remote)
                _run(ui, session, line, task)
        except EOFError:
            return
        except KeyboardInterrupt:
            print("\nOperación cancelada.")
        except (OSError, ValueError) as error:
            show(str(error))


def _run(ui, session, prompt, task):
    # El mismo flujo asíncrono que Studio evita bloquear Ctrl+C durante la red.
    data = {"session": session}
    ui.action("start", {**data, "prompt": prompt, "testing": task.testing, "remote": task.remote})
    proposals = set()
    last = None
    try:
        while True:
            status = ui.action("status", data)
            events = status["events"]
            current = events[-1] if events else None
            if current and current != last:
                show(current)
                last = current
            for change in reversed(ui.action("changes", data)):
                if change["state"] != "pending" or change["id"] in proposals:
                    continue
                proposals.add(change["id"])
                show(change["diff"])
                answer = input(f"¿Aplicar {change['path']}? [s/N] ").lower()
                show(ui.action("accept" if answer == "s" else "reject", {**data, "id": change["id"]}))
            if not status["active"]:
                break
            time.sleep(0.25)
    finally:
        ui.action("cancel", data)
