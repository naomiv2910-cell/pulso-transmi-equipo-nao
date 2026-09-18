"""Análisis exploratorio reproducible del conjunto Pulso TransMi."""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
REPORT_DIR = ROOT / "reports"
FIGURES_DIR = REPORT_DIR / "figures"
TABLES_DIR = REPORT_DIR / "tables"
WEEKDAY_ORDER = [
    "lunes",
    "martes",
    "miércoles",
    "jueves",
    "viernes",
    "sábado",
    "domingo",
]
WEEKDAY_ES = {
    0: "lunes",
    1: "martes",
    2: "miércoles",
    3: "jueves",
    4: "viernes",
    5: "sábado",
    6: "domingo",
}


def configure_style() -> None:
    sns.set_theme(style="whitegrid", context="notebook")
    plt.rcParams.update(
        {
            "figure.figsize": (11, 6),
            "axes.titleweight": "bold",
            "axes.titlesize": 15,
            "axes.labelsize": 11,
            "figure.dpi": 130,
            "savefig.dpi": 180,
            "savefig.bbox": "tight",
        }
    )


def save_figure(filename: str) -> None:
    plt.tight_layout()
    plt.savefig(FIGURES_DIR / filename, facecolor="white")
    plt.close()


def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, dict]:
    required = ["stations.csv", "observations.csv", "context.csv", "metadata.json"]
    missing = [name for name in required if not (RAW_DIR / name).exists()]
    if missing:
        raise FileNotFoundError(
            "Faltan archivos en data/raw: " + ", ".join(missing) + ". Ejecuta primero src/download_data.py."
        )

    stations = pd.read_csv(RAW_DIR / "stations.csv", dtype={"station_id": "string"})
    observations = pd.read_csv(
        RAW_DIR / "observations.csv",
        dtype={"station_id": "string"},
        parse_dates=["observed_at"],
    )
    context = pd.read_csv(RAW_DIR / "context.csv", parse_dates=["observed_at"])
    metadata = json.loads((RAW_DIR / "metadata.json").read_text(encoding="utf-8"))
    return stations, observations, context, metadata


def quality_checks(
    stations: pd.DataFrame, observations: pd.DataFrame, context: pd.DataFrame, metadata: dict
) -> pd.DataFrame:
    expected_periods = int(metadata["periods_per_station"])
    station_counts = observations.groupby("station_id").size()
    expected_timestamps = pd.date_range(
        observations["observed_at"].min(),
        observations["observed_at"].max(),
        freq=f"{metadata['frequency_minutes']}min",
    )

    checks = [
        ("Filas de estaciones", len(stations), metadata["station_count"]),
        ("Filas de observaciones", len(observations), metadata["observation_rows"]),
        ("Filas de contexto", len(context), metadata["context_rows"]),
        ("Duplicados de estación", stations.duplicated("station_id").sum(), 0),
        (
            "Duplicados de observación",
            observations.duplicated(["station_id", "observed_at"]).sum(),
            0,
        ),
        ("Duplicados de contexto", context.duplicated("observed_at").sum(), 0),
        ("Nulos en estaciones", int(stations.isna().sum().sum()), 0),
        ("Nulos en observaciones", int(observations.isna().sum().sum()), 0),
        ("Nulos en contexto", int(context.isna().sum().sum()), 0),
        ("Demandas negativas", int((observations["demand"] < 0).sum()), 0),
        (
            "Estaciones con cantidad de periodos incorrecta",
            int((station_counts != expected_periods).sum()),
            0,
        ),
        (
            "Periodos ausentes en contexto",
            int(len(expected_timestamps.difference(context["observed_at"]))),
            0,
        ),
        (
            "IDs de observaciones sin catálogo",
            int((~observations["station_id"].isin(stations["station_id"])).sum()),
            0,
        ),
    ]
    result = pd.DataFrame(checks, columns=["validacion", "resultado", "esperado"])
    result["estado"] = result["resultado"].eq(result["esperado"]).map({True: "OK", False: "REVISAR"})
    return result


def prepare_analysis(
    stations: pd.DataFrame, observations: pd.DataFrame, context: pd.DataFrame
) -> pd.DataFrame:
    data = observations.merge(stations, on="station_id", how="left", validate="many_to_one")
    data = data.merge(context, on="observed_at", how="left", validate="many_to_one")
    data["hour"] = data["observed_at"].dt.hour
    data["date"] = data["observed_at"].dt.date
    data["weekday_number"] = data["observed_at"].dt.dayofweek
    data["weekday"] = pd.Categorical(
        data["weekday_number"].map(WEEKDAY_ES), categories=WEEKDAY_ORDER, ordered=True
    )
    data["day_type"] = data["weekday_number"].ge(5).map({True: "Fin de semana", False: "Día laboral"})
    data["rain"] = data["rain_mm"].gt(0).map({True: "Con lluvia", False: "Sin lluvia"})
    data["event"] = data["event_intensity"].gt(0).map({True: "Con evento", False: "Sin evento"})
    return data


