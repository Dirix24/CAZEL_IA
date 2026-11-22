# CAZEL 2 · ejecución y preparación USB

## Inicio

En Linux ejecuta `./CAZEL_TERMINAL.sh` o `./CAZEL_STUDIO.sh`. En Windows usa
`CAZEL_TERMINAL.bat` o `CAZEL_STUDIO.bat`. Los lanzadores buscan primero Python
en `python_portatil/`. También puedes ejecutar `python iniciar.py --interfaz
terminal` o `python iniciar.py --interfaz studio`. El arranque interactivo
general ofrece ambos modos y la interfaz clásica. Studio enlaza desde su
cabecera a la interfaz clásica, incluida la parada de emergencia.

Abre una carpeta con `/project ruta` en Terminal o **Abrir** en Studio. Las
rutas relativas se resuelven desde la raíz de CAZEL. Usa `/project` para listar
sesiones y `/session ID` para recuperarlas. Studio las muestra en un selector.
Los proyectos dentro de la distribución conservan sus rutas relativas al
trasladar el USB. Los externos requieren la misma ruta o una nueva sesión.

Selecciona el modo de modelo y envía una petición. Cada edición se presenta
como diff antes de escribirla. Los cambios rechazados permanecen en el
historial. Si deshaces una edición que creó un archivo, se quita ese archivo
si conserva el contenido aprobado. Si una operación se interrumpe, reintenta
la acción a partir del mismo cambio. Si el archivo cambió por fuera, conserva
su contenido y prepara un nuevo diff.

## Modelo local

Arranca Ollama, llama.cpp `llama-server` o LM Studio con un modelo de código
previamente descargado y un endpoint compatible con chat de OpenAI. Los
servidores y modelos se preparan aparte. Guarda pesos GGUF en `modelos/` si
el servidor acepta ese formato. Ollama puede utilizar su propio almacén.

En `datos/ajustes.json` configura, por ejemplo:

```json
{
  "motor_externo": {
    "activo": true,
    "host": "http://127.0.0.1:11434/v1",
    "modelo": "nombre-del-modelo-disponible"
  }
}
```

Ajusta el puerto y el nombre al servidor instalado. El agente requiere un
modelo que siga instrucciones y produzca objetos JSON. Empieza con un modelo
de código instruct cuantizado que quepa en RAM o VRAM con espacio para el
contexto. Consulta su ficha antes de copiar pesos al USB. Cerebro sigue
disponible en el modo clásico.

## Proveedor remoto

Crea `datos/core2-modelos.json` con la URL base HTTPS de una API compatible
y el nombre de una variable de entorno que contenga la clave:

```json
{
  "host": "https://api.openai.com/v1",
  "modelo": "nombre-del-modelo-habilitado",
  "clave_env": "CAZEL_API_KEY"
}
```

Exporta esa variable fuera del proyecto. En modo online debes autorizar el
envío de petición y contexto para cada tarea. Automático usa el remoto
autorizado cuando responde, y prueba el local ante un fallo. Offline usa
únicamente la conexión por loopback. La investigación de GitHub es una acción
separada y requiere aprobar la URL. Wikipedia sigue en la interfaz clásica.

## Ejecución de pruebas

Core 2 admite el perfil `python-unittest`. La opción aislada usa Bubblewrap,
`prlimit` e intérprete de sistema Linux bajo `/usr`. Necesita que el host
permita espacios de nombres de usuario. Trabaja sobre una copia acotada de
archivos de texto visibles y sin red. Si falla el aislamiento, el agente
registra el fallo. Las pruebas que dependen de binarios, archivos ocultos,
servicios externos o escritura en el proyecto requieren otro entorno.

La opción de proyecto confiable ejecuta código de prueba con los permisos de
tu cuenta. Úsala exclusivamente con código revisado. Mantiene tiempo,
captura de salida y entorno reducido. En Linux aplica límites de recursos
si está disponible `prlimit`. En Windows la ejecución confiable termina
el proceso directo. Para ejecución no confiable usa una máquina virtual
aislada. Los resultados reflejan el proceso observado y el código de salida.

Los patrones de nombres bloquean archivos ocultos y nombres frecuentes de
credenciales. Revisa el contenido que autorizas para transmisión remota, ya
que las credenciales también pueden aparecer en archivos fuente ordinarios.
Evita ejecutar CAZEL con una cuenta privilegiada o sobre carpetas modificadas
en paralelo por software no confiable.

## Distribución sin Python instalado en destino

Prepara una distribución por combinación de sistema operativo, arquitectura y
versión de CPython. En Linux usa una distribución independiente de CPython
con `bin/python3` y elige una base compatible con la libc de destino.
En Windows usa el ZIP oficial embebible de CPython, con `python.exe` en la
raíz. Prepara con una Python de la misma versión y arquitectura:

```sh
python -m pip install --only-binary=:all: --target /ruta/a/libs numpy pyserial
python herramientas/empaquetar_usb.py --python-portatil /ruta/cpython \
    --libs /ruta/a/libs --salida /ruta/CAZEL
```

El ensamblador copia archivos rastreados de `HEAD`, Python y las ruedas.
Verifica dependencias y arranque de Terminal antes de entregar la carpeta.
Copia esa carpeta al USB junto con el servidor y los pesos que hayas elegido.
Haz una prueba en destino con Internet desconectado antes de distribuir. El
servidor del modelo, controladores y compatibilidad con la GPU dependen del
equipo. Arranca el modelo desde su propia instalación o binario portable.

## Cobertura y límites

- Python dispone de inspección AST, símbolos e imports. Los informes para
  otros lenguajes son heurísticos. El editor usa resaltado léxico básico.
- Git compara archivos de texto visibles con su índice sin filtros de
  conversión. El diff y las restauraciones operan sobre checkpoints de CAZEL.
- El historial guarda peticiones, planes, acciones, resultados y cambios en
  SQLite. Conserva el archivo de memoria para trasladar las sesiones.
- Los parches unificados se tramitan por archivo. Los proyectos grandes se
  exploran mediante inventario acotado y lecturas parciales.
- Para la aceptación con IA real, pide la calculadora desde Terminal o Studio.
  Revisa las propuestas, comprueba un fallo por la operación deliberadamente
  incorrecta y confirma que las pruebas pasan después de aceptar su corrección.
  Repite desde un proyecto vacío con un modelo local y la red externa
  desconectada.
