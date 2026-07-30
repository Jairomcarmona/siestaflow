# Informe de pruebas V3.2

La suite local contiene 17 pruebas y cubre:

- contrato Slurm 2x64=128 y estrategia interna 64/128;
- hashes PSML y materialización FDF;
- bloque PAO explícito y DFT+U Dudarev;
- índices FM/stripe-AFM;
- rechazo de meseta acumulativa falsa;
- rechazo cuando energía converge pero fuerzas no;
- parser de fuerzas y tabla Mulliken final;
- clasificación FM, stripe, inversión global y colapso;
- prohibición de comparar energías si los estados finales coinciden;
- clasificación retryable/terminal;
- guardia de walltime;
- presencia del preflight multinodo y afinidad;
- cadena automática completa, cierre y transferencia DFT+U.

Resultado local: `17/17 PASS`.

No se ejecutó SIESTA real ni Slurm localmente. El paquete permanece
`LOCAL_STATIC_PASS_REMOTE_VALIDATION_REQUIRED` hasta superar
`sbatch --test-only`, el preflight multinodo y el benchmark dentro de Yoltla.
