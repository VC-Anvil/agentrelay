# Servicio de resumen multiproyecto

## Contrato

`project_overview(config_path, limit=5)` devuelve un documento con `schema_version`, proyecto predeterminado, número de proyectos, límite aplicado y una entrada por workspace. Cada entrada conserva identidad, nombre, ruta legible, marcador demo y las estadísticas de `Store.state()`.

`urgent_open` es el total de tickets urgentes cuyo estado no es `done` ni `cancelled`. `ready`, `review` y `blocked` contienen `total` y una muestra `tickets` de hasta `limit` elementos. `blocked` incluye bloqueos explícitos y tickets `queued` con bloqueadores derivados. `review` describe el estado de entrega; no afirma que el ticket sea aprobable.

Las muestras se ordenan por prioridad, fecha de creación e ID. Cada ticket expone sólo `id`, `title`, `type`, `status`, `priority`, `parent_id`, `profile_id`, `assignee`, `revision`, `ready` y `blockers`. No incluye descripción, aceptación, checkpoint, evidencia, auditoría, ejecuciones ni configuración de workers.

El límite se valida como entero estricto entre 1 y 20 antes de abrir el registro. El servicio llama una sola vez a `Store.state()` por proyecto; el marcador demo sale de ese mismo estado. El resultado no representa un snapshot transaccional entre bases distintas y no promete optimización SQL ni ahorro de tokens.

## Workers y compatibilidad

`load_workspaces(config_path, enable_execution=True)` conserva por defecto el comportamiento de servidor existente. Con `enable_execution=False` valida el registro y cada base y construye sus `Store`, pero no importa ni construye `ExecutionManager` y no abre los archivos de configuración de workers. Resolver el nombre configurado no recupera ejecuciones ni lanza procesos.

Las bases reconocidas siguen pasando por el constructor normal de `Store`; sus migraciones idempotentes permanecen activas. La consulta no crea bases por rutas erróneas. Tampoco crea `execution_runs` ni altera tickets, perfiles, auditoría o ejecuciones existentes.

## Pruebas

`tests/test_project_overview.py` prepara dos bases con IDs de ticket repetidos y estados listos, en revisión, bloqueados explícitamente y bloqueados por dependencia. Comprueba:

- totales completos frente a muestras truncadas y orden estable;
- urgentes abiertos, estadísticas y marcador demo por proyecto;
- campos exactos del documento y ausencia de datos detallados o rutas de workers;
- una llamada a `Store.state()` por proyecto y aislamiento pese a IDs repetidos;
- workers configurados con archivos inexistentes y un `ExecutionManager` que falla si se invoca;
- tickets, perfiles, eventos y runs idénticos antes y después, sin crear `execution_runs`;
- límite estricto validado antes de cargar el registro;
- registros o bases ausentes, IDs repetidos y rutas de base duplicadas rechazados sin crear la ruta ausente.

El módulo nuevo terminó con **3/3 pruebas correctas en 9,633 s**. Las dos regresiones existentes que comprueban validación del registro y activación/limpieza normal de ejecución terminaron **2/2 correctas en 4,430 s**. El sandbox de Windows no permitía usar su `%TEMP%`, por lo que las pruebas apuntaron `TEMP` y `TMP` sólo para esos comandos a un directorio privado dentro del workspace. No se ejecutaron workers, proveedor, navegador ni red.
