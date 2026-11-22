# Aceptación de CAZEL 2

Resultados del 22 de noviembre de 2026 para la [PR #2](https://github.com/Dirix24/CAZEL_IA/pull/2).

| Verificación | Resultado y evidencia |
| --- | --- |
| Modelo local real | Linux x86_64, CPU de 3 hilos, Qwen2.5-Coder-1.5B-Instruct Q4_K_M servido por llama-cpp-python 0.3.9. Creó la calculadora y sus pruebas. Tras una inyección controlada y una petición de seguimiento, corrigió el fallo y pasaron las cuatro pruebas. |
| Repetición local | Otro proyecto vacío produjo los mismos dos archivos. Tras la inyección, la suma devolvió `-1 != 3` (código 1); el diff del modelo corrigió la suma, conservó las pruebas y los cuatro casos pasaron (código 0). Se bloqueó la red externa en el proceso de CAZEL durante la reparación. La traza de ambas fases solo registró loopback. |
| Bloqueo externo durante todo el ensayo | Un tercer proyecto vacío ejecutó la creación y la reparación con el hook activo. La fase de creación llegó a cuatro pruebas correctas aunque agotó la respuesta posterior del servidor. Tras inyectar el defecto, un reintento guiado conservó las pruebas, corrigió la suma y obtuvo `verified` con los cuatro casos correctos. |
| Alternativa automática | Se configuró un destino HTTPS de control en loopback con el puerto cerrado. La traza registró el intento a ese puerto y después la petición al servidor local real. El router devolvió modo `offline` y el modelo respondió `{"respuesta": 7}`. |
| Proveedor remoto real | Pendiente. El entorno carecía de una URL de proveedor y credenciales habilitadas para esta prueba. |
| Bubblewrap | Ubuntu 22.04 e intérprete del sistema. La prueba verificó bloqueo de lectura de un archivo del host, acceso al puerto del host, límite de tiempo y cancelación. [Ejecución en GitHub Actions](https://github.com/Dirix24/CAZEL_IA/actions/runs/45011329074). |
| USB Linux | Linux x86_64, CPython y dependencias incluidos. El verificador arrancó Studio, guardó un cambio y una lección, cerró Studio y abrió la misma sesión desde Terminal. |
| USB Windows | Windows AMD64 y CPython embebido 3.12.10. El verificador invocó el intérprete incluido con un PATH reducido a System32, y verificó ambos modos y la persistencia. La verificación se ejecutó en un runner nativo y usó el Python embebido del paquete. [Ejecución en GitHub Actions](https://github.com/Dirix24/CAZEL_IA/actions/runs/45011329065). |
| Robótica física | Pendiente. El entorno carecía de un dispositivo CAZEL-1 y de puertos USB serie expuestos. La suite Linux ejecutó el transporte con pseudoterminal y verificó que se emite `PARAR` mientras una tarea simulada del agente sigue activa. |
| Regresión general | Linux contabilizó 99 pruebas con una omisión local de Bubblewrap, que se ejecutó en el job nativo dedicado de Ubuntu. |
| Studio | Chromium verificó previsualización y rechazo de parches, guardado y recuperación de una lección tras recargar, ejecución de pruebas, deshacer y diseño móvil. |

## Calculadora con un modelo real

CAZEL recibió el enunciado de aceptación desde un directorio vacío. Generó
`calculator.py` y `test_calculator.py`. Un primer ensayo se agotó porque
el modelo confundía el nombre de la herramienta con el perfil. Otro
ensayo creó solo el programa y terminó con código 5 y cero pruebas.
Se mejoraron los ejemplos de invocación y el resultado que se muestra
cuando el modelo afirma que las pruebas pasaron sin evidencia.

Tras obtener cuatro pruebas correctas, el operador introdujo
deliberadamente una resta en la suma. La prueba real devolvió
`AssertionError: -1 != 5` y código 1. Un intento del modelo sustituyó
el archivo por una aserción. Se deshizo ese cambio. Con fragmentos
acotados de los archivos y una petición de seguimiento para conservar
las cuatro operaciones y las pruebas, el modelo propuso la modificación
siguiente:

```diff
--- a/calculator.py
+++ b/calculator.py
@@ -1,6 +1,6 @@
 class Calculator:
     def add(self, a, b):
-        return a - b
+        return a + b

     def subtract(self, a, b):
         return a - b
```

Después de aceptarla, el modelo volvió a invocar la ejecución. Pasaron
las cuatro pruebas, con código 0, y la tarea quedó como `verified`.
El operador introdujo el defecto, aprobó cambios y guio el reintento.
La creación de archivos, la corrección final y las llamadas de pruebas
procedieron del modelo.

## Aprender durante el trabajo

En Terminal usa `/learn Python | Escribe nombres descriptivos para los contadores`,
`/lessons` y `/forget ID`. En Studio usa **Aprender de mis correcciones**.
Las lecciones se guardan por proyecto y lenguaje en SQLite y se pueden
recuperar desde otra sesión. Las tareas locales aportan hasta cinco
lecciones como contexto y priorizan las relacionadas con los lenguajes
detectados o mencionados. Las tareas que pueden llamar a un proveedor
remoto omiten estas lecciones y el historial previo de la sesión. El aprendizaje añade contexto al modelo
existente y deja intactos sus pesos.

Studio también permite pegar un parche unificado y revisar el diff antes
de aplicar. CAZEL valida que la ruta del parche coincide con el archivo
seleccionado y admite parches con saltos LF sobre archivos CRLF.

## Red durante la repetición

En la tercera ejecución, la creación y la reparación aplicaron un hook de auditoría de Python que
rechaza `socket.connect` y `socket.sendto` a destinos fuera de loopback.
Una sonda hacia una dirección externa reservada devolvió
`PermissionError`. `strace -f -e trace=connect` registró únicamente
`127.0.0.1` para CAZEL y los procesos de pruebas. El modelo se sirvió
desde los pesos locales y escuchó solo en loopback. La restricción
del ensayo se aplicó al proceso de CAZEL y el host conservó su red.
La separación de red a nivel de espacio de nombres se verificó por
separado con Bubblewrap en GitHub Actions.

## Repetir las verificaciones

```sh
python3 -m unittest discover -s tests
python3 herramientas/verificar_usb.py /ruta/al/paquete
CAZEL_REQUIRE_BWRAP=1 /usr/bin/python3 -m unittest discover -s tests -p test_core2_isolation.py -v
```

## Comprobar un proveedor remoto autorizado

Configura el proveedor y su variable de entorno según la guía de uso.
El verificador envía una suma sintética. No abre proyectos ni lee sus
archivos, sesiones o lecciones.

```sh
python3 herramientas/verificar_proveedor.py datos/core2-modelos.json --autorizar-envio
```

Para el ensayo físico, conecta un dispositivo CAZEL-1 en un banco de
pruebas seguro. Verifica su detección y su perfil desde la interfaz
clásica. Comprueba el rechazo de una orden fuera del rango anunciado
y acciona la parada de emergencia mientras Studio ejecuta una tarea
de programación. Registra la respuesta del dispositivo y si la tarea
seguía activa al enviar `PARAR`.
