# AR-0016 · Ampliación de aceptación activa

La reproducción previa de Astra está en `.agentrelay/acceptance-extension-repro.json`: al añadir un criterio válido en `in_progress`, `_update_ticket` sustituía el diccionario `before` por un `set`; la auditoría producía `TypeError` y la transacción retrocedía. Astra confirmó además en `.agentrelay/blocked-acceptance-repro.json` que un ticket `blocked` con propietario permitía quitar criterios.

El conjunto de criterios previos ahora tiene variable propia, de modo que el evento `update_ticket` conserva valores `before` y `after`. La prohibición de debilitar aceptación se aplica a `in_progress`, `review` y `blocked` con propietario, los mismos estados cuya edición exige titularidad. La planificación en `queued`, `backlog` y `blocked` sin propietario conserva su capacidad de revisar criterios.

`tests/test_acceptance_updates.py` comprueba ampliaciones y auditoría en `in_progress`/`review`, rechazo de debilitación con rollback de datos y eventos, conflictos de revisión, titularidad, y aprobación independiente con los criterios ampliados. Cubre también `blocked` con propietario (rechazo y ampliación válida) y las tres situaciones de planificación.

Resultado propio: 3/3 pruebas nuevas y 14/14 pruebas existentes de `test_store.py` pasan con `.runtime/Scripts/python.exe`. El sandbox negó SQLite en el TEMP de Windows; dirigí `TEMP`/`TMP` sólo en los procesos de prueba a `.agentrelay`. `git diff --check` pasó. La batería integrada y la revisión final corresponden a Astra.
