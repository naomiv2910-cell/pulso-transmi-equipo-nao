# Pulso TransMi — Equipo Nao

Sistema MLOps para pronosticar la demanda de pasajeros de TransMilenio. Esta primera fase descarga el conjunto inicial del API oficial y genera un análisis exploratorio reproducible.

## Estructura

```text
data/raw/          Datos originales descargados del API (no se modifican)
reports/figures/   Gráficas generadas por el EDA
reports/tables/    Tablas resumen y controles de calidad
src/               Scripts reproducibles
```

## Preparación en Windows PowerShell

Requiere Python 3.11 o superior.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

Si PowerShell bloquea la activación, ejecuta una vez en esa ventana:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.venv\Scripts\Activate.ps1
```

## Descargar los datos

```powershell
python src/download_data.py
```

El script descarga `stations.csv`, `observations.csv`, `context.csv` y `metadata.json`. Después compara el SHA-256 de cada CSV con el publicado por el API.

## Ejecutar el análisis exploratorio

```powershell
python src/eda.py
```

El resultado principal queda en [`reports/eda_report.md`](reports/eda_report.md). Las gráficas y tablas se regeneran automáticamente a partir de los datos originales.

## Base de datos en Supabase

El esquema de producción contiene nueve tablas:

| Tabla | Función |
|---|---|
| `dataset_snapshots` | Versiones y metadatos de cada corte de datos |
| `stations` | Catálogo geográfico de estaciones |
| `observations` | Demanda real por estación e intervalo |
| `context_observations` | Clima y eventos por intervalo |
| `pipeline_runs` | Historial de ejecuciones y errores |
| `model_versions` | Modelos, parámetros, métricas y champion |
| `forecast_cycles` | Ciclos abiertos y cerrados de predicción |
| `predictions` | Pronósticos por estación y horizonte |
| `evaluation_metrics` | WAPE, accuracy, MAE, RMSE y drift |

Las migraciones SQL están en `supabase/migrations/`. Las tablas tienen RLS activo y no exponen acceso directo a `anon` ni `authenticated`. Los procesos administrativos deben ejecutarse desde un servidor o GitHub Actions con la clave de servicio almacenada como secreto.

Para repetir la migración inicial:

```powershell
Copy-Item .env.example .env
# Completa .env sin subirlo a Git.
$env:SUPABASE_URL="https://TU_PROJECT_REF.supabase.co"
$env:SUPABASE_SERVICE_ROLE_KEY="TU_CLAVE_DE_SERVICIO"
python src/migrate_supabase.py
```

La carga usa `upsert`, por lo que repetirla actualiza las filas existentes y no duplica las observaciones.

## Entrenar y comparar modelos

El entrenamiento reserva los últimos siete días como validación temporal y
compara tres baselines con Gradient Boosting para horizontes de 15, 30, 45 y
60 minutos:

```powershell
python src/train.py
```

Los modelos quedan en `artifacts/`; las métricas y predicciones de validación
en `reports/tables/`, y la gráfica comparativa en
`reports/figures/09_comparacion_modelos.png`.

## Fuente

- API: `https://pulso-transmi.72-60-245-2.sslip.io`
- Documentación: `https://pulso-transmi.72-60-245-2.sslip.io/docs`
- SDK oficial: `https://github.com/uexternadojz/pulso-transmi-sdk`

La demanda, el clima y los eventos del conjunto inicial son sintéticos. Los nombres y coordenadas de estaciones provienen de datos oficiales de TransMilenio, según los metadatos del SDK.
