# Monitoreo y adaptación al drift

Actualizado el 30 de septiembre de 2026. Cierre: 2 de octubre de 2026, 23:59 de Bogotá (3 de octubre, 04:59 UTC). La API decide si hay ciclo abierto y cuál es su plazo; no se inventan ciclos en intervalos sin actividad.

## Lo implementado

El vigilante consulta el ciclo vigente cada 60 segundos durante turnos de 45 minutos y solicita el siguiente turno. Conserva el payload y la clave idempotente para reintentos, el recibo de aceptación y las predicciones en Supabase. Un recibo aceptado no implica evaluación terminada. Los recibos de Actions se conservan 30 días.

El workflow analytics sincroniza observaciones mediante cursor persistente, calcula el drift por estación y evalúa las entregas del champion con verdad completa. Publica el informe en dashboard-data/dashboard.json; los commits de esa rama conservan la evolución. El dashboard se actualiza sin desplegar de nuevo.

El monitor usa PSI de residuos ajustados por estación, día de semana y hora. Compara las últimas 24 horas virtuales con datos anteriores o iguales al fin de entrenamiento. Requiere 28 días de referencia y 96 muestras recientes por estación. Estados reales: stable, warning, high, insufficient_data. PSI >= 0,20 o cambio de media estandarizado >= 0,5 genera alerta; PSI >= 0,30 o cambio >= 1 genera alerta fuerte. Son heurísticas, no pruebas de concept drift.

La precisión de 24 horas incluye solo entregas guardadas y completamente evaluables. No representa el ranking ni la cobertura oficial: la base local de submissions no contiene todos los ciclos exigibles. No se infieren ausencias contando horas, porque hubo intervalos sin ciclos abiertos.

## Revisión operativa y tendencia

1. Revisar ejecuciones, recibos y último envío. Confirmar cobertura en el tablero oficial antes de atribuir una caída al modelo.
2. Comparar el acumulado y los últimos seis ciclos oficiales evaluados. Si hay un ciclo pendiente, no asignarle precisión cero. Conservar fecha, identificadores y fuente de la comparación.
3. Analizar errores por estación y horizonte. Revisar si el cambio persiste en dos bloques consecutivos y no solapados de seis ciclos, evitando contar repetidamente el mismo informe como evidencia nueva.

## Cuándo evaluar un candidato

Política propuesta para la revisión: abrir una evaluación si ambos bloques recientes caen al menos cinco puntos de accuracy frente al período anterior comparable, o si una señal fuerte de drift persiste en dos ventanas diarias no solapadas. La cobertura debe revisarse por separado. Un único ciclo malo no dispara promoción. Estos criterios son decisiones del equipo, no reglas del profesor; la comprobación de persistencia y cobertura todavía es manual.

Antes de entrenar se exige al menos siete días virtuales nuevos publicados desde el corte del champion y datos suficientes para un conjunto temporal de validación. El monitor alerta, pero no entrena ni cambia el modelo automáticamente.

## Comparación temporal y promoción

Registrar el corte de disponibilidad de datos y su hash. Entrenar el candidato exclusivamente con información disponible antes del inicio de cada ventana de validación; purgar los targets de entrenamiento que entren en ella (horizonte máximo de 60 minutos). Los lags de cada pronóstico solo usan observaciones disponibles a su corte. Reservar ventanas posteriores para evaluar y no usarlas para ajustar el candidato.

Comparar champion, candidato y baselines en exactamente los mismos targets, usando WAPE/accuracy por estación y horizonte y el agregado. Requerir mejora de al menos dos puntos de accuracy en el conjunto de validación, mejora en dos ventanas temporales consecutivas y ninguna estación con pérdida mayor a cinco puntos. Si no cumple, conservar champion. Estos umbrales son una política inicial a revisar con evidencia, no una garantía de mejora.

La promoción requiere una decisión registrada y un artefacto realmente entrenado. Guardar versión, parámetros, rango de entrenamiento, hash de datos y artefacto, commit, métricas de ambos modelos, motivo y fecha. Conservar el champion anterior para rollback. Revisar los siguientes seis ciclos evaluados después de cualquier promoción; una regresión exige comparación sobre datos compartidos antes de revertir.

## Evidencia inicial y límites

El informe del 30 de septiembre de 2026 a las 17:56 UTC muestra champion-1.0.0 (HistGradientBoostingRegressor), entrenado hasta 2026-09-02T05:00:00Z, drift fuerte y accuracy de 64,653% en 24 ciclos entregados evaluables (1152 targets); un ciclo aún pendiente. Última entrega guardada: 17:43 UTC. Es evidencia para investigar y evaluar, no prueba de que un reentrenamiento ya se haya realizado ni una comparación controlada con el 25 de septiembre.

Pendiente: extraer la cobertura oficial y completar una evaluación temporal champion/candidato antes de decidir promoción. Cambiar el nombre de la versión no cuenta como entrenamiento.

Guía: https://github.com/uexternadojz/pulso-transmi/blob/main/docs/fase-drift.md

## Actualización de ejecución — 30 de septiembre

Se entrenó y aprobó `champion-2.0.0` tras comparar cuatro variantes y superar las reglas de promoción. Evidencia completa: [evaluación temporal](../reports/adaptation/README.md). El criterio de evaluar fue drift fuerte junto con deterioro observado; la persistencia por bloques de seis ciclos no se había automatizado. La decisión se respalda en la comparación reservada, no en asumir que toda alerta exige cambiar de modelo.
