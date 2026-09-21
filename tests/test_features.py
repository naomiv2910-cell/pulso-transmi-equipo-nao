from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from features import FEATURE_COLUMNS, add_origin_features, build_target_features, normalize_station_ids


def history(rows: int = 700) -> tuple[pd.DataFrame, pd.DataFrame]:
    timestamps = pd.date_range("2026-09-01", periods=rows, freq="15min", tz="UTC")
    observations = pd.DataFrame(
        {"station_id": "02300", "observed_at": timestamps, "demand": np.arange(rows) + 10}
    )
    context = pd.DataFrame(
        {
            "observed_at": timestamps,
            "rain_mm": 0.0,
            "rain_forecast": 0.0,
            "temperature_c": 18.0,
            "temperature_forecast": 18.5,
            "event_intensity": 0.0,
        }
    )
    return observations, context


def test_station_id_keeps_leading_zeroes() -> None:
    result = normalize_station_ids(pd.Series(["02300", "2300"]))
    assert result.tolist() == ["02300", "02300"]


def test_feature_construction_matches_training_columns() -> None:
    observations, context = history()
    frame = observations.merge(context, on="observed_at")
    featured = add_origin_features(frame)
    assert set(FEATURE_COLUMNS).issubset(featured.columns)
    assert featured.iloc[-1][FEATURE_COLUMNS].notna().all()


def test_target_features_are_built_at_cutoff() -> None:
    observations, context = history()
    cutoff = observations["observed_at"].iloc[-1]
    targets = [
        {
            "station_id": "02300",
            "target_at": (cutoff + pd.Timedelta(horizon, unit="minutes")).isoformat(),
            "horizon_minutes": horizon,
        }
        for horizon in (15, 30, 45, 60)
    ]
    result = build_target_features(observations, context, targets, cutoff.isoformat())
    assert len(result) == 4
    assert result[FEATURE_COLUMNS].notna().all().all()


def test_target_origin_must_equal_cutoff() -> None:
    observations, context = history()
    cutoff = observations["observed_at"].iloc[-1]
    targets = [{"station_id": "02300", "target_at": cutoff.isoformat(), "horizon_minutes": 15}]
    with pytest.raises(ValueError, match="data_cutoff"):
        build_target_features(observations, context, targets, cutoff.isoformat())
