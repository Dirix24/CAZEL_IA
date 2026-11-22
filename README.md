# CAZEL IA

Una asistente portátil para robótica y código que **vive en un USB**. Analiza
proyectos localmente, puede leer repositorios públicos de GitHub cuando tú se lo
pides, investiga en Wikipedia con permiso y se conecta a robots serie compatibles.

Cerebro es su mente (el modelo hecho con NumPy) y las ideas de seguridad de
Arquitectura-Arus son su cuerpo (permisos, registro, límites).

## CAZEL Core 2

CAZEL Terminal y CAZEL Studio comparten proyectos, sesiones y cambios
reversibles. Ambos pueden conectarse a un modelo local o a un proveedor
remoto autorizado. Arranca con `CAZEL_TERMINAL` o `CAZEL_STUDIO` para tu
sistema. Consulta la [guía de uso y preparación USB](docs/CAZEL_2_USO.md)
para configurar el modelo, los permisos y los perfiles de pruebas.

Las secciones siguientes describen la interfaz clásica y la robótica.

## Cómo usarlo

1. Copia la carpeta `CAZEL_IA` entera al USB.
2. Necesitas **Python 3.9+** y **NumPy** en el ordenador (o corre `PREPARAR_USB`
   una vez con internet para guardar NumPy dentro del USB, en `libs/`).
3. Doble clic en:
   - Windows: `INICIAR.bat`
   - Linux: `INICIAR.sh` (o `INICIAR.desktop`)
   - Mac: `INICIAR.command`
4. Se abre tu navegador con la interfaz de CAZEL (solo accesible desde ese
   mismo equipo).

> Un USB **no puede arrancar programas solo** (los sistemas lo bloquean por
> seguridad): siempre hace falta ese doble clic.

## Menú de tres puntitos ⋮

- **Escanear placas y componentes**: lista puertos USB-serie y algunos VID/PID.
  La opción de autoconexión queda desactivada por defecto; al activarla, CAZEL
  consulta `AYUDA` y conecta solo los robots que hablan CAZEL-1. Los sensores
  deben ser anunciados por el firmware.
- **Analizar código y proyectos**: selecciona varios archivos para un informe
  heurístico offline sobre placas, dependencias, componentes, riesgos y mejoras
  sugeridas en Arduino/C/C++, Python, JavaScript/TypeScript, Java, Rust y configs.
- **Repositorio GitHub**: lee hasta 24 archivos de un repositorio público. No
  necesita token, no ejecuta ni modifica el código y no crea commits.
- **Adaptar sketch Arduino**: genera un adaptador CAZEL-1 a partir de un sketch;
  tú revisas los pines y cargas el código con el IDE.
- **Internet y biblioteca**: abrir/cerrar la puerta, buscar en Wikipedia,
  revisar la cuarentena y aprobar textos.
- **Espacio del USB**: barra de uso y qué se puede borrar. Las cachés se limpian
  automáticamente si falta espacio. Bajo 20 MB puede borrar conversaciones
  comprimidas muy antiguas, registros grandes y recuerdos
  triviales; se detiene al recuperar espacio y conserva nombre y recuerdos
  importantes. El resto requiere que lo marques y confirmes.
- **Diario y entrenamiento**: exporta conversaciones para que las revises antes
  de que Cerebro aprenda de ellas.
- **Apagar CAZEL**. El botón rojo **PARAR** corta al robot siempre.

## Seguridad (resumen)

- Servidor solo en `127.0.0.1`, con token de sesión, comprobación de Host y
  Origin, y CSP estricta. Se apaga solo tras 20 min sin uso.
- La puerta de investigación de Wikipedia está **cerrada por defecto**. Se abre
  por tiempo (máx. 60 min), solo a `es.wikipedia.org` y `en.wikipedia.org`, con
  tope de 20 peticiones. Por separado, la acción de GitHub consulta únicamente
  `api.github.com` después de que pegues una URL pública; lee hasta 24 archivos
  fuente y no ejecuta, guarda, modifica ni sube el contenido.
- Escribe únicamente dentro de `datos/`. Protegidos del borrado: modelo,
  memoria, biblioteca, robots y ajustes.
- Robots: las órdenes se construyen solo desde el perfil validado (nunca texto
  libre), con rangos, límite de ritmo y `PARAR` siempre disponible; se envía
  `PARAR` al desconectar o apagar.

## Protocolo CAZEL-1 (para tu robot)

El robot habla por serie, una línea por mensaje:

```
AYUDA            ->  CAZEL 1 mirobot
                     ORDEN avanzar cm:0:50
                     ORDEN girar grados:-180:180
                     LECTURA distancia cm
                     FIN
avanzar 10       ->  OK        (o ERR motivo)
LEER distancia   ->  VAL 42
PARAR            ->  OK
```

