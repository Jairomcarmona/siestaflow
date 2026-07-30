# PROMPT M3B1 — PRIMER SMOKE REAL DE SIESTA CON `SURF_Gr5x5_clean_v01`

## 0. Autopersistencia obligatoria

Guarda íntegramente este prompt en:

```text
siestaflow/docs/governance/PROMPT_M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE_PACKAGE.md
```

Calcula su SHA-256 y registra:

- ruta;
- fecha;
- tamaño;
- SHA-256;
- hito asociado;

en:

```text
siestaflow/docs/context/CONTEXT_INVENTORY.md
```

Si no puedes conservar el prompt íntegro:

```text
PROMPT_SELF_PERSISTENCE_FAILED
M3B1_NOT_STARTED
```

No hagas commits.

---

# 1. Hito autorizado

Ejecuta exclusivamente:

```text
M3B1_SURF_GR5X5_REAL_SIESTA_SMOKE_PACKAGE
```

Objetivo:

```text
corregir el defecto remoto de SLURM_SUBMIT_DIR
+
preparar el primer cálculo real de SIESTA
+
entregar un ZIP autosuficiente listo para subir a Yoltla
```

El cálculo utilizará la geometría real:

```text
SURF_Gr5x5_clean_v01
```

Clasificación obligatoria:

```yaml
geometry_origin: REAL_VALIDATED_PROJECT_GEOMETRY
execution_purpose: TECHNICAL_REMOTE_SIESTA_SMOKE
scientific_calculation_performed: true
scientific_interpretation_allowed: false
production_calculation: false
geometry_optimization: false
campaign_execution: false
```

No ejecutes SLURM, SSH, MPI remoto ni SIESTA remoto.

No continúes a M4.

No hagas commits.

---

# 2. Estado de entrada

Considera aceptados localmente:

```text
M0_COMPLETE
M1_COMPLETE
M2_COMPLETE
M3G_COMPLETE
M3R_LOCAL_PASS
M3R2_LOCAL_PASS
M3_STATIC_V3_VERIFIED_ON_YOLTLA
LOGIN_PROBE_REAL_PASS
ACCOUNT_WIDE_ASSOCIATION_RESOLUTION_PASS
UNIQUE_DEFAULT_PARTITION_RESOLUTION_PASS
```

Evidencia remota real:

```yaml
account: vini
partition: q1h-20p
qos: normal
association_scope: ACCOUNT_WIDE_ASSOCIATION
selection_policy: UNIQUE_COMPATIBLE_DEFAULT_PARTITION
```

El trabajo real anterior:

```yaml
job_id: 778835
state: FAILED
exit_code: "1:0"
elapsed: "00:00:01"
node: nc65
partition: q1h-20p
account: vini
qos: normal
```

demostró correctamente:

```text
sbatch aceptó el trabajo
la cuenta es válida
el QoS es válido
la partición es válida
el trabajo llegó a un nodo de cómputo
SLURM creó stdout y stderr
sacct produjo evidencia terminal
```

Falló únicamente por:

```text
mkdir: cannot create directory '/var/spool/slurm/evidence': Permission denied
```

Causa confirmada:

```bash
ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)
```

SLURM ejecutó una copia del script desde su spool interno y `BASH_SOURCE[0]` resolvió una ruta bajo:

```text
/var/spool/slurm
```

El trabajo `778835` debe conservarse como evidencia de fallo real y nunca presentarse como ejecución aprobada.

---

# 3. Cambio de estrategia autorizado

No prepares otro probe SLURM vacío.

La próxima asignación remota debe ejecutar directamente el primer smoke real de SIESTA con:

```text
SURF_Gr5x5_clean_v01
```

La secuencia será:

```text
descubrimiento en nodo de login
→ validación del paquete
→ generación del SLURM real
→ revisión humana
→ una ejecución real de grafeno
→ inspección de sacct y outputs
→ importación del bundle
```

El descubrimiento en el nodo de login no constituye una ejecución científica y no debe usar `sbatch`.

El único `sbatch` preparado por este paquete debe corresponder al smoke real del grafeno.

---

# 4. Restricción de generalización

SIESTAFLOW debe seguir siendo un framework generalizable.

No introduzcas en el núcleo lógica específica para:

```text
SURF_Gr5x5_clean_v01
grafeno
carbono
vini
q1h-20p
normal
Yoltla
birnessita
Mn
O
```

Estos valores pueden existir únicamente en:

```text
paquete externo del proyecto de referencia
perfil de despliegue Yoltla
fixtures de integración
manifiesto del smoke real
documentación de validación
```

La lógica reutilizable debe permanecer general:

```text
resolución del directorio de envío
descubrimiento del ejecutable
selección del launcher
renderizado SLURM
verificación de pseudopotenciales
ejecución SIESTA
captura de evidencia
importación y parsing de resultados
```

No conviertas el caso del grafeno en lógica central.

---

# 5. Desarrollo dirigido por pruebas

Trabaja en este orden obligatorio:

```text
1. incorporar evidencia real;
2. escribir pruebas que fallen con el código actual;
3. demostrar el fallo;
4. aplicar la corrección mínima;
5. ejecutar pruebas específicas;
6. ejecutar todas las regresiones;
7. generar el paquete;
8. verificar el ZIP de forma independiente.
```

No corrijas primero para escribir las pruebas después.

---

# 6. Corrección obligatoria de `SLURM_SUBMIT_DIR`

Corrige la fuente responsable de renderizar el script SLURM.

El script ejecutado en el nodo debe resolver su raíz mediante:

