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

Requiere Python 3.12. El artefacto champion fue creado con scikit-learn 1.8 y
debe cargarse con la versión acotada en `requirements.txt`.

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

La migración inicial ya fue aplicada y no forma parte del pipeline de
predicción. `src/migrate_supabase.py` se conserva únicamente para un despliegue
nuevo y deliberado; sus credenciales deben inyectarse desde un gestor de
secretos, nunca escribirse en el repositorio.

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

Para producción, `artifacts/champion.joblib` contiene en un solo archivo los
cuatro modelos correspondientes a los horizontes de 15, 30, 45 y 60 minutos,
junto con sus variables, versiones y métricas de validación.

## Predicción segura y submission

La CLI consulta siempre el reloj y el ciclo autoritativos. Su comportamiento
predeterminado es `dry-run`: construir, validar y guardar el payload nunca
implica enviarlo.

```bash
python src/predict.py --status
python src/predict.py --dry-run
python src/predict.py --check-auth
python src/predict.py --submit
```

- `--status` valida el OpenAPI actual y muestra reloj y ciclo.
- `--dry-run` descarga únicamente la historia de las estaciones solicitadas,
  incorpora el stream incremental, construye las mismas variables del
  entrenamiento y guarda el JSON en `artifacts/submissions/`.
- `--check-auth` requiere `PULSO_API_KEY` y consulta `/v1/me` sin mostrar la
  credencial.
- `--submit` requiere la API key, muestra el resumen y pide escribir `SUBMIT`
  inmediatamente antes del POST. En automatización también exige `--yes`.

Si el reloj responde `waiting` o no existe un ciclo abierto, todos los modos de
estado/predicción terminan correctamente sin enviar nada. Los objetivos,
timestamps y horizontes proceden exclusivamente de
`/v1/forecast-cycles/current`; no se inventan valores de competencia.

La `Idempotency-Key` es estable: SHA-256 de ciclo, versión del modelo y commit.
Repetir exactamente la misma ejecución reutiliza la llave; cambiar cualquiera
de esos componentes produce otra. Los payloads y recibos locales están
ignorados por Git y nunca contienen headers de autorización.

### Variables de entorno

Copia `.env.example` solo si necesitas una referencia, pero no confirmes un
archivo `.env`. Para una sesión local, exporta las variables desde una entrada
oculta o desde tu gestor de secretos:

```bash
read -s "PULSO_API_KEY?API key: "
echo
export PULSO_API_KEY
```

La persistencia en Supabase es opcional durante el desarrollo local. Cuando
`SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` están disponibles, una submission
aceptada registra la ejecución, ciclo, modelo y predicciones en las tablas ya
existentes. Si faltan, el `dry-run` continúa con un aviso. La clave
`service_role` se usa únicamente en procesos de servidor o GitHub Actions,
nunca en frontend.

### Pruebas

Las solicitudes de los tests están mockeadas y jamás envían predicciones:

```bash
python -m pytest -q
```

## GitHub Actions

El workflow manual está en `.github/workflows/pipeline.yml`. En la pestaña
**Actions**, selecciona **Run workflow** y deja `dry-run` (valor
predeterminado). `submit` solo debe elegirse después de revisar el ciclo y el
resumen.

Configura los secretos sin escribir sus valores en archivos o comandos visibles:

```bash
gh secret set PULSO_API_KEY
gh secret set SUPABASE_URL
gh secret set SUPABASE_SERVICE_ROLE_KEY
```

Cada ejecución instala dependencias, corre las pruebas, consulta el estado y
ejecuta el modo elegido. Mientras el reloj esté en `waiting`, termina con éxito
sin POST. No se habilita `schedule` hasta que el profesor publique la frecuencia.

Para revisar una ejecución, abre **Actions**, selecciona
`pulso-transmi-pipeline` y consulta los pasos. Después de una entrega aceptada,
la CLI guarda el `submission_id` y consulta
`GET /v1/submissions/{submission_id}` con la misma API key.

## Fuente

- API: `https://pulso-transmi.72-60-245-2.sslip.io`
- Documentación: `https://pulso-transmi.72-60-245-2.sslip.io/docs`
- SDK oficial: `https://github.com/uexternadojz/pulso-transmi-sdk`

La demanda, el clima y los eventos del conjunto inicial son sintéticos. Los nombres y coordenadas de estaciones provienen de datos oficiales de TransMilenio, según los metadatos del SDK.
