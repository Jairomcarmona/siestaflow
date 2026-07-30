# Política científica V3.2

## Convergencia

La geometría permanece fija durante las pruebas. Para un candidato \(i\), se
comparan energía y fuerzas contra cada nivel superior \(j>i\). Se acepta el
nivel más bajo que cumpla todas las comparaciones:

- energía: máximo 2 meV/átomo;
- diferencia máxima entre vectores de fuerza: 0.01 eV/Ang;
- RMS de las diferencias de fuerza: 0.005 eV/Ang.

Estos dos umbrales de fuerza miden sensibilidad numérica en una geometría
idéntica. No son `MD.MaxForceTol` ni autorizan todavía la relajación M1.

Después de Mesh, k-grid y base se ejecuta un cierre contra 350 Ry, 5x5x1 y la
base seleccionada. Si falla, se promueven Mesh y k a esos valores estrictos.
Un cálculo representativo con el U primario y el orden seleccionado repite la
verificación. Si falla, toda la matriz U/espín se repite con los parámetros
estrictos.

## Base y DFT+U

DZP se compara con una base triple-zeta polarizada definida mediante
`PAO.Basis` explícito. La documentación también menciona TZP en contextos de
especificación automática; el bloque explícito se conserva para hacer
auditables las capas y semicore, no porque la cadena `TZP` sea universalmente
inválida.

Se mantiene Dudarev, `Ueff=U-J`, `J=0`,
`DFTU.ProjectorGenerationMethod 2`, `DFTU.CutoffNorm 0.9`, radio cero y ancho
cero. Los candidatos siguen siendo Ueff=3.8 eV (protocolo primario) y 4.0 eV
(sensibilidad). No se comparan energías entre valores de U diferentes.

## Magnetismo

`DM.InitSpin` sólo inicializa. La clasificación usa la tabla Mulliken final:

- `FM`: los 18 Mn conservan signo común y momento suficiente;
- `STRIPE_AFM`: coincide con el patrón stripe o su inversión global;
- `MOMENT_COLLAPSE_OR_MIXED`;
- `OTHER_MAGNETIC_PATTERN`;
- `INCOMPLETE_MN_MULLIKEN_TABLE`.

Las energías FM/stripe-AFM se comparan únicamente cuando los resultados finales
son realmente FM y stripe-AFM, respectivamente. Cada intento guarda
`mn_moments.csv`. Mulliken se usa para patrón relativo; no se interpreta como
momento o carga absoluta independiente de la base.

La campaña prueba solamente FM y un stripe-AFM colineales. No explora otros
AFM, ferrimagnetismo, no colinealidad ni frustración; por ello nunca declara
mínimo magnético global.