En `ejemplos/` hay un sketch de ejemplo y el adaptador que genera CAZEL.

## Qué puede hacer Cerebro y qué no

Cerebro es el modelo de lenguaje pequeño que viene incluido en el proyecto (aprox. 190 mil parámetros). El chat, la memoria y las nuevas funciones trabajan sin instalar ni conectarse a otro modelo de IA. La interfaz usa análisis local por reglas para revisar código: encuentra señales conocidas y propone mejoras concretas, pero no comprende cualquier programa como lo haría un programador experto.

Esta versión puede:

- Analizar varios archivos de Arduino/C/C++, Python, JavaScript/TypeScript, Java y Rust, listar dependencias y funciones, identificar algunos patrones de riesgo y sugerir correcciones conocidas.
- Leer hasta 24 archivos fuente de un repositorio **público** de GitHub. La lectura es de solo consulta: no cambia archivos, no sube commits y no accede a repositorios privados.
- Identificar algunos modelos de placa por su identificador USB. Si una placa responde al protocolo CAZEL-1, puede anunciar órdenes y sensores y CAZEL puede conectarse a ella.
- Buscar y guardar información de Wikipedia cuando abres la puerta de internet. La memoria y los datos quedan en `datos/` dentro del USB.

### Placas, sensores y cambios de código

No existe un método único para detectar o controlar todas las placas programables: cada familia usa puertos, controladores, pines y protocolos distintos. El escaneo puede reconocer algunos identificadores USB, pero solo conecta robots que tengan firmware compatible con CAZEL-1. Los sensores deben estar conectados a la placa y el firmware debe comunicarlos. Para otra placa hace falta crear y revisar un adaptador compatible; CAZEL no lo instala ni lo carga automáticamente.

El análisis de proyectos ofrece recomendaciones basadas en patrones conocidos. No compila, no ejecuta y no modifica tus archivos o repositorios. Revisa y prueba las sugerencias antes de usarlas en un robot.

### Uso desde un USB de 7 GB

El proyecto cabe holgadamente en un USB de 7 GB. Para arrancar, cada ordenador necesita Python 3.9 o superior y NumPy, salvo que prepares una carpeta `libs/` con `PREPARAR_USB` en ese mismo sistema. Las bibliotecas de Python pueden depender del sistema operativo y de su versión: preparar el USB en Linux no garantiza que funcione sin preparación en Windows o macOS. En todos los casos hay que abrir el lanzador del sistema con doble clic; un USB no puede ejecutar programas automáticamente al conectarse.

Si el espacio escasea, CAZEL limpia cachés regenerables. Por debajo de 20 MB libres, también puede eliminar registros grandes, conversaciones comprimidas muy antiguas y recuerdos de importancia mínima. Conserva el modelo, la biblioteca aprobada, los perfiles de robots, los ajustes y los recuerdos importantes. Puedes desactivar el olvido automático de recuerdos en `datos/ajustes.json`.

### Cómo ampliar el conocimiento de Cerebro

Puedes añadir diálogos revisados a `cerebro/data/corpus/` y entrenar el modelo ejecutando `python3 train.py` desde la carpeta `cerebro/`. Los ejemplos pueden mejorar respuestas sobre esos temas, pero este Cerebro pequeño no se convierte por ello en un modelo universal. Conserva una copia de seguridad y revisa las métricas del entrenamiento.

## Pruebas

```
python3 -m unittest discover -s tests
```

## Estructura

```
cazel/       código de CAZEL (núcleo, puerta, biblioteca, espacio, robot, web)
cerebro/     el modelo y agente Cerebro
datos/       TODO lo que CAZEL escribe (memoria, diario, cuarentena, ...)
ejemplos/    sketch y adaptador de ejemplo
tests/       pruebas
```

## Licencia

El código original de CAZEL IA y Cerebro se distribuye bajo la [licencia MIT](LICENSE).
El contenido de terceros, incluidos los textos consultados en Wikipedia, conserva
la licencia y la atribución de su fuente.

## Integración local con CEREBRO

`python3 -m cazel.especialista --proyecto RUTA` recibe JSON v1 por entrada
estándar. Ofrece inventario técnico y análisis sintáctico del proyecto
seleccionado. La ejecución de pruebas requiere `--permitir-pruebas` y
usa el perfil aislado de CAZEL. Para editar u operar hardware se usan
las interfaces existentes y sus flujos de aprobación.

Con `--permitir-propuestas`, la acción v1 `proponer` llama al modelo
local configurado y deja los cambios pendientes en una sesión de Studio.
La respuesta incluye el identificador de sesión y las rutas propuestas.
`--datos` selecciona la misma carpeta de ajustes y sesiones que Studio.
