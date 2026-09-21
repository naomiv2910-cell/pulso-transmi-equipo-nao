# Estado del proyecto Pulso TransMi

## Arquitectura y componentes

La API oficial aporta reloj, ciclos, observaciones, contexto y recibos. GitHub Actions ejecuta pruebas y los comandos manuales; los procesos del servidor usan los secretos `PULSO_API_KEY`, `SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` sin registrar sus valores. Supabase conserva datos, ejecuciones, modelos, ciclos, predicciones y métricas con RLS activo y sin políticas públicas.

Están completos: descarga verificable, EDA, esquema de nueve tablas, entrenamiento temporal, artefacto champion, inferencia segura, primera submission oficial, reconciliador idempotente, ingesta incremental, backtesting multifold, evaluación, monitoreo y política de reentrenamiento. No se implementaron MLflow ni dashboard porque son bonos posteriores.

## Modelo y backtesting

El champion usa Gradient Boosting para 15, 30, 45 y 60 minutos. En tres folds expansivos de siete días alcanzó accuracy promedio de 86,11 % (desviación 0,50 pp), WAPE medio por estación de 14,26 %, MAE 49,71 y RMSE 78,54. Superó a los tres baselines en cada uno de los 12 cruces fold/horizonte. Las tablas y gráficas están en `reports/tables/backtest_*` y `reports/figures/10_*`, `11_*`.

## Entrega oficial y Supabase

- Submission: `sub_d9851baf53ce4340bbe5bbecf63ada61`
- Estado: `accepted`, oficial, intento 1, 48/48.
- Modelo: `champion-1.0.0`; commit de la entrega: `01ab0d0`.
- Estado previo confirmado: `pipeline_runs=2`; ciclos, modelos, predicciones y métricas en cero.
- El código de reconciliación está listo, pero la escritura debe ejecutarse únicamente después de aprobación expresa. No se reenvía la submission.

## Seguridad y operación

No hay secretos en archivos versionados. `service_role` se limita a procesos de servidor. La reconciliación solo usa GET contra la API y todos los upserts tienen conflicto lógico explícito. RLS permanece activo; no se añadieron políticas públicas ni cambios de esquema. El monitor compara distribución reciente y accuracy con el champion; la promoción y reentrenamiento siguen siendo decisiones humanas. No hay cron hasta recibir la frecuencia oficial.

## Demostración

```bash
python -m pytest -q
python src/reconcile_submission.py --submission-id sub_d9851baf53ce4340bbe5bbecf63ada61 --dry-run
python src/ingest.py --dry-run
python src/evaluate.py --dry-run
python src/monitor.py --dry-run
```

## Evidencias para el profesor

- Commit y workflow verde; pruebas mockeadas.
- Dry-run sin escrituras y recibo `accepted`, `is_official=true`, 48/48.
- Tablas, métricas y dos gráficas del backtesting.
- RLS activo y nombres —no valores— de los tres GitHub Secrets.
- Después de autorizar `reconcile`: conteos antes/después, ciclo oficial, champion, exactamente 48 predicciones, ausencia de duplicados y run `succeeded` con `finished_at`.

Pendientes legítimos: ejecutar y verificar la reconciliación aprobada; evaluar cuando llegue ground truth; activar cron solo cuando el profesor publique la frecuencia; MLflow/dashboard como bonos.
