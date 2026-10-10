# Ejemplo reproducible de entrega y devolución

## Diagnóstico y alcance

Faltaba un ejemplo local copiable que mostrase el ciclo completo de ayuda, devolución para corrección y aceptación usando `Store` y `ExecutionManager`, sin depender de un proveedor, de un juego o de una base existente. `examples/handoff_demo.py` es un controlador fixture explícito; el mismo script tiene un modo privado de trabajador llamado por tres comandos Python fijos (`shell=False` en ExecutionManager). Sus textos están predefinidos y se etiquetan como **simulación**, nunca como inferencia o medición real.

La invocación pública es `python examples/handoff_demo.py --output NEW_DIRECTORY` tras una instalación editable. La ruta debe no existir y su padre debe existir. El script rechaza una ruta ya presente antes de crear o modificar archivos. La nueva carpeta contiene `workspace.sqlite`, `workers.json`, `backup.sqlite`, `report.md`, `result.json` y los diagnósticos de run que genere ExecutionManager; no usa la base por defecto. Cierra el manager aun si falla un paso y conserva todo lo ya escrito para inspección.

## Flujo y contrato de salida

Un perfil propio `fixture-python` / esfuerzo `none` es el recomendado y declarado por los tres workers. El controlador reclama un padre urgente como `agent:parent-owner` y solicita ayuda con una acción Store real. El hijo hereda prioridad urgente. Un worker entrega primero una cifra simulada «23» sin unidad; `agent:independent-reviewer` pide añadir «MHz» y explicitar que no es medición real. Otro run entrega la corrección; el controlador coteja el texto capturado con el esperado antes de que el revisor distinto del autor la acepte. El padre permanece bloqueado hasta que su dueño lo reencola explícitamente. El worker final inspecciona el hijo aceptado en `context.children`; el controlador coteja ID, unidad y límites del informe capturado antes de aceptar su resumen mediante el revisor fixture.

`result.json` registra `schema_version`, `simulation`, rutas absolutas, tickets y estados, tres IDs de run con estado y SHA-256 de los textos exactos capturados, además del motivo y actor de revisión. `report.md` resume el traspaso para una persona. Los tres informes íntegros están en `result_json` de los runs y en el backup SQLite; no se duplican como contexto completo en el JSON de salida. La comparación con el backup se hace antes de declarar éxito.

## Verificación

`tests/test_handoff_example.py` invoca el script como subprocess. Comprueba estados finales, herencia urgente, actores independientes, evento de devolución, flags históricos, dos entregas de ayuda, reencolado explícito del padre, informes exactos y sus hashes, igualdad de backup para tickets/perfiles/eventos/runs y rechazo de segunda invocación sin alterar bytes existentes. Otro caso exige error de uso sin `--output` y ausencia de estado por defecto.

El análisis sintáctico de ambos archivos pasó (`AST OK`) y no hubo errores de espacios en la revisión de diff. No ejecuté las fixtures SQLite en mi sandbox: en tareas previas este entorno denegó abrir bases bajo su TEMP virtual; el contrato encomienda esa corrida a la raíz. La raíz ejecutó `tests.test_handoff_example`: **2/2 correctas en 1,373 s** (`.agentrelay/handoff-example-tests.log`). Esa versión tenía una debilidad en la negativa sin `--output`: medía un directorio distinto del cwd del subprocess y podía pasar aunque se crease una base por defecto en el cwd real. Corregí la prueba para ejecutar desde la carpeta temporal que compara; la raíz repitió las dos pruebas finales: **2/2 correctas en 1,342 s** (`.agentrelay/handoff-example-tests-final.log`). También invocó el ejemplo directamente con salida nueva `.agentrelay/handoff-example-v0171`: terminó en 5,3 s, conservó `result.json` y `report.md`, y registró padre e hijo en `done`. Estas son ejecuciones de la raíz, no propias.

## Límites

Los workers no hacen llamadas a modelos, red, emuladores ni proyectos vecinos. La aceptación es una decisión explícita del revisor fixture sobre textos simulados; no valida un dato científico ni un juego. El modelo/esfuerzo `fixture-python`/`none` describe al worker Python configurado, no la identidad real de este especialista, que el host no expone. No se cambió el runtime de producto, la versión ni una base viva.
