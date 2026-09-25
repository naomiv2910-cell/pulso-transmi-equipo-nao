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

`watch-cycles.yml` mantiene la vigilancia en la nube: consulta el ciclo cada
60 segundos mientras el runner está activo. Cuando aparece un ciclo pendiente,
ejecuta la inferencia y entrega sus targets exactos. No requiere mantener el Mac
encendido. La inferencia tarda más que una consulta; no es un envío instantáneo
al segundo exacto de apertura.

Cada turno dura 45 minutos y, al terminar, activa el siguiente mediante
`workflow_dispatch` con el token temporal del propio repositorio y permiso
`actions: write`. Un cron cada 10 minutos queda como respaldo. Todos los workflows
comparten `concurrency` para evitar entregas simultáneas. Las colas de GitHub,
caídas de la API o un fallo de renovación aún pueden producir huecos: no hay una
garantía absoluta de disponibilidad. Revisar recibos y cobertura, no solo checks.

La clave `PULSO_API_KEY` sigue únicamente en Actions Secrets, junto con
`SUPABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY`. El token de renovación solo se
expone al paso que activa el siguiente workflow.

Se guardan el payload pendiente, su clave idempotente, el recibo y una marca de
aceptación por ciclo. Los reintentos reutilizan exactamente el payload pendiente,
incluso después de un cambio de commit. La aceptación se registra antes de
persistir métricas, para no repetir un envío si falla ese paso posterior. El diario
se transfiere entre runners mediante Actions cache y se respalda en artifacts.
Una caché expulsada puede obligar a usar la protección idempotente del servidor.
No hay credenciales en el diario.

Para iniciar: **Actions → Vigilancia continua de ciclos → Run workflow**.
El input `minutes` permite un primer turno corto para verificar la renovación;
los siguientes duran 45 minutos. Para detenerlo, establecer la variable de
repositorio `PULSO_WATCH_ENABLED=false` y cancelar la ejecución activa. El cierre
predeterminado es el 30 de septiembre de 2026 a medianoche de Bogotá
(`2026-10-01T05:00:00Z`); `PULSO_WATCH_UNTIL` permite cambiarlo si el profesor
extiende la competencia. Deshabilitar el workflow al terminar para quitar el cron.

`pipeline.yml` conserva los modos manuales `dry-run`, `submit`, `reconcile`,
`ingest`, `evaluate` y `monitor`. El valor predeterminado sigue siendo `dry-run`.
Comparte el diario y la exclusión mutua con el watcher; una ejecución manual puede
esperar a que termine el turno activo.

## Operación MLOps

Todos los comandos operativos son `dry-run` por defecto y usan credenciales
solo desde variables de entorno del servidor:

```bash
python src/reconcile_submission.py --submission-id ID --dry-run
python src/ingest.py --status
python src/ingest.py --dry-run
python src/evaluate.py --dry-run
python src/monitor.py --dry-run
python src/backtest.py
```

`reconcile_submission.py` consulta por GET el recibo aceptado, exige el payload
original y verifica las 48 predicciones antes de cualquier upsert. Nunca llama
al endpoint de creación de submissions. La ingesta conserva cursores, detecta
repeticiones y escribe por claves naturales; evaluación une estación y timestamp
exactos; monitoreo emite `healthy`, `warning`, `retrain_recommended` o
`insufficient_data`.

El backtesting usa tres ventanas expansivas de siete días. Gradient Boosting
obtuvo accuracy promedio de **86,11 %** (desviación 0,50 pp) y WAPE medio por
estación de **14,26 %**, superando a los tres baselines en los 12 cruces de fold
y horizonte. Consulta `reports/backtest_report.md` y
`docs/retraining-policy.md`.

El workflow manual ofrece `dry-run`, `submit`, `reconcile`, `ingest`, `evaluate`
y `monitor`. El watcher automático usa `submit`; todas las ejecuciones comparten el
mismo grupo de `concurrency` para evitar envíos simultáneos.

## Fuente

- API: `https://pulso-transmi.72-60-245-2.sslip.io`
- Documentación: `https://pulso-transmi.72-60-245-2.sslip.io/docs`
- SDK oficial: `https://github.com/uexternadojz/pulso-transmi-sdk`

La demanda, el clima y los eventos del conjunto inicial son sintéticos. Los nombres y coordenadas de estaciones provienen de datos oficiales de TransMilenio, según los metadatos del SDK.


### Compatibilidad de la API y frecuencia efectiva

El despliegue público puede carecer de `GET /v1/submissions/current`, aunque
la guía lo documente. Si devuelve `submission_not_found`, el cliente confirma
la ausencia de esa ruta en OpenAPI antes de continuar con la llave idempotente
estable. Otros errores no se ignoran. El diario conserva las entregas aceptadas
y los payloads pendientes entre los turnos del watcher.

El cron de respaldo corre en los minutos 3, 13, 23, 33, 43 y 53.
GitHub no garantiza la frecuencia efectiva: verifica los horarios en Actions y
los recibos, no solo el check verde. Un run sin ciclo abierto no es una entrega.
