# Informe de la skill AgentRelay v0.5

## Cambio realizado

Se actualizó `skills/agentrelay-work/SKILL.md` sin añadir referencias ni scripts. La skill sigue siendo autocontenida y compatible con el wheel actual, que sólo empaqueta su `SKILL.md`; no hace falta ampliar la configuración de empaquetado.

La selección de trabajo conserva el ticket elegido por la persona y, cuando no hay elección, prioriza reanudar trabajo propio antes de tomar otro. Las consultas usan páginas pequeñas y filtros concretos, sin sondeo ni recorrido rutinario del catálogo. Se documentaron los filtros, límites, paginación, campos de resumen y respuesta reales de `list_tickets`; el detalle y el catálogo de perfiles se obtienen desde `get_ticket_context`.

El flujo de `create_plan` describe IDs de petición estables, estado `backlog` predeterminado, referencias locales adelantadas, reintento idéntico y conflicto al reutilizar un ID con otro actor o carga. También exige contexto fresco después del recibo. MCP es la vía preferida; `agentrelay action` queda como alternativa sólo si la herramienta, base y acción local ya están disponibles y autorizadas, sin instalación ni base implícita.

La comprobación opcional `compare-snapshot` requiere una raíz actual explícita. La skill diferencia códigos 0 (igual), 2 (cambio, ausencia o no comprobable) y 1 (snapshot o raíz inválidos), además del 2 de uso de `argparse` sin JSON. No convierte esta comprobación en requisito cuando el host o el alcance no la autorizan.

El MCP exige cadenas de modelo y esfuerzo, pero esos valores son hechos de ejecución. La skill usa los valores reales cuando el host los conoce y, para perfiles no Astra, declara `unknown` cuando el host no expone esa metadata, sin bloquear el trabajo ni pedir confirmación rutinaria. Esto no concede permisos adicionales ni convierte recomendaciones en disponibilidad. Astra mantiene una política vinculante: sólo se reclama desde un host conocido `gpt-6-astra` con esfuerzo `high`; valores desconocidos o incompatibles bloquean ese claim.

## Verificación

La revisión se contrastó con las firmas y respuestas vigentes en `agentrelay/mcp_server.py`, el comportamiento de `create_plan` y los códigos de `agentrelay/__main__.py`. No se ejecutaron servidor, navegador, proveedor, inferencia ni instalación global.

Se ejecutó `quick_validate.py` de `skill-creator` sobre `skills/agentrelay-work`: **Skill is valid!** Una comprobación AST independiente confirmó la firma `list_tickets(status, priority, profile_id, ready_only=False, assignee, limit=20, offset=0, include_details=False)` y `create_plan(request_id, tickets)`. `git diff --check` no encontró errores de espacios. La skill permanece en un único recurso para evitar una dependencia que el wheel actual no empaqueta.
