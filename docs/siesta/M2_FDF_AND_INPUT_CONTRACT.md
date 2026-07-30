# Contrato M2 de FDF e input

El parser es una máquina de estados lossless. Conserva texto original, comentarios, blancos, orden, capitalización, unidades, bloques, includes, redirecciones, contenido desconocido y EOL. `render(parse(bytes))` es idéntico para los 17 artefactos del snapshot. Includes y redirecciones se registran pero jamás se abren sin una política externa.

SIESTA 5.4.2 indica que la primera aparición de una etiqueta gana, admite `%include` y redirecciones, exige `AtomicCoordinatesAndAtomicSpecies`, define `kgrid.MonkhorstPack` como matriz entera con desplazamiento y `Mesh.Cutoff` como energía. La evidencia visual revisada corresponde a las páginas 20, 47, 54 y 78 del manual oficial.

El registro operativo sólo contiene etiquetas activas del snapshot y sanity. Únicamente `Mesh.Cutoff` y `kgrid.MonkhorstPack` son `MUTABLE_TECHNICAL`. Geometría, celda, especies, carga, spin, XC, PAO y relajación son `SCIENTIFICALLY_GOVERNED`; el resto es read-only o parsed-only.

El validador compara átomos/coordenadas, especies/bloque, índices, bloques obligatorios, duplicados, includes, declaraciones de carga/spin/MD y pseudopotenciales. Devuelve `PASS`, `REVIEW`, `BLOCKED` o `FAIL`, sin aplicar defaults ni interpretar ciencia.

Los manifiestos de pseudopotenciales verifican especie, nombre/formato PSML o PSF, existencia si hay ruta, SHA-256, cobertura y duplicados. Un pseudo auditado pero no suministrado conserva `EXTERNAL_NOT_PACKAGED`; nunca se descarga ni copia.

Las variantes están ligadas al hash del FDF y a una autorización M1 con parámetro y valores permitidos. Una serie admite como máximo una variable; el punto igual al FDF base es un baseline explícito de diff cero. Cualquier cambio adicional, especialmente geometría, carga o parámetros gobernados, aborta.
