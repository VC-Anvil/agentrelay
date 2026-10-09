# Informe de vigencia de snapshots

## Contrato de biblioteca

`compare_snapshot(directory: Path, root: Path) -> dict` compara un snapshot íntegro con una raíz actual elegida explícitamente. La función nunca usa `source_root` del manifiesto para seleccionar, autorizar ni leer archivos actuales.

Antes de inspeccionar la raíz actual, verifica por completo el snapshot. La lectura estable del manifiesto queda rodeada por dos verificaciones; se conservan y comparan el ID, la identidad del directorio y los bytes exactos del manifiesto. Un snapshot inválido o que cambia durante esta secuencia produce `SnapshotError` antes de acceder a la raíz actual.

La respuesta tiene esta forma:

```text
{
  "snapshot_id": "sha256:…",
  "root": "ruta absoluta explícita",
  "files": [{
    "path": "ruta/relativa",
    "status": "unchanged|modified|missing|uncheckable",
    "expected": {"size": 123, "sha256": "…"},
    "current": {"size": 123|null, "sha256": "…"|null},
    "reason": "explicación"
  }],
  "summary": {"total": 1, "unchanged": 1, "modified": 0, "missing": 0, "uncheckable": 0}
}
```

`missing` requiere dos observaciones de ausencia mediante `lstat` y que el directorio padre real conserve su firma entre ambas; no se resuelve ni se sigue la ruta ausente. Errores de permisos, carreras, enlaces, junctions, puntos de reanálisis, componentes no directorio y archivos no regulares se clasifican como `uncheckable` con una razón concreta.

## Límites y estabilidad

La implementación reutiliza la canonicalización, las firmas portables y la lectura estable de `snapshots.py`. Mantiene los límites de 64 entradas ya verificados en el manifiesto, 1 MiB por archivo actual y 8 MiB de intentos de lectura actuales en total. El tamaño observado se reserva antes de cada intento, incluso si la lectura termina en carrera o error, y se usa como límite del lector estable para detectar crecimiento. Cada archivo se comprueba antes, durante y después de leerlo. Si la identidad de la raíz cambia durante la operación, todos los resultados se degradan a `uncheckable`.

La comparación no escribe en el snapshot ni en la raíz. Como la captura original, no representa una vista atómica de varios archivos: distintos archivos pueden observarse en instantes diferentes. Las defensas detectan corrupción y carreras observables, pero no forman un sandbox contra un proceso local hostil capaz de ganar una carrera TOCTOU.

## Pruebas

Las pruebas cubren contenido idéntico, cambio de tamaño, cambio de igual tamaño, ausencia confirmada, snapshot corrupto y traversal antes de tocar la raíz, omisión deliberada de `source_root`, cambio de identidad del snapshot, lectura actual inestable, archivo no regular, enlace o reparse inseguro y límites por archivo y total. Una regresión adicional fuerza varios fallos de lectura y comprueba que consumen el presupuesto reservado antes de impedir el siguiente intento. El caso de enlace real se omite explícitamente si Windows no permite crearlo; la clasificación se prueba además sin depender de ese privilegio.

No se ejecutan proveedor, servidor, red, base de datos ni inferencia. La integración CLI pertenece al coordinador.

La compilación de `agentrelay/freshness.py` y `tests/test_freshness.py` con `py_compile` terminó correctamente. La ejecución ordinaria dentro del sandbox de Windows no alcanzó las aserciones porque `Path.resolve(strict=True)` recibió `WinError 5` incluso sobre directorios recién creados dentro del workspace; se respetó la indicación de no elevar. Como diagnóstico acotado, sustituyendo únicamente `Path.resolve` por `Path.absolute` en el proceso de prueba, se ejecutaron los 10 casos: 9 correctos y 1 omisión por falta del privilegio de crear enlaces simbólicos. Esta ejecución diagnóstica no acredita la comprobación de resolución real.

El integrador ejecutó después la ruta normal, sin esa sustitución: 16 pruebas combinadas de plan y vigencia, con 15 correctas y una única omisión del caso de symlink por privilegios (6 de plan y los 10 casos de este módulo). También había validado previamente las rutas CLI y HTTP asociadas. Esta es la evidencia definitiva de ejecución para el paquete.

## QA cruzada de `create_plan`

Se revisaron de forma independiente `Store._create_plan`, la migración de esquema, el despacho transaccional y `tests/test_plan_import.py`. No se encontraron defectos bloqueantes en atomicidad, replay, padres cerrados ni normalización:

- `Store.action` ejecuta `create_plan` dentro del mismo `_write` con `BEGIN IMMEDIATE`; tickets provisionales, secuencia, dependencias, eventos y recibo de idempotencia se confirman o revierten juntos. La prueba de error tardío comprueba tickets, eventos y contador después del rollback.
- `plan_requests` se crea con `CREATE TABLE IF NOT EXISTS` al abrir la base. La clave primaria serializa un `request_id`; el bloqueo de escritura hace que dos importadores concurrentes terminen con un único recibo y el segundo reproduzca el resultado persistido.
- El hash usa JSON canónico por orden de claves. Un replay exige el mismo actor y la misma carga canónica; los cambios de actor o carga devuelven conflicto. El resultado almacenado es deliberadamente un recibo de creación y no pretende ser contexto actual.
- Los IDs externos se normalizan antes de validarlos y persistirlos. Las claves locales rechazan espacios exteriores, las dependencias se vuelven a comprobar después de resolver referencias locales y los duplicados resultantes se rechazan.
- La segunda validación usa `_normalize_ticket_fields`, que impide adjuntar hijos a padres `done` o `cancelled`. Como ocurre todavía dentro de la transacción, ese fallo también revierte los IDs y tickets provisionales.

Quedan dos huecos de cobertura explícita, de riesgo bajo: el archivo de pruebas no construye una base v0.3 previa para comprobar la migración de `plan_requests`, ni contiene un caso directo de padre externo cerrado que verifique el rollback. Las rutas correspondientes son simples y compartidas con la inicialización y normalización existentes, y la pasada integrada no mostró fallos; conviene convertirlas en regresiones si estas reglas cambian. No se modificó `store.py`, sus pruebas ni ningún dato de tickets durante esta revisión.
