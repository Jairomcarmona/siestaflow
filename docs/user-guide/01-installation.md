# Instalación

QRAFT requiere Python 3.11 o posterior y está dirigido a sistemas
POSIX/Linux. Instálalo en un entorno virtual para que tu proyecto no dependa de
paquetes globales.

## Desde un clon limpio

Esta ruta no depende de que exista un wheel dentro del repositorio:

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
python3 -m venv qraft-env
source qraft-env/bin/activate
python -m pip install .
qraft --version
which qraft
```

La ruta mostrada por `which qraft` debe pertenecer al entorno virtual. Para
desarrollo usa `python -m pip install -e '.[dev]'`; para una instalación de uso
normal conserva `python -m pip install .`.

## Desde un wheel

El wheel es un artefacto de compilación y no está incluido en el clon. Puedes
recibir un wheel aprobado del administrador o construirlo desde un clon limpio:

```bash
python -m pip install build
python -m build --wheel
python -m pip install dist/qraft-0.2.0-py3-none-any.whl
```

También puedes instalar un wheel entregado en una ruta compartida:

```bash
python3 -m venv qraft-env
source qraft-env/bin/activate
python -m pip install /shared/software/qraft/qraft-0.2.0-py3-none-any.whl
qraft --version
which qraft
```

## Instalación offline con wheelhouse

En un nodo Linux con acceso a Internet, compatible con la arquitectura y la
versión de Python del HPC, crea un wheelhouse que incluya QRAFT y sus
dependencias:

```bash
git clone https://github.com/Jairomcarmona/siestaflow.git
cd siestaflow
python3 -m venv build-env
source build-env/bin/activate
python -m pip install build
python -m pip wheel --wheel-dir wheelhouse .
```

Copia `wheelhouse/` al almacenamiento compartido del clúster. En el HPC:

```bash
python3 -m venv qraft-env
source qraft-env/bin/activate
python -m pip install --no-index --find-links /shared/software/qraft/wheelhouse qraft==0.2.0
qraft --version
which qraft
```

Conserva el wheelhouse junto con la versión desplegada para que la instalación
sea repetible. No uses `PYTHONPATH` ni ejecutes la CLI desde un árbol fuente.

Si el clúster no incluye el módulo `venv`, solicita al administrador un Python
3.11 o posterior con soporte para entornos virtuales.

## Programas externos

Para ejecutar una campaña necesitas:

- un ejecutable SIESTA compatible con tus entradas, instalado por ti o por el
  administrador del HPC;
- un launcher MPI, como `mpirun`, si usarás varios rangos;
- Slurm sólo si tu sistema usa Slurm.

Carga los módulos requeridos por el sitio antes de usar QRAFT. QRAFT no instala
ni configura SIESTA, MPI o Slurm y tampoco ejecuta comandos `module` declarados
en un perfil.

Comprueba el entorno antes de ejecutar:

```bash
qraft setup env
qraft --help
```

QRAFT puede validar y renderizar entradas sin ejecutar SIESTA. La disponibilidad real del ejecutable se comprueba de nuevo durante `qraft run`.

Antes de `qraft check` o `qraft run`, crea un perfil específico para el sitio y
valídalo. Consulta [Perfiles de ejecución](../user/profiles.md), el
[inicio rápido](02-quickstart.md) y [Slurm y HPC](11-slurm-hpc.md). No copies
la partición, cuenta, launcher o rutas de otro clúster.
