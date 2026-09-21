"""Optional server-side persistence for prediction pipeline telemetry."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

import httpx


class SupabaseLogger:
    """Small REST logger that is disabled when server credentials are absent."""

    def __init__(self) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.enabled = bool(self.url and self.key)
        self.run_id: str | None = None

    def _headers(self, prefer: str = "return=representation") -> dict[str, str]:
        return {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Prefer": prefer,
        }

    def _post(
        self,
        table: str,
        payload: dict[str, Any] | list[dict[str, Any]],
        *,
        params: dict[str, str] | None = None,
        prefer: str = "return=representation",
    ) -> list[dict[str, Any]]:
        response = httpx.post(
            f"{self.url}/rest/v1/{table}",
            headers=self._headers(prefer),
            params=params,
            json=payload,
            timeout=20,
        )
        response.raise_for_status()
        return response.json() if response.content else []

    def start(self, cutoff: str | None, commit: str) -> None:
        if not self.enabled:
            print("Supabase no configurado; se omite el registro remoto.")
            return
        rows = self._post(
            "pipeline_runs",
            {
                "run_type": "predict",
                "status": "running",
                "cutoff_at": cutoff,
                "commit_sha": commit,
                "details": {"source": "src/predict.py"},
            },
        )
        self.run_id = rows[0]["id"]

    def finish(self, status: str, rows: int = 0, error: str | None = None) -> None:
        if not self.enabled or not self.run_id:
            return
        payload = {
            "status": status,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "rows_processed": rows,
            "error_message": error,
        }
        response = httpx.patch(
            f"{self.url}/rest/v1/pipeline_runs",
            headers=self._headers("return=minimal"),
            params={"id": f"eq.{self.run_id}"},
            json=payload,
            timeout=20,
        )
        response.raise_for_status()

    def persist_submission(
        self,
        cycle: dict[str, Any],
        payload: dict[str, Any],
        submitted_at: str,
    ) -> None:
        """Upsert cycle, model metadata and accepted predictions."""
        if not self.enabled:
            return
        targets = cycle["targets"]
        cycle_rows = self._post(
            "forecast_cycles",
            {
                "external_cycle_id": cycle["cycle_id"],
                "status": "submitted",
                "issued_at": cycle.get("opens_at", cycle["data_cutoff"]),
                "target_start": min(item["target_at"] for item in targets),
                "target_end": max(item["target_at"] for item in targets),
                "closes_at": cycle.get("closes_at"),
            },
            params={"on_conflict": "external_cycle_id"},
            prefer="resolution=merge-duplicates,return=representation",
        )
        model = payload["model"]
        model_rows = self._post(
            "model_versions",
            {
                "model_name": "pulso_transmi_champion",
                "version": model["version"],
                "algorithm": "HistGradientBoostingRegressor",
                "training_start": model["trained_at"],
                "training_end": model["training_data_end"],
                "features": payload.get("feature_names", []),
                "validation_metrics": payload.get("validation_metrics", {}),
                "artifact_uri": "artifacts/champion.joblib",
                "commit_sha": model.get("git_commit"),
                "is_champion": True,
            },
            params={"on_conflict": "model_name,version"},
            prefer="resolution=merge-duplicates,return=representation",
        )
        horizons = {
            (item["station_id"], item["target_at"]): item["horizon_minutes"]
            for item in targets
        }
        rows = [
            {
                "cycle_id": cycle_rows[0]["id"],
                "model_id": model_rows[0]["id"],
                "station_id": item["station_id"],
                "target_at": item["target_at"],
                "horizon_minutes": horizons[(item["station_id"], item["target_at"])],
                "predicted_demand": item["value"],
                "submitted_at": submitted_at,
            }
            for item in payload["predictions"]
        ]
        self._post(
            "predictions",
            rows,
            params={"on_conflict": "cycle_id,model_id,station_id,target_at"},
            prefer="resolution=merge-duplicates,return=minimal",
        )
