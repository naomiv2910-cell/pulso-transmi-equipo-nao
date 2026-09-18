"""Entrena y evalúa modelos de demanda para horizontes de 15 a 60 minutos.

La validación es estrictamente temporal: los últimos siete días se reservan
como futuro simulado. Se comparan tres baselines con Gradient Boosting y se
guardan modelos, predicciones y métricas reproducibles.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import joblib
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
ARTIFACTS = ROOT / "artifacts"
TABLES = ROOT / "reports" / "tables"
FIGURES = ROOT / "reports" / "figures"
HORIZONS = (1, 2, 3, 4)  # intervalos de 15 minutos
LAGS = (1, 4, 8, 12, 96, 192, 672)


def load_frame() -> pd.DataFrame:
    observations = pd.read_csv(RAW / "observations.csv", dtype={"station_id": "string"})
    context = pd.read_csv(RAW / "context.csv")
    observations["observed_at"] = pd.to_datetime(observations["observed_at"], utc=True)
    context["observed_at"] = pd.to_datetime(context["observed_at"], utc=True)
    frame = observations.merge(context, on="observed_at", how="left", validate="many_to_one")
    return frame.sort_values(["station_id", "observed_at"]).reset_index(drop=True)


def add_origin_features(frame: pd.DataFrame) -> pd.DataFrame:
    data = frame.copy()
    grouped = data.groupby("station_id", sort=False)["demand"]
    for lag in LAGS:
        data[f"lag_{lag}"] = grouped.shift(lag)

    # shift(1) impide que el promedio incluya la demanda del instante objetivo.
    past = grouped.shift(1)
    for window in (4, 12, 96):
        data[f"rolling_mean_{window}"] = (
            past.groupby(data["station_id"]).rolling(window, min_periods=window).mean()
            .reset_index(level=0, drop=True)
        )

    bogota_time = data["observed_at"].dt.tz_convert("America/Bogota")
    data["hour_sin"] = np.sin(2 * np.pi * (bogota_time.dt.hour * 4 + bogota_time.dt.minute / 15) / 96)
    data["hour_cos"] = np.cos(2 * np.pi * (bogota_time.dt.hour * 4 + bogota_time.dt.minute / 15) / 96)
    data["week_sin"] = np.sin(2 * np.pi * bogota_time.dt.dayofweek / 7)
    data["week_cos"] = np.cos(2 * np.pi * bogota_time.dt.dayofweek / 7)
    data["is_weekend"] = (bogota_time.dt.dayofweek >= 5).astype(int)
    return data


def mean_station_metrics(frame: pd.DataFrame, prediction_col: str) -> tuple[float, float, float]:
    scores = []
    for _, group in frame.groupby("station_id"):
        actual = group["target"].to_numpy()
        predicted = group[prediction_col].to_numpy()
        wape = np.abs(actual - predicted).sum() / actual.sum()
        mae = np.abs(actual - predicted).mean()
        scores.append((wape, mae))
    mean_wape = float(np.mean([score[0] for score in scores]))
    return mean_wape, 100 * max(0.0, 1.0 - mean_wape), float(np.mean([score[1] for score in scores]))


def train_horizon(data: pd.DataFrame, horizon: int, cutoff: pd.Timestamp) -> tuple[list[dict], pd.DataFrame]:
    work = data.copy()
    grouped = work.groupby("station_id", sort=False)["demand"]
    work["target"] = grouped.shift(-horizon)
    work["target_at"] = work["observed_at"] + pd.Timedelta(minutes=15 * horizon)

    # Baselines disponibles en el origen para el instante que se pronostica.
    work["baseline_last"] = work["demand"]
    work["baseline_daily"] = grouped.shift(96 - horizon)
    work["baseline_weekly"] = grouped.shift(672 - horizon)

    numeric = [f"lag_{lag}" for lag in LAGS] + [
        "rolling_mean_4", "rolling_mean_12", "rolling_mean_96",
        "rain_mm", "rain_forecast", "temperature_c", "temperature_forecast",
        "event_intensity", "hour_sin", "hour_cos", "week_sin", "week_cos", "is_weekend",
    ]
    required = numeric + ["station_id", "target", "target_at", "baseline_daily", "baseline_weekly"]
    work = work.dropna(subset=required).copy()
    train = work[work["target_at"] < cutoff].copy()
    valid = work[work["target_at"] >= cutoff].copy()

    preprocessor = ColumnTransformer(
        [("station", OneHotEncoder(handle_unknown="ignore", sparse_output=False), ["station_id"])],
        remainder="passthrough",
    )
    model = Pipeline([
        ("features", preprocessor),
        ("regressor", HistGradientBoostingRegressor(
            learning_rate=0.08, max_iter=250, max_leaf_nodes=31,
            min_samples_leaf=30, l2_regularization=1.0, random_state=42,
        )),
    ])
    feature_columns = ["station_id"] + numeric
    model.fit(train[feature_columns], train["target"])
    valid["gradient_boosting"] = np.clip(model.predict(valid[feature_columns]), 0, None)

    version = f"h{horizon}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    joblib.dump(
        {"model": model, "features": feature_columns, "horizon_steps": horizon,
         "trained_until": cutoff.isoformat(), "version": version},
        ARTIFACTS / f"model_h{horizon}.joblib",
    )

    metrics = []
    for name in ("baseline_last", "baseline_daily", "baseline_weekly", "gradient_boosting"):
        wape, accuracy, mae = mean_station_metrics(valid, name)
        metrics.append({
            "horizon_minutes": 15 * horizon, "model": name,
            "mean_station_wape": wape, "accuracy_pct": accuracy, "mae": mae,
            "train_rows": len(train), "validation_rows": len(valid), "version": version,
        })
    columns = ["target_at", "station_id", "target", "baseline_last", "baseline_daily",
               "baseline_weekly", "gradient_boosting"]
    valid = valid[columns].copy()
    valid["horizon_minutes"] = 15 * horizon
    return metrics, valid


def main() -> None:
    data = add_origin_features(load_frame())
    cutoff = data["observed_at"].max() - pd.Timedelta(days=7) + pd.Timedelta(minutes=15)
    all_metrics: list[dict] = []
    predictions = []
    for horizon in HORIZONS:
        metrics, valid = train_horizon(data, horizon, cutoff)
        all_metrics.extend(metrics)
        predictions.append(valid)

    metrics_frame = pd.DataFrame(all_metrics)
    predictions_frame = pd.concat(predictions, ignore_index=True)
    TABLES.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    metrics_frame.to_csv(TABLES / "model_metrics.csv", index=False)
    predictions_frame.to_csv(TABLES / "validation_predictions.csv", index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "validation_start": cutoff.isoformat(),
        "validation_end": data["observed_at"].max().isoformat(),
        "frequency_minutes": 15,
        "horizons_minutes": [15, 30, 45, 60],
        "champion_by_horizon": {},
    }
    for horizon, group in metrics_frame.groupby("horizon_minutes"):
        winner = group.loc[group["mean_station_wape"].idxmin()]
        summary["champion_by_horizon"][str(horizon)] = {
            "model": winner["model"], "wape": winner["mean_station_wape"],
            "accuracy_pct": winner["accuracy_pct"], "mae": winner["mae"],
        }
    (ARTIFACTS / "training_summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Artefacto único para producción: permite cargar una sola vez los cuatro
    # modelos y seleccionar el horizonte requerido durante la inferencia.
    packaged_models = {}
    for horizon in HORIZONS:
        artifact = joblib.load(ARTIFACTS / f"model_h{horizon}.joblib")
        packaged_models[15 * horizon] = artifact
    joblib.dump(
        {
            "artifact_type": "pulso_transmi_champion",
            "artifact_version": "1.0.0",
            "created_at": summary["generated_at"],
            "frequency_minutes": 15,
            "horizons_minutes": list(packaged_models),
            "validation_start": summary["validation_start"],
            "validation_end": summary["validation_end"],
            "champion_by_horizon": summary["champion_by_horizon"],
            "models": packaged_models,
        },
        ARTIFACTS / "champion.joblib",
        compress=3,
    )

    pivot = metrics_frame.pivot(index="horizon_minutes", columns="model", values="accuracy_pct")
    ax = pivot.plot(kind="bar", figsize=(11, 6), color=["#b8b8b8", "#f4a6c1", "#d6b3e8", "#6c4ab6"])
    ax.set(title="Comparación temporal de modelos", xlabel="Horizonte (minutos)", ylabel="Accuracy (%)")
    ax.legend(title="Modelo")
    ax.grid(axis="y", alpha=0.25)
    plt.tight_layout()
    plt.savefig(FIGURES / "09_comparacion_modelos.png", dpi=180)
    plt.close()

    print(metrics_frame.sort_values(["horizon_minutes", "mean_station_wape"]).to_string(index=False))
    print(f"\nValidación desde {cutoff.isoformat()}")
    print(f"Resultados guardados en {TABLES.relative_to(ROOT)} y {ARTIFACTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
