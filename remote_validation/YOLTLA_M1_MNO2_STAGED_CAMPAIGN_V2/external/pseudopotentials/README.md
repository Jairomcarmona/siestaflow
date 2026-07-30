# Pseudopotenciales incluidos y protegidos

La V2 incluye por instrucción directa del usuario los archivos auditados:

| Archivo | SHA-256 obligatorio |
|---|---|
| `Mn.psml` | `0b97ccd71456e4a7b28316f78ddb30bb1f6a82d9aba386c7fde78090d31c0dc6` |
| `O.psml` | `224ded5c59176d9bcb76d19b7a4a68a48d5dffabf8b262f64d5760250e87c35e` |

Forman parte del contenido inmutable, del manifiesto y del ZIP. No los copie
encima ni los sustituya. El verificador y el guardián de ejecución se bloquean
si cambia un byte.

Familia auditada: ONCVPSP/PBE, escalar relativista, PSML. El XC de generación
del pseudo es PBE; la energía total de esta rama usa vdW-DF2/LMKLL.
