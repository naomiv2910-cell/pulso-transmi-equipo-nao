"""Migra el corte inicial mediante la API con una clave de servicio del servidor.

Variables requeridas:
  SUPABASE_URL
  SUPABASE_SERVICE_ROLE_KEY

La clave de servicio nunca debe usarse en el navegador ni guardarse en Git.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import httpx
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
BATCH_SIZE = 1000


def require_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"Falta la variable de entorno {name}")
    return value


def upsert_batches(client: httpx.Client, table: str, rows: list[dict], conflict: str) -> int:
    processed = 0
    for start in range(0, len(rows), BATCH_SIZE):
        batch = rows[start : start + BATCH_SIZE]
        response = client.post(
            f"/rest/v1/{table}",
            params={"on_conflict": conflict},
            headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
            json=batch,
        )
        response.raise_for_status()
        processed += len(batch)
        print(f"{table}: {processed:,}/{len(rows):,}")
    return processed


def main() -> None:
    url = require_env("SUPABASE_URL").rstrip("/")
    key = require_env("SUPABASE_SERVICE_ROLE_KEY")
    metadata = json.loads((RAW / "metadata.json").read_text(encoding="utf-8"))

    stations = pd.read_csv(RAW / "stations.csv", dtype={"station_id": "string"}).to_dict(orient="records")
    observations = pd.read_csv(
        RAW / "observations.csv", dtype={"station_id": "string"}
    ).to_dict(orient="records")
    context = pd.read_csv(RAW / "context.csv").to_dict(orient="records")

    headers = {"apikey": key, "Authorization": f"Bearer {key}"}
    with httpx.Client(base_url=url, headers=headers, timeout=60) as client:
        snapshot = {
            "dataset_name": metadata["dataset"],
            "generated_at": metadata["generated_at"],
            "history_start": metadata["history_start"],
            "history_end": metadata["history_end"],
            "frequency_minutes": metadata["frequency_minutes"],
            "station_count": metadata["station_count"],
            "observation_rows": metadata["observation_rows"],
            "context_rows": metadata["context_rows"],
            "metadata": metadata,
        }
        response = client.post(
            "/rest/v1/dataset_snapshots",
            params={"on_conflict": "dataset_name,generated_at"},
            headers={"Prefer": "resolution=merge-duplicates,return=representation"},
            json=snapshot,
        )
        response.raise_for_status()
        snapshot_id = response.json()[0]["id"]

        upsert_batches(client, "stations", stations, "station_id")
        for row in observations:
            row["snapshot_id"] = snapshot_id
        for row in context:
            row["snapshot_id"] = snapshot_id
        upsert_batches(client, "observations", observations, "station_id,observed_at")
        upsert_batches(client, "context_observations", context, "observed_at")

    print("Migración terminada.")


if __name__ == "__main__":
    main()
