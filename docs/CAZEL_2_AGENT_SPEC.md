# CAZEL 2 — Especificación del agente programador

Estado: diseño inicial; no equivale a una implementación probada.

## Objetivo
CAZEL es un asistente portátil centrado en **programación y análisis de código**. Debe explorar proyectos, explicar arquitectura, localizar errores, proponer parches, editar archivos autorizados, ejecutar pruebas y reportar resultados verificables. Investigación en Internet solo bajo solicitud o autorización explícita.

## Principios
1. **Offline auténtico:** motor local compatible con API de chat (llama.cpp / Ollama / LM Studio), modelo descargado previamente; ninguna operación básica de programación requiere red.
2. **Online opcional:** proveedor remoto configurable con credenciales fuera del repositorio; no enviar archivos o secretos sin permiso.
3. **Un agente inicial:** ciclo observar → planificar → ejecutar herramienta → comprobar → informar, con límites de iteraciones y tiempo.
4. **Herramientas estructuradas:** las decisiones del modelo se validan por esquema antes de ejecutarse; nunca interpretar una respuesta de texto como comando shell implícito.
5. **Cambios reversibles:** previsualización de diffs, copia de seguridad o Git checkpoint y posibilidad de deshacer.
6. **Evidencia:** distinguir “generado”, “revisado”, “probado” y “no comprobado”; nunca inventar resultados.
7. **Portabilidad:** datos y modelos en rutas relativas al USB; binarios separados por SO y arquitectura; no asumir dependencias preinstaladas.

## Herramientas mínimas (MVP)
- `list_files(root, glob)`: listado limitado al workspace autorizado.
- `read_file(path, start, end)`: lectura con límite de bytes, excluyendo secretos por defecto.
- `search_code(query, glob)`: búsqueda de texto/símbolos con límite de resultados.
- `apply_patch(diff)`: valida rutas, muestra diff, crea checkpoint y aplica solo dentro del workspace.
- `run_tests(command_id)`: comandos permitidos y predefinidos, límites de tiempo/CPU/salida; no shell arbitrario por defecto.
- `git_diff()`, `git_status()`, `undo_checkpoint(id)`.
- `research_web(query)`: solo cuando el usuario lo solicita; dominios, tamaño y tiempo limitados; contenido externo tratado como no confiable.

## Política de permisos
- Lectura: proyectos seleccionados explícitamente por el usuario.
- Escritura: solo dentro del proyecto seleccionado, con previsualización y autorización configurable por sesión.
- Pruebas: comandos aprobados, aislados cuando el sistema lo permita.
- Confirmación individual obligatoria: borrado irreversible, acceso fuera del workspace, instalación de software, comandos arbitrarios, publicación en red, Git push, credenciales y control de robots.
- STOP de robótica independiente de la ejecución del agente.

## Arquitectura propuesta
- `core/orchestrator.py`: estado y presupuesto de pasos.
- `core/model_router.py`: local/remoto, timeout, fallos y fallback.
- `coding/context_builder.py`: selección de archivos relevantes.
- `coding/tool_registry.py`: esquemas y validación de herramientas.
- `coding/patch_manager.py`: checkpoints y aplicación atómica.
- `coding/test_runner.py`: ejecución controlada y registro.
- `security/permissions.py`: autorización por acción y proyecto.
- `memory/session_store.py`: SQLite, decisiones y resultados comprobados.
- `web/`: interfaz actual extendida con editor, diffs, pruebas y permisos.
- Mantener módulos existentes de robótica y Cerebro sin romper sus contratos.

## Primera prueba de aceptación
1. En un proyecto temporal vacío, pedir “crea una calculadora en Python con pruebas”.
2. Verificar archivos realmente creados y diff visible.
3. Ejecutar pruebas con salida y código de retorno capturados.
4. Introducir un error controlado, pedir su corrección y repetir pruebas.
5. Desconectar Internet y repetir la tarea usando modelo local.
6. Comprobar que un intento de editar fuera del workspace es bloqueado.
7. Comprobar que el historial permite deshacer.

## Próximos pasos de implementación
1. Inspeccionar las interfaces reales de `cazel/nucleo.py`, `cazel/servidor.py`, `cazel/seguridad.py` y los tests.
2. Crear pruebas de permisos/rutas y una capa de herramientas sin dependencias de modelos.
3. Integrar el agente con el adaptador `motor_externo.py` existente.
4. Probar con un modelo real y registrar resultados.
5. Empaquetar y validar en Windows/Linux; macOS después.

No se declara ninguna funcionalidad nueva como operativa hasta superar sus pruebas.
