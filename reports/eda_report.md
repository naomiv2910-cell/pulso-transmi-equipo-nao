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
4. **Lluvia:** la demanda promedio es 356.8 con lluvia y 127.7 sin lluvia. Esta comparación describe asociación y no causalidad.
5. **Eventos:** la demanda promedio es 361.1 durante eventos y 317.6 sin eventos.

## Implicaciones para el modelo

- Incluir estación, corredor, hora, día de la semana y tipo de día.
- Crear rezagos de demanda de 15 minutos, 1 hora, 1 día y 1 semana.
- Añadir lluvia, temperatura e intensidad de eventos como variables externas.
- Validar en orden temporal; no usar una partición aleatoria.
- Comparar cualquier modelo con baselines diarios y semanales.

## Figuras

1. `01_demanda_diaria.png`: evolución diaria total.
2. `02_demanda_por_hora.png`: patrón horario por tipo de día.
3. `03_demanda_por_estacion.png`: comparación de estaciones.
4. `04_mapa_calor_dia_hora.png`: intensidad por día y hora.
5. `05_demanda_lluvia_eventos.png`: demanda por condiciones de contexto.
6. `06_demanda_temperatura.png`: relación entre temperatura y demanda.
7. `07_mapa_estaciones.png`: ubicación y demanda promedio.
