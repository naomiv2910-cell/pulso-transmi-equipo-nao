# Evidencias opcionales — Pulso TransMi

Dashboard publicado: https://pulso-transmi-nao.vercel.app

MLflow local: http://127.0.0.1:5001

[Pantallazo para adjuntar](mlflow-experimentos-metricas.png) · [Comentario listo para copiar](comentario-profesor.txt)

Los resultados fueron **importados el 24 de octubre de 2026** desde los CSV y JSON históricos del proyecto. No se presentan como ejecuciones registradas en MLflow durante el entrenamiento original. La fecha de creación de cada run corresponde a su importación; las fechas originales y las fuentes se conservan en parámetros/tags y artefactos.

Se separan tres experimentos para no mezclar validaciones diferentes:

- Inicial: 16 combinaciones de modelo y horizonte, con accuracy, WAPE medio por estación y MAE.
- Selección: cuatro candidatos, con accuracy del período de desarrollo.
- Holdout drift: cinco modelos evaluados en los mismos targets reservados, con accuracy y WAPE. Champion 2: 79,25%; Champion 1: 67,23%.

Cada run conserva la fuente y su SHA-256. El importador compara los valores registrados en MLflow contra los originales y evita duplicar ejecuciones si se vuelve a ejecutar con las mismas fuentes. No carga secretos ni modifica el modelo de producción.

## Reabrir o reconstruir

Desde la raíz del repositorio:

```sh
python3.12 -m venv .venv-mlflow
.venv-mlflow/bin/python -m pip install -r requirements-mlflow.txt
.venv-mlflow/bin/python scripts/import_mlflow_history.py
./scripts/start_mlflow.sh
```

Abrir http://127.0.0.1:5001. La base SQLite y los artefactos están en `.mlflow/`, fuera de Git. `mlflow-import-manifest.json` contiene la relación de runs, fuentes y métricas.

## Comentario para el profesor

Hola, profesor. Comparto juntas las evidencias de los componentes opcionales de Pulso TransMi:

• Dashboard en Vercel: https://pulso-transmi-nao.vercel.app
• Adjunto el pantallazo de MLflow con los experimentos y sus métricas. Los resultados históricos del proyecto fueron importados a MLflow y están identificados como tales.

Equipo Nao.
