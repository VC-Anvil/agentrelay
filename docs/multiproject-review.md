# Revisión independiente: espacios de trabajo de AgentRelay

## Resultado

La selección HTTP de proyecto no recibe rutas arbitrarias desde el cliente. `load_workspaces()` valida IDs registrados y bases existentes de AgentRelay, rechaza duplicados y cierra gestores ya creados si falla una configuración posterior. Estado, contexto, exportación y acciones usan `X-AgentRelay-Workspace`: sin encabezado en modo multiproyecto devuelven 400 y un ID desconocido devuelve 404. `start_run` y `cancel_run` llaman al gestor del `Workspace` elegido; `server_close()` cierra todos los gestores registrados.

Añadí `tests/test_workspace_execution.py` para comprobar la ruta que faltaba: dos SQLite y dos `ExecutionManager` reales, ambos con AR-0001 y worker `fixture`; un proceso Python por proyecto sin proveedor LLM. La prueba retiene alpha en ejecución, comprueba que cancelar su `run_id` desde beta responde 404, inicia beta mientras alpha sigue activo, libera alpha y espera ambos en `review`. Comprueba además el contenido y la ruta de cada reporte, la evidencia y el resumen con marca de proyecto, el historial de estado y exportación de cada base, y una cancelación válida de otro run de beta que deja su ticket bloqueado sin alterar alpha. Los bucles de espera tienen plazo y duermen 0,05 s por iteración. Los gestores y el servidor se cierran en limpieza de prueba.

Las dos carreras de interfaz señaladas en la revisión anterior están corregidas en fuente: `dataEpoch` invalida un `loadState()` iniciado antes de una mutación confirmada, y `contextRequest` invalida la respuesta de un contexto cerrado y reabierto con el mismo ID. La lectura de `static/app.js` confirma esos guardas; quedan pendientes prueba unitaria de frontend y QA interactiva en navegador. No afirmo que la revisión de fuente sustituya esa comprobación.

## Evidencia y límite de ejecución

`python -B -c "import ast, pathlib; ast.parse(pathlib.Path('tests/test_workspace_execution.py').read_text(encoding='utf-8'))"` pasó (`AST OK`). El intento normal de `D:\AgentWorkspace\agentrelay\.runtime\Scripts\python.exe -m unittest tests.test_workspace_execution -v` falló en `setUp` antes de iniciar SQLite o HTTP: `PermissionError: [Errno 13] Permission denied` al escribir `fixture_worker.py` bajo el TEMP aislado de Windows. El mismo sandbox denegó limpiar esa carpeta temporal. No se escaló el permiso. Por ello la prueba funcional nueva está preparada, pero su resultado sigue pendiente de ejecución en el entorno autorizado de integración.

La suite previa `tests.test_workspaces` había fallado también en `setUp` al abrir SQLite bajo ese TEMP (`sqlite3.OperationalError: unable to open database file`); no fue un fallo de sus aserciones. No se hizo QA visual en navegador. El recibo de snapshot y `report_sha256` en el adaptador no seleccionan base de datos y no muestran cruce de proyectos en revisión de código.

## Validación posterior del integrador

La prueba funcional de dos gestores pasó en el entorno normal de integración (1 caso, 1,570 s). También pasaron los cuatro escenarios de carreras de UI mediante Node, sin navegador. La batería integrada posterior ejecutó 62 casos en 16,089 s: 61 pasaron y uno se omitió por falta de privilegios para crear symlinks. El intento fallido anterior del revisor se conserva como límite de su entorno. La revisión visual sigue pendiente.
