# Informe MCP de contexto e historial

## Contrato expuesto

`get_ticket_context(ticket_id, event_limit=20)` conserva el estado actual completo del ticket, relaciones, evidencia y perfiles, pero limita el historial incluido a los eventos más recientes. `event_limit` es un entero estricto entre 1 y 100. La respuesta incorpora `events_page` con `total`, `count`, `limit` y `next_before_id`.

La nueva herramienta de sólo lectura `list_ticket_events(ticket_id, limit=20, before_id=None)` pagina exclusivamente el historial del ticket indicado en orden de ID descendente. El cursor `before_id` es exclusivo, estricto y está limitado a 1..2^63-1. La respuesta devuelve `ticket_id`, `events`, `total`, `count`, `limit`, `before_id` y `next_before_id`. Los errores de dominio, incluido un ticket inexistente, se convierten en errores MCP sin filtrar excepciones internas.

Las instrucciones del servidor y de ambas herramientas explican que un `next_before_id` no nulo indica historia anterior, que sólo debe pedirse si hace falta, y que una página acotada no demuestra ausencia. El historial no sustituye al estado vigente: se usa la revisión del contexto actual o de una mutación correcta, y se relee tras un conflicto o antes de actuar sobre valores conocidos sólo mediante páginas históricas. No se fuerzan lecturas redundantes después de cada acción correcta. No se añadió un límite artificial por bytes ni se exige cargar todo el historial.

## Pruebas

`tests/test_mcp_history.py` usa el cliente y servidor stdio reales del SDK. Genera más de 50 eventos del ticket objetivo intercalados con otros 50 de otro ticket, comprueba que el contexto contiene el título y la revisión actuales junto con la primera página, y recorre cursores de 13 eventos hasta reconstruir exactamente todo el historial objetivo, sin duplicados ni IDs cruzados.

La misma prueba verifica descubrimiento y anotación `readOnly`, valores predeterminados, metadatos de página, tipos estrictos, límites, cursores inválidos y tickets desconocidos. Sólo usa SQLite temporal; no inicia proveedor, inferencia, navegador ni red.

`py_compile` terminó correctamente. La ejecución stdio iniciada dentro del sandbox local quedó detenida durante el arranque del subproceso y se interrumpió sin elevar permisos. El integrador ejecutó después el caso SDK normal en su entorno: **1 prueba correcta en 2,807 s**. Esta es la evidencia funcional del paquete.
