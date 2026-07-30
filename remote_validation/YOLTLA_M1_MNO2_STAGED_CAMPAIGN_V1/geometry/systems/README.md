# Resultados padres importados

Los resultados aceptados se organizan como:

```text
systems/<system_id>/runs/<run_id>/
  work/run.fdf
  work/<SystemLabel>.STRUCT_OUT
  work/<SystemLabel>.XV
  work/<SystemLabel>.FA
  results/siesta.out
```

No copie un `XV` aislado. La validación necesita el conjunto completo y sus
hashes para distinguir un reinicio técnico de una geometría promovida.

