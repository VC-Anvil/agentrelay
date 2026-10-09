# Informe del frontend de ejecución y espacios de trabajo

## Resultado multiproyecto

La interfaz inicia consultando `GET /api/workspaces` y muestra siempre un selector accesible de proyecto, incluso cuando el catálogo contiene uno solo. Cada opción combina el nombre y la base de datos comunicados por el servidor; no hay campos para introducir rutas ni IDs arbitrarios.

La selección inicial usa, por este orden, el ID guardado en `sessionStorage` para el origen actual si sigue en el catálogo y `default_workspace_id`. Un catálogo vacío, duplicado o mal formado produce un error visible. La compatibilidad con un servidor antiguo se activa únicamente si `/api/workspaces` devuelve `404`; otros fallos no se ocultan mediante un fallback.

Todas las operaciones específicas capturan el ID y la época del proyecto antes de empezar:

- `/api/state`, contexto, exportación y `/api/actions` reciben `X-AgentRelay-Workspace` en modo multiproyecto.
- El modo antiguo conserva las mismas llamadas sin esa cabecera.
- Las mutaciones capturan también la cabecera antes del primer `await` y deshabilitan el selector hasta finalizar.
- El estado general y el estado devuelto por cada acción se rechazan si identifican un proyecto distinto.
- Las respuestas tardías de estado, contexto, mutación o exportación se ignoran cuando su época ya no coincide.

Al cambiar de proyecto se cierran el drawer y los diálogos, se eliminan estado y contexto, se vacían las vistas y se reinician los filtros y formularios. Si existe una edición abierta se pide confirmación antes de descartarla. El cambio sólo carga estado; no lanza ejecutores ni acciones.

El nombre activo aparece en la cabecera y en el título del documento. La exportación conserva la cabecera capturada y genera un nombre como `agentrelay-nombre-proyecto-AAAA-MM-DD.json`.

## Ejecución local

La vista **Ejecuciones** sigue consumiendo el contrato opcional `state.execution`. Lista la configuración declarada de los ejecutores y las ejecuciones reales, sin afirmar conectividad, disponibilidad, consumo ni actividad inventada.

El drawer ofrece **Ejecución local** sólo para una tarea `queued`, `ready` y con criterios de aceptación. Filtra por `profile_ids`, mantiene la regla de Astra compatible y diferencia el modelo y esfuerzo configurados para ejecutar de la recomendación del perfil. `start_run` incluye la revisión visible; una ejecución activa puede cancelarse mediante `cancel_run`. El resultado enviado sigue pasando a revisión humana.

Cuando la ejecución está desactivada o no hay ejecutores compatibles, la interfaz explica el trabajo manual/MCP y la configuración necesaria sin simular agentes conectados.

## Seguridad de representación y persistencia

Los nombres de proyecto, bases de datos, tickets y datos de auditoría se insertan con `textContent` o propiedades de controles. No se usa `innerHTML`. La selección persiste sólo en `sessionStorage`; no se guarda ningún secreto ni cabecera de autenticación.

El sondeo periódico conserva formularios abiertos. Una revisión o un contexto tardío no sustituye una edición sucia, y las revisiones optimistas siguen viajando como `expected_revision`.

## Verificación

Se ejecutó:

```text
node --check agentrelay/static/app.js
```

Resultado: sintaxis correcta. También se revisaron manualmente los puntos de salida de red para comprobar que sólo el catálogo queda fuera del ámbito de un proyecto y que las rutas específicas usan la cabecera capturada.

No se realizó prueba de navegador: el permiso para esa ejecución continúa denegado y la integración visual queda pendiente de la validación del propietario del backend.

## Regresión de carreras asíncronas

Se añadió un arnés unitario Node que carga el `app.js` de producción mediante `node:vm`, con DOM mínimo y `fetch` controlado en memoria. El arnés no reproduce las funciones de coordinación: expone y ejecuta directamente `app`, `loadState`, `mutate`, `loadContext`, `closeTicket` y `selectWorkspace`. Sólo sustituye el bloque final que conecta eventos, arranca la carga y programa el sondeo. La sustitución exige una coincidencia exacta y única; si el bootstrap cambia o desaparece, la prueba falla en vez de reducir cobertura en silencio.

Las pruebas cubren estas intercalaciones:

- un `GET /api/state` iniciado antes de un `POST /api/actions` termina después y no sustituye el estado confirmado por la mutación;
- cerrar y volver a abrir el mismo ticket invalida el contexto de la apertura anterior;
- al cambiar de proyecto, las respuestas pendientes de estado y contexto del proyecto previo se descartan;
- la mutación conserva la cabecera `X-AgentRelay-Workspace` capturada al iniciarse, bloquea el selector durante la escritura y rechaza una segunda mutación concurrente antes de llegar a `fetch`.

Se ejecutaron, sin navegador, servidor ni acceso de red:

```text
node --check tests/test_ui_races.js
node tests/test_ui_races.js
.runtime/Scripts/python.exe -X utf8 -B -m unittest tests.test_ui_races -v
```

Resultado: 4 escenarios Node superados y 1 prueba `unittest` superada. El wrapper omite la prueba de forma explícita cuando no encuentra Node y limita el subproceso a 20 segundos. No se detectaron nuevos defectos en estas guardas de concurrencia.
