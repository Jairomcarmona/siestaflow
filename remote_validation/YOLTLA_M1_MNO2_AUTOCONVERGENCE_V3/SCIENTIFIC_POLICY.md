# Política científica cerrada

## Convergencia numérica

La geometría, composición, celda, funcional, pseudopotenciales, temperatura
electrónica, mezcla y estado inicial U=0/FM permanecen fijos durante las series
de Mesh y k-grid. Solamente cambia el parámetro bajo prueba.

El criterio automático es 2 meV/átomo. Se requiere terminación normal, SCF
convergido y energía final analizable.

## Base

El manual SIESTA 5.4.2, sección 6.3.3, documenta `PAO.BasisSize` para SZ, DZ,
SZP y DZP. Por ello la base más estricta no se expresa mediante el valor no
documentado `PAO.BasisSize TZP`.

Se usa un bloque `PAO.Basis` explícito de triple zeta con una polarización:

- Mn: 3s, 3p, 3d y 4s, conservando los semicore 3s/3p incluidos en Mn.psml.
- O: 2s y 2p.
- Los radios cero solicitan su generación consistente desde
  `PAO.EnergyShift=200 meV` y `PAO.SplitNorm=0.15`.

La comparación es una prueba de sensibilidad DZP/TZP. Si no cumple la
tolerancia, TZP se adopta como base piloto más completa; no se afirma límite de
base completa.

## DFT+U

El manual SIESTA 5.4.2, secciones 8 y `DFTU.Proj`, establece para magnetismo
colineal el formalismo simplificado de Dudarev:

`Ueff = U - J`

El paquete utiliza `J=0`, por lo que el valor ingresado como U es exactamente
Ueff. Los candidatos son 3.8 y 4.0 eV.

Se utiliza `DFTU.ProjectorGenerationMethod 2`, valor predeterminado documentado,
con `DFTU.CutoffNorm=0.9`. El radio y ancho se especifican como cero para usar
los valores generados por el método documentado, evitando transferir el radio
1.76 Bohr específico del ejemplo Cu3N.

El archivo Cu3N sirvió para reconocer la estructura del bloque, pero no se
transfirieron sus parámetros Cu, su U=5 eV ni la etiqueta antigua
`LDAU.ProjectorGenerationMethod`.

## Magnetismo

Los 18 índices Mn están auditados. Se ejecutan FM y stripe-AFM con la misma
celda, base, Mesh, malla k y U. Se selecciona el estado de menor energía dentro
de cada U, salvo degeneración dentro de 2 meV/Mn.

No se comparan energías totales entre U distintos para seleccionar U. El valor
3.8 eV es la política primaria predeclarada y 4.0 eV una prueba de sensibilidad.
La elección magnética se considera robusta únicamente cuando ambos valores de U
producen el mismo orden.
