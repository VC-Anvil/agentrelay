# Informe de snapshots acotados

## Resultado

Se añadió `agentrelay/snapshots.py` con dos operaciones de biblioteca estándar:

- `create_snapshot(root, files, destination)` captura una lista explícita de archivos sin escribir en el proyecto fuente.
- `verify_snapshot(directory)` valida estructura, límites, tamaños, SHA-256 e identificador estable y devuelve `valid`, `errors` y `snapshot_id`.

La captura limita la entrada a 64 archivos, 1 MiB por archivo y 8 MiB totales. Rechaza rutas absolutas, traversal, globs, duplicados sin distinguir mayúsculas, nombres no portables en Windows, ADS, archivos no regulares y enlaces o puntos de reanálisis en cualquier componente inspeccionado. El destino debe ser nuevo, estar fuera de la raíz fuente y tener un padre existente.

Los bytes se escriben primero en un directorio de staging exclusivo junto al destino. Sólo después de completar los archivos y `manifest.json` se promociona el directorio. La limpieza comprueba que el staging siga siendo un directorio real cuyo padre resuelto sea el previsto antes de eliminarlo.

El identificador `sha256:…` depende únicamente de las rutas canónicas ordenadas y de sus bytes, con longitudes delimitadas; no incorpora fecha, raíz fuente ni orden de entrada. `captured_at` se registra en UTC.

## Estabilidad en Windows

Python 3.12 en Windows puede exponer `st_ctime_ns` como fecha de creación al consultar una ruta y como fecha de cambio al consultar el descriptor abierto. Por eso la firma portable de Windows compara dispositivo, inode, tamaño y `mtime_ns`. En otras plataformas también compara `ctime_ns`. La lectura sigue verificando la firma antes, durante y después de leer, tanto sobre el descriptor como sobre la ruta.

Hay una regresión específica que cubre un archivo preexistente modificado antes de capturarlo y la diferencia estable de `ctime_ns` entre `lstat` y `fstat` en Windows.

## Comprobación

Comando ejecutado con el Python 3.12 incluido en el entorno del proyecto:

```text
python -X utf8 -m unittest tests.test_snapshots -v
```

Resultado: 9 pruebas correctas; 1 prueba de enlaces simbólicos omitida porque la cuenta de Windows no dispone del privilegio para crearlos. La lógica de rechazo de enlaces y puntos de reanálisis se prueba donde el sistema permite construir el caso. También se comprobó compilación con `py_compile`.

Tras corregir la semántica de `ctime` de Windows, el coordinador comunicó además un piloto correcto sobre cuatro proyectos y la batería integrada completa con 52 pruebas correctas y una única omisión por ese mismo privilegio de enlaces simbólicos.

La batería cubre copia byte a byte, hashes e ID estable, corrupción, manifiesto con traversal, límites, destinos existentes, retirada del staging tras fallo, cambios durante lectura, rutas Windows no portables y manifiestos ausentes o inválidos.

## Límites de seguridad y consistencia

La captura no es una vista atómica de varios archivos. Cada archivo queda protegido por comprobaciones antes y después de su propia lectura, pero dos archivos pueden representar instantes ligeramente distintos.

El manifiesto no está firmado. La verificación detecta corrupción accidental y alteraciones observables, pero no autentica el origen. Las comprobaciones reducen escapes por rutas, enlaces, junctions y puntos de reanálisis; no prometen aislamiento frente a un proceso local hostil que gane una carrera TOCTOU sobre el sistema de archivos.
