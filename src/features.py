"""Feature engineering shared by training and production inference."""

from __future__ import annotations

import numpy as np
import pandas as pd


LAGS = (1, 4, 8, 12, 96, 192, 672)
ROLLING_WINDOWS = (4, 12, 96)
CONTEXT_COLUMNS = (
    "rain_mm",
    "rain_forecast",
    "temperature_c",
    "temperature_forecast",
    "event_intensity",
)
NUMERIC_FEATURES = [f"lag_{lag}" for lag in LAGS] + [
    "rolling_mean_4",
    "rolling_mean_12",
    "rolling_mean_96",
    *CONTEXT_COLUMNS,
    "hour_sin",
    "hour_cos",
    "week_sin",
    "week_cos",
    "is_weekend",
]
FEATURE_COLUMNS = ["station_id", *NUMERIC_FEATURES]


def normalize_station_ids(series: pd.Series) -> pd.Series:
    """Return station identifiers as five-character strings."""
    values = series.astype("string").str.strip()
    if values.str.fullmatch(r"\d{1,5}").fillna(False).all():
        values = values.str.zfill(5)
    if not values.str.fullmatch(r"\d{5}").fillna(False).all():
        raise ValueError("station_id debe contener exactamente cinco dígitos")
    return values


def add_origin_features(frame: pd.DataFrame) -> pd.DataFrame:
    """Build the exact causal features used by every persisted model."""
    data = frame.copy()
    data["station_id"] = normalize_station_ids(data["station_id"])
    data["observed_at"] = pd.to_datetime(data["observed_at"], utc=True)
    data = data.sort_values(["station_id", "observed_at"]).reset_index(drop=True)
    grouped = data.groupby("station_id", sort=False)["demand"]
    for lag in LAGS:
        data[f"lag_{lag}"] = grouped.shift(lag)

    past = grouped.shift(1)
    for window in ROLLING_WINDOWS:
        data[f"rolling_mean_{window}"] = (
            past.groupby(data["station_id"])
            .rolling(window, min_periods=window)
            .mean()
            .reset_index(level=0, drop=True)
        )

    bogota_time = data["observed_at"].dt.tz_convert("America/Bogota")
    quarter = bogota_time.dt.hour * 4 + bogota_time.dt.minute / 15
    data["hour_sin"] = np.sin(2 * np.pi * quarter / 96)
    data["hour_cos"] = np.cos(2 * np.pi * quarter / 96)
    data["week_sin"] = np.sin(2 * np.pi * bogota_time.dt.dayofweek / 7)
    data["week_cos"] = np.cos(2 * np.pi * bogota_time.dt.dayofweek / 7)
    data["is_weekend"] = (bogota_time.dt.dayofweek >= 5).astype(int)
    return data


def build_target_features(
    observations: pd.DataFrame,
    context: pd.DataFrame,
    targets: list[dict],
    data_cutoff: str,
) -> pd.DataFrame:
    """Create one feature row for each requested target without future leakage."""
    if not targets:
        raise ValueError("El ciclo no contiene objetivos")

    obs = observations.copy()
    obs["station_id"] = normalize_station_ids(obs["station_id"])
    obs["observed_at"] = pd.to_datetime(obs["observed_at"], utc=True)
    obs["demand"] = pd.to_numeric(obs["demand"], errors="raise")
    obs = obs.drop_duplicates(["station_id", "observed_at"], keep="last")

    cutoff = pd.Timestamp(data_cutoff)
    if cutoff.tzinfo is None:
        raise ValueError("data_cutoff debe incluir zona horaria")
    cutoff = cutoff.tz_convert("UTC")
    obs = obs[obs["observed_at"] <= cutoff].copy()

    ctx = context.copy()
    ctx["observed_at"] = pd.to_datetime(ctx["observed_at"], utc=True)
    ctx = ctx.sort_values("observed_at").drop_duplicates("observed_at", keep="last")
    missing_context = [column for column in CONTEXT_COLUMNS if column not in ctx]
    if missing_context:
        raise ValueError(f"Faltan variables de contexto: {', '.join(missing_context)}")

    target_rows = pd.DataFrame(targets)
    target_rows["station_id"] = normalize_station_ids(target_rows["station_id"])
    target_rows["target_at"] = pd.to_datetime(target_rows["target_at"], utc=True)
    target_rows["horizon_minutes"] = pd.to_numeric(
        target_rows["horizon_minutes"], errors="raise"
    ).astype(int)
    target_rows["origin_at"] = target_rows["target_at"] - pd.to_timedelta(
        target_rows["horizon_minutes"], unit="m"
    )
    if not (target_rows["origin_at"] == cutoff).all():
        raise ValueError("Cada target debe originarse exactamente en data_cutoff")

    origins = target_rows[["station_id", "origin_at"]].drop_duplicates().rename(
        columns={"origin_at": "observed_at"}
    )
    existing = obs.merge(origins, on=["station_id", "observed_at"], how="inner")
    missing_origins = origins.merge(
        existing[["station_id", "observed_at"]],
        on=["station_id", "observed_at"],
        how="left",
        indicator=True,
    )
    missing_origins = missing_origins[missing_origins["_merge"] == "left_only"].drop(
        columns="_merge"
    )
    if not missing_origins.empty:
        missing_origins["demand"] = np.nan
        obs = pd.concat([obs, missing_origins], ignore_index=True)

    frame = obs.merge(ctx, on="observed_at", how="left", validate="many_to_one")
    # The public API currently exposes context as a static series. For a later
    # cutoff, use only the latest context already released (never future rows).
    frame = frame.sort_values(["station_id", "observed_at"])
    frame[list(CONTEXT_COLUMNS)] = frame.groupby("station_id", sort=False)[
        list(CONTEXT_COLUMNS)
    ].ffill()
    featured = add_origin_features(frame)
    selected = featured.merge(
        origins,
        on=["station_id", "observed_at"],
        how="inner",
        validate="one_to_one",
    )
    selected = target_rows.merge(
        selected,
        left_on=["station_id", "origin_at"],
        right_on=["station_id", "observed_at"],
        how="left",
        validate="many_to_one",
    )
    if selected[FEATURE_COLUMNS].isna().any().any():
        columns = selected[FEATURE_COLUMNS].columns[
            selected[FEATURE_COLUMNS].isna().any()
        ].tolist()
        raise ValueError(f"Historia insuficiente para construir: {', '.join(columns)}")
    return selected
