# Política de reentrenamiento

El sistema **recomienda**, pero no ejecuta ni promueve automáticamente, un reentrenamiento.

Se requiere un mínimo de siete días nuevos desde el último corte. Cumplido ese mínimo, se recomienda reentrenar si la accuracy rolling de 24 horas cae al menos cinco puntos porcentuales frente a la validación del champion, o si el drift fuerte (cambio estandarizado de media ≥ 1) persiste durante más de una ventana. Un cambio ≥ 0,5 o una caída de tres puntos genera advertencia.

Todo candidato debe evaluarse con ventanas temporales, superar a los tres baselines y al champion vigente y crear una versión nueva. La promoción requiere revisión humana; nunca reemplaza `champion.joblib` automáticamente. Se conserva el artefacto anterior para rollback y se registra motivo, corte de datos, commit, métricas y versión.

Estados del monitor: `healthy`, `warning`, `retrain_recommended` e `insufficient_data` (menos de 48 muestras evaluables). Clima, eventos, estación y hora se revisan junto con demanda cuando están disponibles.
