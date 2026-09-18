# Análisis exploratorio de Pulso TransMi

## Alcance de los datos

- Periodo: 2026-07-26T00:00:00-05:00 a 2026-09-08T23:45:00-05:00.
- Frecuencia: cada 15 minutos.
- Estaciones: 12.
- Observaciones de demanda: 51,840.
- Registros de contexto: 4,320.
- La demanda, el clima y los eventos son datos sintéticos suministrados por el reto.

## Calidad

Se ejecutaron 13 validaciones. Controles que requieren revisión: **0**.
El detalle está en `reports/tables/quality_checks.csv`.

## Hallazgos principales

1. **Estaciones:** `Ricaurte - NQS` presenta la demanda promedio más alta (683.7), mientras `Portal Usme` registra la menor (217.9).
2. **Hora:** la mayor demanda promedio ocurre alrededor de las **17:00**.
3. **Día:** el día con mayor demanda promedio es **martes** (382.8 pasajeros por intervalo).
4. **Lluvia:** la demanda promedio es 353.4 con lluvia muy baja, 370.4 con lluvia moderada y 343.8 con lluvia alta. Esta comparación describe asociación y no causalidad.
5. **Eventos:** usando intensidad mayor que 0,1 para identificar un evento activo, la demanda promedio es 420.1 con evento y 352.8 sin evento activo.

## Implicaciones para el modelo

- Incluir estación, corredor, hora, día de la semana y tipo de día.
- Crear rezagos de demanda de 15 minutos, 1 hora, 1 día y 1 semana.
- Añadir lluvia, temperatura e intensidad de eventos como variables externas.
- Validar en orden temporal; no usar una partición aleatoria.
- Comparar cualquier modelo con baselines diarios y semanales.

## Figuras

1. `00_distribucion_demanda.png`: distribución de la variable objetivo.
2. `01_demanda_diaria.png`: evolución diaria total.
3. `02_demanda_por_hora.png`: patrón horario por tipo de día.
4. `03_demanda_por_estacion.png`: comparación de estaciones.
5. `04_mapa_calor_dia_hora.png`: intensidad por día y hora.
6. `05_demanda_lluvia_eventos.png`: demanda por condiciones de contexto.
7. `06_demanda_temperatura.png`: relación entre temperatura y demanda.
8. `07_mapa_estaciones.png`: ubicación y demanda promedio.
9. `08_correlaciones.png`: correlaciones lineales entre demanda y contexto.