```bash
[[ -n "${SLURM_SUBMIT_DIR:-}" ]] || {
  echo "SLURM_SUBMIT_DIR_NOT_SET" >&2
  exit 2
}

ROOT=$(cd "$SLURM_SUBMIT_DIR" && pwd -P)

[[ -f "$ROOT/package_manifest.json" ]] || {
  echo "INVALID_SLURM_SUBMIT_DIR:$ROOT" >&2
  exit 2
}
```

Adapta el nombre del manifiesto sólo si el paquete usa otro nombre canónico.

No utilices:

```bash
BASH_SOURCE[0]
dirname "$0"
pwd
PWD
```

como fuente de autoridad para determinar la raíz del paquete dentro del trabajo SLURM.

`PWD` puede registrarse como evidencia, pero no debe controlar las rutas.

Todas las escrituras deben quedar bajo:

```text
$SLURM_SUBMIT_DIR/evidence/
$SLURM_SUBMIT_DIR/results/
$SLURM_SUBMIT_DIR/work/
```

No debe existir ningún intento de escribir bajo:

```text
/var/spool/slurm
/tmp
$HOME
directorio del repositorio local
```

salvo archivos temporales explícitos, controlados y eliminados dentro del propio directorio del paquete.

---

# 7. Pruebas de regresión para el fallo remoto

Añade pruebas para:

```text
SLURM_SUBMIT_DIR válido
SLURM_SUBMIT_DIR ausente
SLURM_SUBMIT_DIR inexistente
SLURM_SUBMIT_DIR sin manifiesto
BASH_SOURCE apuntando a /var/spool/slurm
script ejecutado desde una copia simulada del spool
evidence creada bajo la raíz del paquete
work creado bajo la raíz del paquete
results creado bajo la raíz del paquete
ninguna escritura bajo /var/spool/slurm
```

El test principal debe simular:

```yaml
script_location: /var/spool/slurm/job12345/slurm_script
SLURM_SUBMIT_DIR: <temporary-package-root>
```

Resultado esperado:

```text
ROOT = <temporary-package-root>
exit_code = 0
no_spool_write_attempts = true
```

Token requerido:

```text
SLURM_SUBMIT_DIR_RUNTIME_FIX_PASS
SPOOL_PATH_REGRESSION_TEST_PASS
```

---

# 8. Geometría canónica

Localiza la geometría canónica aprobada:

```text
SURF_Gr5x5_clean_v01
```

Debe provenir del proyecto externo o paquete de referencia aprobado en T02/T02R.

Propiedades esperadas:

```yaml
atoms: 50
elements:
  C: 50
charge: 0
magnetism: non_spin_polarized
surface_type: graphene
geometry_status: validated
```

No recrees la geometría manualmente.

No redondees coordenadas.

No recentres átomos.

No cambies la celda.

No cambies el vacío.

No reordenen átomos, salvo que el formato SIESTA lo exija y exista una transformación determinista, documentada y reversible.

Calcula y registra:

```text
source_geometry_path
source_geometry_sha256
packaged_geometry_sha256
coordinate_semantic_hash
lattice_semantic_hash
atom_order_hash
```

La comparación debe demostrar:

```text
GEOMETRY_BYTE_IDENTICAL
```

o, cuando el formato empaquetado sea distinto:

```text
GEOMETRY_SEMANTICALLY_IDENTICAL
```

La geometría específica debe residir fuera del núcleo, por ejemplo:

```text
examples/reference_projects/graphene/
```

o en la estructura externa de proyectos ya implementada.

---

# 9. Pseudopotencial de carbono

Localiza un pseudopotencial de carbono real, previamente auditado y compatible con el adaptador SIESTA.

Preferencia:

```text
C.psml
```

No descargues pseudopotenciales de Internet.

No generes un pseudopotencial nuevo.

No cambies su nombre interno.

No conviertas formatos.

No uses un pseudopotencial de otro elemento como stub.

Registra:

```text
filename
format
absolute_source_path
source_sha256
packaged_sha256
element
atomic_number
provenance
license_or_redistribution_status
```

El ZIP sólo puede declararse listo para subir si el pseudopotencial real está incluido y su inclusión está permitida por la política del proyecto.

Si falta o no puede empaquetarse:

```text
C_PSEUDOPOTENTIAL_NOT_AVAILABLE_FOR_PACKAGING
M3B1_PACKAGE_NOT_READY
```

No construyas un ZIP incompleto presentado como ejecutable.

La verificación remota debe bloquear la ejecución si el hash no coincide exactamente.

---

# 10. Construcción del FDF

Genera el FDF mediante el adaptador SIESTA de SIESTAFLOW.

No escribas un FDF artesanal fuera del flujo normal del framework.

El input debe derivarse de:

```text
geometría real aprobada
pseudopotencial real aprobado
perfil técnico explícito
renderer FDF existente
validator FDF existente
```

Características del cálculo:

```yaml
system: SURF_Gr5x5_clean_v01
calculation_type: single_point
geometry_optimization: false
molecular_dynamics: false
spin_polarized: false
number_of_atoms: 50
number_of_species: 1
species:
  - C
charge: 0
bands: false
dos: false
pdos: false
optical_properties: false
restart: false
campaign: false
```

No autorices interpretación de:

```text
energía total
energía por átomo
estructura electrónica
propiedades del grafeno
convergencia científica
comparación con literatura
```

El objetivo es verificar funcionamiento técnico.

---

# 11. Parámetros numéricos

No inventes silenciosamente:

```text
MeshCutoff
PAO.BasisSize
XC.functional
k-grid
tolerancia SCF
mezcla de densidad
número máximo de iteraciones
temperatura electrónica
```

Procedimiento obligatorio:

1. busca el perfil SIESTA real asociado al proyecto;
2. busca variantes técnicas ya aprobadas

