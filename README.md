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

## Fuente

- API: `https://pulso-transmi.72-60-245-2.sslip.io`
- Documentación: `https://pulso-transmi.72-60-245-2.sslip.io/docs`
- SDK oficial: `https://github.com/uexternadojz/pulso-transmi-sdk`

La demanda, el clima y los eventos del conjunto inicial son sintéticos. Los nombres y coordenadas de estaciones provienen de datos oficiales de TransMilenio, según los metadatos del SDK.
