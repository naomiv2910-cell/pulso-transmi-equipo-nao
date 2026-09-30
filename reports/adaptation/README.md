# Mejora del modelo por drift — 30 de septiembre de 2026

## Decisión

Promover `champion-2.0.0`: Gradient Boosting con 21 días recientes, ponderación exponencial de semivida de cuatro días e influencia equilibrada por estación. Se añaden demanda del origen, tendencias de 15/60 minutos y lags diarios/semanales alineados con los cuatro targets. No es un cambio de nombre: se entrenaron cuatro pipelines nuevos.

## Protocolo temporal

Datos publicados hasta 2026-09-18T01:30:00+00:00. Selección de cuatro variantes entre 2026-09-14T01:30:00+00:00 y 2026-09-16T01:30:00+00:00. El candidato se eligió antes de evaluar el holdout final de dos días. Solo entran al entrenamiento targets <= al corte; los orígenes de validación son >= al corte. El contexto se propaga desde el pasado, igual que en producción.

Las predicciones de validación se simulan cada 15 minutos con la historia disponible en cada origen. Tras aprobar, se reentrena la misma configuración con los datos publicados hasta el corte final. El resultado de backtest no es accuracy oficial futura ni del acumulado.

## Resultados reservados

| Modelo | Accuracy |
|---|---:|
| candidate | 79.25% |
| champion | 67.23% |
| last | 78.19% |
| daily | 75.03% |
| weekly | 59.70% |

9144 targets. Mejora de 12.02 puntos porcentuales. Mejora en ambas ventanas diarias; ninguna estación pierde más de cinco puntos. La comprobación adicional restringida a orígenes horarios obtiene 79,37% frente a 67,13% (2280 targets), sin cambiar la selección.

| Ventana | Anterior | Candidato |
|---|---:|---:|
| Día 1 | 69.11% | 81.54% |
| Día 2 | 64.60% | 75.01% |

## Evidencia y límites

`decision.json` conserva hashes de datos/contexto/artefactos, cortes, parámetros, métricas por estación/horizonte y comprobaciones de promoción. `holdout_predictions.csv` permite recalcular los resultados. `artifacts/versions/` conserva ambas versiones para rollback. Los archivos `model_h*.joblib` son históricos; producción carga únicamente `champion.joblib`.

El margen frente al baseline de última observación es pequeño (aproximadamente un punto), aunque supera claramente al champion. Hay solo dos días reservados; debe verificarse la mejora en los próximos seis ciclos reales evaluados junto con cobertura. No se ha demostrado adaptación automática ante cualquier drift futuro.

## Reproducción

Descargar primero los CSV iniciales con `python src/download_data.py`. Luego ejecutar (sin cambiar el champion automáticamente):

```sh
OMP_NUM_THREADS=2 python src/adapt.py --download --cutoff 2026-09-18T01:30:00+00:00
```

La ejecución usa como referencia la versión 1 archivada, genera un candidato separado y conserva el snapshot local ignorado por Git. Comprobar el hash contra `decision.json`. Las claves no son necesarias para descargar los datos sintéticos publicados. Un reentrenamiento futuro requiere otro identificador de versión y nuevas ventanas de evaluación, sin reutilizar este holdout para ajustar parámetros.

Entorno utilizado: Python 3.12, scikit-learn 1.8.0, NumPy 2.5.3, pandas 2.3.3 y joblib 1.6.0. En la prueba reservada mejoraron las 12 estaciones y los cuatro horizontes.

## Verificación en producción

La primera entrega de `champion-2.0.0` se guardó el 30/09/2026 a las 18:43:21 UTC (13:43 de Bogotá): 48 predicciones. Supabase confirma la versión 2 como champion y la versión 1 desactivada. La evaluación real de esta entrega sigue pendiente; no se presenta el resultado del backtest como resultado oficial. Ejecución: https://github.com/naomiv2910-cell/pulso-transmi-equipo-nao/actions/runs/36760385357
