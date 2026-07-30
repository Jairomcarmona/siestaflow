# Compuertas de decisión

`templates/` es inmutable. Las decisiones reales se crean en `decisions/`,
fuera del manifiesto inmutable, y deben contener `decision: ACCEPTED`,
responsable, fecha y hashes de la evidencia. El programa comprueba los hashes
de nuevo inmediatamente antes de cada ejecución.

No copie ni renombre una plantilla como aceptación sin revisar la evidencia.

