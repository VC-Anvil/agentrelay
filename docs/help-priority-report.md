# AR-0015 · Prioridad de la ayuda solicitada

La reproducción anterior al cambio está en `.agentrelay/help-priority-repro.txt` (fixture SQLite aislado). Un padre `urgent` bloqueado por `request_help` creaba un hijo `normal`; `ready_work` situaba una tarea urgente ajena antes del hijo que permitía recuperar al padre.

`Store._help` ahora copia `priority` del padre al crear el hijo, igual que `split_ticket`. Conserva el perfil de ayuda explícito, la dependencia padre→hijo y la transacción existente. No hay propagación posterior de prioridad ni desalojo de trabajo ya reclamado.

`tests/test_help_priority.py` prueba `urgent`, `high` y `low` frente a una tarea `high` mediante el orden real de `ready_work`; verifica el bloqueo del padre, el perfil explícito y que repriorizar al padre no modifica una ayuda ya asignada. También comprueba que el agente ayudante no puede aprobar su propia entrega, que otro revisor sí puede hacerlo y que el padre permanece bloqueado hasta una reanudación explícita.

Resultado propio: 2/2 pruebas nuevas y 14/14 pruebas existentes de `test_store.py` pasan con `.runtime/Scripts/python.exe`. El sandbox de esta sesión negó SQLite en el TEMP de Windows; para estas pruebas dirigí `TEMP`/`TMP` sólo en los procesos de prueba a `.agentrelay`. `git diff --check` pasó. La batería integrada y la revisión final corresponden a Astra.
