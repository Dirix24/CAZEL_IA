# CAZEL IA — funciones ampliadas

## Analizar proyectos de varios lenguajes

Desde el menú **Analizar código y proyectos**, selecciona hasta 24 archivos. El análisis funciona offline y no ejecuta el código. Reconoce indicios de placas/plataformas (ESP32, ESP8266, Arduino AVR, RP2040/Pico, STM32, micro:bit, Raspberry Pi/Linux y ROS), componentes y buses habituales, dependencias e indicadores simples de riesgo. También lista funciones y líneas por archivo.

Es un análisis heurístico, no un compilador ni una comprensión universal. No corrige ni escribe los archivos automáticamente. Las nuevas sugerencias se producen con reglas explicables dentro de Cerebro y no requieren otro servicio de IA.

## Repositorios GitHub

El panel **Repositorio GitHub** admite direcciones `https://github.com/propietario/repositorio` de repositorios públicos. Con una acción explícita consulta la API pública, lee hasta 24 archivos fuente y 150 KB, y muestra un informe. No usa credenciales, no abre repositorios privados, no ejecuta el contenido, no escribe ni crea commits. La API anónima tiene límites de uso de GitHub.

El análisis es local y basado en reglas. Las recomendaciones no se aplican automáticamente; revisa y prueba cada cambio por tu cuenta.

## Escaneo de hardware

El escaneo serie no transmite datos al listar puertos y ahora añade el VID/PID USB y una identificación aproximada de algunas placas/puentes comunes. La autoconexión es una opción del usuario; envía `AYUDA` y conecta solo firmware CAZEL-1. Un sensor sin firmware que lo reporte no puede descubrirse de forma genérica desde el USB. Una placa cualquiera necesita un controlador y firmware compatibles; CAZEL no puede controlar automáticamente todo hardware del mercado.

## Cerebro incluido

El modelo NumPy original sigue siendo el único cerebro conversacional requerido. El análisis ampliado funciona sin motores de IA adicionales. El modelo tiene unos 190 mil parámetros: no se puede convertir en un experto universal solo con cambios de interfaz o reglas.

## Espacio y recuerdos

Con la limpieza automática habilitada, CAZEL elimina cachés regenerables cuando el almacenamiento entra en alerta. Si quedan menos de 20 MB, puede liberar en orden conversaciones comprimidas muy antiguas, registros grandes y recuerdos de importancia mínima; se detiene al recuperar el mínimo de espacio configurado. No selecciona recuerdos importantes, el nombre, categorías de usuario/robot/seguridad, el modelo, los ajustes, la biblioteca aprobada ni los perfiles de robots. Para desactivar el olvido automático, cambia `auto_olvidar_recuerdos_triviales` a `false` en `datos/ajustes.json`.