def create_tables(data: pd.DataFrame, quality: pd.DataFrame) -> dict[str, pd.DataFrame]:
    station_summary = (
        data.groupby(["station_id", "station_name", "corridor"], as_index=False)
        .agg(
            observations=("demand", "size"),
            mean_demand=("demand", "mean"),
            median_demand=("demand", "median"),
            max_demand=("demand", "max"),
            std_demand=("demand", "std"),
        )
        .sort_values("mean_demand", ascending=False)
    )
    hourly_summary = (
        data.groupby(["day_type", "hour"], as_index=False)["demand"]
        .mean()
        .rename(columns={"demand": "mean_demand"})
    )
    weekday_summary = (
        data.groupby("weekday", observed=False, as_index=False)["demand"]
        .mean()
        .rename(columns={"demand": "mean_demand"})
    )
    context_summary = (
        data.groupby(["rain", "event"], as_index=False)["demand"]
        .agg(["count", "mean", "median", "std"])
        .reset_index()
    )

    tables = {
        "quality_checks.csv": quality,
        "station_summary.csv": station_summary,
        "hourly_summary.csv": hourly_summary,
        "weekday_summary.csv": weekday_summary,
        "context_summary.csv": context_summary,
    }
    for filename, table in tables.items():
        table.to_csv(TABLES_DIR / filename, index=False)
    return tables


def create_figures(data: pd.DataFrame, station_summary: pd.DataFrame) -> None:
    daily = data.groupby("date", as_index=False)["demand"].sum()
    plt.figure(figsize=(12, 5))
    sns.lineplot(data=daily, x="date", y="demand", color="#d81b60", linewidth=2)
    plt.title("Demanda total diaria en las 12 estaciones")
    plt.xlabel("Fecha")
    plt.ylabel("Demanda total")
    plt.xticks(rotation=35, ha="right")
    save_figure("01_demanda_diaria.png")

    hourly = data.groupby(["day_type", "hour"], as_index=False)["demand"].mean()
    plt.figure()
    sns.lineplot(
        data=hourly,
        x="hour",
        y="demand",
        hue="day_type",
        marker="o",
        palette=["#1769aa", "#d81b60"],
    )
    plt.title("Demanda promedio por hora")
    plt.xlabel("Hora del día")
    plt.ylabel("Demanda promedio por intervalo")
    plt.xticks(range(0, 24, 2))
    plt.legend(title="Tipo de día")
    save_figure("02_demanda_por_hora.png")

    by_station = station_summary.sort_values("mean_demand", ascending=True)
    plt.figure(figsize=(11, 7))
    sns.barplot(data=by_station, x="mean_demand", y="station_name", hue="corridor", dodge=False)
    plt.title("Demanda promedio por estación")
    plt.xlabel("Demanda promedio por intervalo")
    plt.ylabel("Estación")
    plt.legend(title="Corredor", bbox_to_anchor=(1.02, 1), loc="upper left")
    save_figure("03_demanda_por_estacion.png")

    weekday_hour = data.pivot_table(
        index="weekday", columns="hour", values="demand", aggfunc="mean", observed=False
    )
    plt.figure(figsize=(13, 5))
    sns.heatmap(weekday_hour, cmap="YlOrRd", linewidths=0.15, cbar_kws={"label": "Demanda promedio"})
    plt.title("Patrón de demanda por día y hora")
    plt.xlabel("Hora del día")
    plt.ylabel("Día de la semana")
    save_figure("04_mapa_calor_dia_hora.png")

    sampled = data.sample(min(12000, len(data)), random_state=42)
    plt.figure()
    sns.boxplot(
        data=sampled,
        x="rain",
        y="demand",
        hue="event",
        showfliers=False,
        palette=["#5c6bc0", "#ef6c00"],
    )
    plt.title("Demanda según lluvia y presencia de eventos")
    plt.xlabel("Condición de lluvia")
    plt.ylabel("Demanda por intervalo")
    plt.legend(title="Contexto")
    save_figure("05_demanda_lluvia_eventos.png")

    plt.figure()
    sns.scatterplot(
        data=data.sample(min(15000, len(data)), random_state=7),
        x="temperature_c",
        y="demand",
        hue="rain",
        alpha=0.25,
        s=20,
        palette=["#546e7a", "#1e88e5"],
    )
    plt.title("Demanda y temperatura observada")
    plt.xlabel("Temperatura (°C)")
    plt.ylabel("Demanda por intervalo")
    plt.legend(title="Lluvia")
    save_figure("06_demanda_temperatura.png")

    station_map = (
        data.groupby(["station_id", "station_name", "corridor", "latitude", "longitude"], as_index=False)
        ["demand"]
        .mean()
    )
    plt.figure(figsize=(9, 8))
    sns.scatterplot(
        data=station_map,
        x="longitude",
        y="latitude",
        size="demand",
        hue="corridor",
        sizes=(100, 700),
        alpha=0.8,
    )
    for row in station_map.itertuples():
        eastern_edge = row.longitude > -74.08
        plt.annotate(
            row.station_name,
            (row.longitude, row.latitude),
            xytext=(-6 if eastern_edge else 6, 4),
            textcoords="offset points",
            ha="right" if eastern_edge else "left",
            fontsize=8,
        )
    plt.title("Ubicación y demanda promedio de las estaciones")
    plt.xlabel("Longitud")
    plt.ylabel("Latitud")
    handles, labels = plt.gca().get_legend_handles_labels()
    labels = ["Corredor" if label == "corridor" else "Demanda promedio" if label == "demand" else label for label in labels]
    plt.legend(handles, labels, bbox_to_anchor=(1.02, 1), loc="upper left")
    save_figure("07_mapa_estaciones.png")


