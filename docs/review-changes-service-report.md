# AR-0039 — devolución de una entrega para corrección

## Cambio

`Store.action("request_changes", {"id", "expected_revision", "reason"}, actor)` permite a un revisor distinto del autor devolver exclusivamente un ticket en `review` a `queued`. Valida las tres claves exactas, `id` como cadena no vacía, revisión positiva entera sin `bool`, razón no vacía de hasta 4000 caracteres tras quitar espacios exteriores y actor de hasta 128. El control de identidad usa `_actor_identity`, igual que `complete_ticket`; ni `author` ni `agent:author` pueden revisar una entrega asignada a `author`, y un humano no puede revisar su propia entrega humana. El CAS y la escritura ocurren bajo `BEGIN IMMEDIATE`.

La transición limpia `assignee` y `blocked_reason`, incrementa la revisión y conserva checkpoint, evidencia, criterios, descripción, prioridad, perfil, relaciones y modelo/esfuerzo declarados. Un evento `request_changes` registra razón, responsable anterior y revisiones de entrega y devolución. El reintento con revisión antigua da conflicto; no hay idempotencia por identificador ni aceptación automática. La disponibilidad futura sigue calculándose con el grafo de dependencias e hijos vigente.

`Store.context` añade `review_feedback`: proyección del último evento de devolución, consultada dentro de la misma transacción aunque se solicite `event_limit=1`. Los indicadores `submission_after_request` y `completion_after_request` sólo denotan eventos posteriores; no demuestran que se corrigiera el defecto ni que la evidencia fuera auténtica. La instrucción de contexto hace explícita esa diferencia. `state` y `export` conservan sus formas de ticket; el historial completo sigue en `events` y en el backup SQLite.

## Comprobación

Preparadas seis pruebas funcionales en `tests/test_review_changes.py`: preservación y bloqueadores, identidad y alias, datos y estados inválidos, dos revisores concurrentes, proyección con más de 20 comentarios y ciclos de entrega/corrección/aceptación, y backup. Una ejecución local con `.runtime/Scripts/python.exe -m unittest tests.test_review_changes -v` quedó bloqueada **antes de cualquier aserción**: `sqlite3.OperationalError: unable to open database file` al crear la fixture en el TEMP virtual del sandbox, acompañado de `WinError 5` al limpiar. No se atribuye a una falla del código ni se cuenta como prueba pasada. La raíz ejecutó seis pruebas de servicio y una fixture de trabajador real: **7/7** correctas en 1,207 s (`.agentrelay/v016-service-tests.log`). Tras añadir la validación explícita de `id`, volvió a ejecutar servicio, MCP y CLI: **8/8** correctas en 3,003 s (`.agentrelay/v016-focused-final.log`). Son resultados de la raíz, no de este especialista. El análisis sintáctico de los dos archivos Python con `.runtime/Scripts/python.exe -B` pasó (`AST OK`); esto no sustituye las pruebas funcionales.

## Límites

La proyección deriva de auditoría local y no verifica el contenido de la corrección. Una devolución deja el artefacto original intacto y no ejecuta trabajador alguno. La solución no autentica identidades más allá del `actor` que entrega la capa llamante; esa capa debe vincularlo al usuario real. No se modificaron bases de desarrollo ni archivos de juegos. Identidad exacta de modelo/esfuerzo de este especialista: desconocida en el host.
