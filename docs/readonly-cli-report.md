# CLI de consulta sobre bases existentes

## Defecto reproducido

Antes del cambio ejecuté `context`, `history`, `export` y `backup` en fixtures aislados. Cada comando creó el directorio padre y una base SQLite AgentRelay de 53.248 bytes cuando `--db` contenía una ruta inexistente. Los cuatro también migraron una SQLite ajena que sólo tenía una tabla `sentinel`: su hash cambió y aparecieron las tablas de AgentRelay. `backup` creó además el archivo de salida en ambos escenarios.

La primera corrección aún aceptaba una SQLite camuflada que tenía los cinco nombres de tabla esperados, pero sólo una columna `bogus` en cada una. La reproducción adicional mostró que los cuatro comandos cambiaban su hash, añadían `plan_requests` y acababan con un error de SQLite al insertar perfiles. Esa segunda reproducción también forma parte de la captura privada.

La captura estructurada previa al arreglo está en `.agentrelay/readonly-cli-repro.json`; los archivos de reproducción quedaron confinados bajo `.agentrelay/readonly-cli-repro.*`. No se usaron bases externas al fixture.

## Corrección

`workspaces.require_agentrelay_database()` centraliza la comprobación que ya protegía el registro multiproyecto. Resuelve la ruta explícita, exige un archivo existente, lo abre mediante URI SQLite con `mode=ro` y comprueba que las cinco entidades originales sean tablas reales en `sqlite_master`, además de exigir sus columnas originales, antes de construir `Store`. Las columnas se comprueban como subconjunto para admitir ampliaciones posteriores; no se exigen `plan_requests` ni otras tablas añadidas después de la primera versión. Vistas con nombres y columnas coincidentes no se aceptan como tablas.

Los comandos `context`, `history`, `export` y `backup` llaman ahora esa comprobación antes de crear directorios o instanciar `Store`. Una ruta ausente, un archivo vacío o corrupto y una SQLite ajena terminan con diagnóstico y no crean la base, su padre ni la salida del backup. El registro de workspaces reutiliza la misma función, evitando dos heurísticas distintas.

`action`, `serve`, `mcp` y `run` conservan el camino anterior que crea el directorio y permite inicializar una base cuando el operador lo solicita. La comprobación previa no elimina las migraciones idempotentes que `Store` pueda aplicar después a una base AgentRelay reconocida, ni pretende cerrar una carrera TOCTOU hostil entre la comprobación y la apertura posterior.

## Pruebas

`tests/test_cli_readonly.py` ejecuta los cuatro comandos como subprocesos y comprueba:

- rutas inexistentes sin creación del padre, base o salida;
- archivos vacíos, corruptos y SQLite ajenas sin cambio de bytes;
- esquema `sentinel` ajeno, esquema camuflado con columnas incompatibles y vistas que imitan las entidades intactos para los cuatro comandos, sin copia de backup;
- base con el esquema original, sin `plan_requests`, reconocida y migrada correctamente por `Store`;
- contexto, historial, exportación y backup correctos sobre una base AgentRelay válida;
- `action` aún inicializa una ruta explícita nueva.

El pase final de las cinco pruebas nuevas y la prueba de registro compartido terminó con **6/6 correctas en 18,292 s**. Incluye el rechazo de vistas con nombres y columnas coincidentes. El `%TEMP%` normal del sandbox negó escritura, por lo que ese pase usó `TEMP` y `TMP` apuntados sólo para el comando a `.agentrelay/readonly-cli-test-tmp`, dentro del workspace.

El primer pase local de regresión `tests.test_cli tests.test_workspaces` produjo seis pruebas correctas y dos bloqueos ambientales: el sandbox negó acceso a un fixture de snapshot y rechazó el socket local del test HTTP con WinError 10013. No se solicitó elevación ni se reinterpretaron esos dos bloqueos como pruebas funcionales correctas. El integrador repitió después las pruebas nuevas junto con `deep_graph`, CLI y workspaces en un entorno normal: **15/15 correctas en 7,252 s** antes del refuerzo de columnas. El pase dirigido final anterior acredita el caso camuflado y la compatibilidad legacy añadidos tras esa revisión.

El integrador comprobó además `context`, `history` y `export` sobre los cuatro pilotos reales: 33 tickets y 34 eventos de los tickets consultados, sin cambios en tickets, perfiles ni eventos. Esta comprobación acredita compatibilidad de lectura en esas bases; no sustituye las pruebas aisladas de rechazo ni incluye `backup`.

La identidad por estructura reduce falsos positivos accidentales; no autentica archivos deliberadamente hostiles ni elimina una carrera TOCTOU entre validación y apertura. `Store` conserva la responsabilidad de sus migraciones idempotentes después de reconocer la base.