def write_report(
    data: pd.DataFrame,
    metadata: dict,
    quality: pd.DataFrame,
    tables: dict[str, pd.DataFrame],
) -> None:
    station_summary = tables["station_summary.csv"]
    hourly = data.groupby("hour")["demand"].mean().sort_values(ascending=False)
    weekday = data.groupby("weekday", observed=False)["demand"].mean().sort_values(ascending=False)
    busiest = station_summary.iloc[0]
    quietest = station_summary.iloc[-1]
    peak_hour = int(hourly.index[0])
    rain_means = data.groupby("rain")["demand"].mean()
    event_means = data.groupby("event")["demand"].mean()
    failed = int((quality["estado"] != "OK").sum())

    report = f"""# Análisis exploratorio de Pulso TransMi

## Alcance de los datos

- Periodo: {metadata['history_start']} a {metadata['history_end']}.
- Frecuencia: cada {metadata['frequency_minutes']} minutos.
- Estaciones: {metadata['station_count']}.
- Observaciones de demanda: {metadata['observation_rows']:,}.
- Registros de contexto: {metadata['context_rows']:,}.
- La demanda, el clima y los eventos son datos sintéticos suministrados por el reto.

## Calidad

Se ejecutaron {len(quality)} validaciones. Controles que requieren revisión: **{failed}**.
El detalle está en `reports/tables/quality_checks.csv`.

## Hallazgos principales

1. **Estaciones:** `{busiest['station_name']}` presenta la demanda promedio más alta ({busiest['mean_demand']:.1f}), mientras `{quietest['station_name']}` registra la menor ({quietest['mean_demand']:.1f}).
2. **Hora:** la mayor demanda promedio ocurre alrededor de las **{peak_hour}:00**.
3. **Día:** el día con mayor demanda promedio es **{weekday.index[0]}** ({weekday.iloc[0]:.1f} pasajeros por intervalo).
4. **Lluvia:** la demanda promedio es {rain_means.get('Con lluvia', float('nan')):.1f} con lluvia y {rain_means.get('Sin lluvia', float('nan')):.1f} sin lluvia. Esta comparación describe asociación y no causalidad.
5. **Eventos:** la demanda promedio es {event_means.get('Con evento', float('nan')):.1f} durante eventos y {event_means.get('Sin evento', float('nan')):.1f} sin eventos.

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
"""
    (REPORT_DIR / "eda_report.md").write_text(report, encoding="utf-8")


def main() -> None:
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    configure_style()
    stations, observations, context, metadata = load_data()
    quality = quality_checks(stations, observations, context, metadata)
    data = prepare_analysis(stations, observations, context)
    tables = create_tables(data, quality)
    create_figures(data, tables["station_summary.csv"])
    write_report(data, metadata, quality, tables)
    print(f"EDA terminado. Informe: {REPORT_DIR / 'eda_report.md'}")
    print(f"Validaciones: {(quality['estado'] == 'OK').sum()}/{len(quality)} OK")


if __name__ == "__main__":
    main()
