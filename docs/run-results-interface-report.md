# Interfaces de consulta de propuestas por ejecución

## Implementación

El comando `run-result --db PATH --run ID` usa la validación existente de bases AgentRelay antes de construir `Store`, por lo que una ruta ausente o una SQLite ajena no se inicializa. Después delega exclusivamente en `agentrelay.run_results.get_run_result` y emite JSON UTF-8.

La herramienta MCP `get_run_result(run_id)` está marcada como sólo lectura, delega en el mismo helper y convierte `DomainError` según la convención de las demás consultas. Las instrucciones y el docstring presentan el resultado como propuesta histórica: tras un conflicto hay que recuperar contexto vigente y revisar pertinencia, sin replay automático.

Ninguna interfaz construye `ExecutionManager`, lanza workers, lee logs ni amplía el export masivo. Las migraciones normales de `Store` para bases reconocidas permanecen vigentes; no se afirma lectura de filesystem estrictamente inmutable. El run, su `claim_revision`/actor y la identidad mínima actual del ticket salen de una sola transacción SQLite consistente.

## Compatibilidad y límites

La columna de propuesta conserva sólo resultados futuros. Un run legacy devuelve `result: null`; lo mismo puede ocurrir en runs nuevos mientras aún no exista captura válida o si la cancelación, timeout, salida no cero, salida malformada o crash sucede primero. Un run todavía `running` puede contener propuesta en el intervalo entre captura y aplicación; estados cancelado, fallido, interrumpido o conflictivo también pueden conservarla si se capturó antes. No se intenta reconstruir salida desde resumen, error o logs. Los backups SQLite conservan las propuestas almacenadas. La consulta selecciona un run explícito y devuelve identidad mínima del ticket actual, sin contexto completo ni decisión automática sobre el contenido. Stdout tiene límite de 1 MiB y el JSON estricto normalizado un límite separado de 4 MiB ASCII.

## Pruebas

`tests/test_cli_run_results.py` usa dos tickets, dos propuestas distintas y un run legacy. Comprueba selección exacta, JSON UTF-8, campos públicos, `claim_revision`/actor, resultado legacy nulo, IDs vacíos o desconocidos, opción obligatoria, ruta inexistente y SQLite ajena. Compara tickets, perfiles, dependencias, eventos, metadata y runs antes y después. Terminó con **3/3 pruebas correctas en 5,922 s**.

`tests/test_mcp_run_results.py` usa el servidor y cliente stdio reales del SDK. Verifica descubrimiento `readOnly`, la misma propuesta Unicode, aislamiento frente a otro run, legacy nulo, tipos/IDs inválidos y dominio intacto. Mi ejecución local quedó esperando en el transporte stdio del sandbox después de que las tres pruebas CLI ya pasaran, y la interrumpí sin elevar permisos. El integrador ejecutó el módulo MCP en entorno normal: **1 prueba correcta en 1,751 s**. También ejecutó el test backend de recuperación: **1 prueba correcta en 0,676 s**.

Los fixtures insertan el esquema y `result_json` directamente; no construyen `ExecutionManager`, no lanzan workers y no leen logs. No se ejecutaron proveedor, navegador ni red.
