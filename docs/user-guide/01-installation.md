# Instalación

QRAFT requiere Python 3.11 o posterior. Instálalo en un entorno virtual para que tu proyecto no dependa de paquetes globales.

```bash
python -m venv qraft-env
source qraft-env/bin/activate
python -m pip install /ruta/al/qraft-0.2.0-py3-none-any.whl
qraft --version
which qraft
```

En Windows PowerShell, activa con `qraft-env\Scripts\Activate.ps1` y usa `Get-Command qraft` en lugar de `which qraft`.

La ruta mostrada por `which qraft` debe pertenecer al entorno virtual. No uses `PYTHONPATH` ni ejecutes la CLI desde un árbol fuente.

## Programas externos

Para ejecutar una campaña necesitas:

- un ejecutable SIESTA compatible con tus entradas;
- un launcher MPI, como `mpirun`, si usarás varios rangos;
- Slurm sólo si tu sistema usa Slurm.

Comprueba el entorno antes de ejecutar:

```bash
qraft env
qraft --help
```

QRAFT puede validar y renderizar entradas sin ejecutar SIESTA. La disponibilidad real del ejecutable se comprueba de nuevo durante `qraft run`.
