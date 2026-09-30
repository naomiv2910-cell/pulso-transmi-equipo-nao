"""Server-only, idempotent Supabase REST helpers for MLOps jobs."""
from __future__ import annotations
import json, os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
import httpx, joblib, pandas as pd

ROOT = Path(__file__).resolve().parents[1]

class SupabaseLogger:
    """Minimal PostgREST client. Credentials are read only from the environment."""
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self.url = os.getenv("SUPABASE_URL", "").rstrip("/")
        self.key = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "")
        self.enabled = bool(self.url and self.key)
        self.run_id: str | None = None
        self.client = httpx.Client(timeout=30, transport=transport)

    def close(self) -> None: self.client.close()
    def _headers(self, prefer: str = "return=representation") -> dict[str, str]:
        return {"apikey": self.key, "Authorization": f"Bearer {self.key}", "Prefer": prefer}

    def request(self, method: str, table: str, *, params: dict[str, str] | None = None,
                payload: Any = None, prefer: str = "return=representation") -> list[dict[str, Any]]:
        if not self.enabled: raise RuntimeError("Faltan SUPABASE_URL y SUPABASE_SERVICE_ROLE_KEY")
        response = self.client.request(method, f"{self.url}/rest/v1/{table}",
            headers=self._headers(prefer), params=params, json=payload)
        response.raise_for_status()
        return response.json() if response.content else []

    def select(self, table: str, params: dict[str, str]) -> list[dict[str, Any]]:
        return self.request("GET", table, params=params)
    def select_all(self, table: str, params: dict[str, str], page_size: int = 1000) -> list[dict[str, Any]]:
        if "order" not in params:
            raise ValueError("La paginación requiere un orden estable")
        rows: list[dict[str, Any]] = []
        offset = 0
        while True:
            page = self.select(table, {**params, "limit": str(page_size), "offset": str(offset)})
            if not page:
                return rows
            rows.extend(page)
            offset += len(page)

    def upsert(self, table: str, payload: Any, conflict: str, *, representation: bool = True) -> list[dict[str, Any]]:
        returned = "representation" if representation else "minimal"
        return self.request("POST", table, params={"on_conflict": conflict}, payload=payload,
            prefer=f"resolution=merge-duplicates,return={returned}")

    def start(self, cutoff: str | None, commit: str, *, run_type: str = "predict",
              details: dict[str, Any] | None = None) -> None:
        if not self.enabled:
            print("Supabase no configurado; se omite el registro remoto."); return
        rows = self.request("POST", "pipeline_runs", payload={"run_type": run_type, "status": "running",
            "cutoff_at": cutoff, "commit_sha": commit, "details": details or {}})
        self.run_id = rows[0]["id"]

    def finish(self, status: str, rows: int = 0, error: str | None = None,
               details: dict[str, Any] | None = None) -> None:
        if not self.enabled or not self.run_id: return
        payload: dict[str, Any] = {"status": status, "finished_at": datetime.now(timezone.utc).isoformat(),
            "rows_processed": rows, "error_message": error}
        if details is not None: payload["details"] = details
        self.request("PATCH", "pipeline_runs", params={"id": f"eq.{self.run_id}"}, payload=payload,
            prefer="return=minimal")

    def persist_submission(self, cycle: dict[str, Any], payload: dict[str, Any], submitted_at: str,
                           *, submission_id: str | None = None) -> tuple[str, str, int]:
        active = joblib.load(ROOT / "artifacts/champion.joblib")
        active_version = active.get("model_version", "champion-1.0.0")
        submitted_version = payload["model"]["version"]
        if submitted_version == active_version:
            artifact = active
        else:
            # A retry may belong to the previous version: preserve its true metadata.
            if not all(c.isalnum() or c in "-_." for c in submitted_version):
                raise ValueError("Versión de modelo inválida")
            artifact = joblib.load(ROOT / "artifacts/versions" / f"{submitted_version}.joblib")
        raw_path = ROOT / "data/raw/observations.csv"
        training_end = pd.Timestamp(payload["model"]["training_data_end"])
        # The starter dataset spans 45 days and validation reserves the final 7.
        # Prefer the observed minimum locally; CI can derive the same 38-day boundary.
        training_start = (pd.Timestamp(artifact["training_start"]) if artifact.get("training_start") else
                          pd.to_datetime(pd.read_csv(raw_path, usecols=["observed_at"])["observed_at"], utc=True).min()
                          if raw_path.exists() else training_end - pd.Timedelta(days=38))
        targets = cycle["targets"]
        cycle_row = self.upsert("forecast_cycles", {"external_cycle_id": cycle["cycle_id"],
            "status": "submitted", "issued_at": cycle.get("opens_at", payload["data_cutoff"]),
            "target_start": min(x["target_at"] for x in targets), "target_end": max(x["target_at"] for x in targets),
            "closes_at": cycle.get("closes_at")}, "external_cycle_id")[0]
        model = payload["model"]
        if submitted_version == active_version:
            self.request("PATCH", "model_versions", params={"model_name":"eq.pulso_transmi_champion", "version":f"neq.{active_version}"},
                         payload={"is_champion":False}, prefer="return=minimal")
        model_row = self.upsert("model_versions", {"model_name": "pulso_transmi_champion",
            "version": model["version"], "algorithm": "HistGradientBoostingRegressor",
            "training_start": training_start.isoformat(),
            "training_end": model["training_data_end"], "features": artifact["models"][15]["features"],
            "parameters": {"artifact_created_at": artifact["created_at"], **artifact.get("adaptation", {})},
            "validation_metrics": artifact["champion_by_horizon"], "artifact_uri": f"artifacts/versions/{submitted_version}.joblib",
            "commit_sha": model.get("git_commit"), "is_champion": submitted_version == active_version}, "model_name,version")[0]
        horizons = {(x["station_id"], x["target_at"]): x["horizon_minutes"] for x in targets}
        rows = [{"cycle_id": cycle_row["id"], "model_id": model_row["id"], "station_id": x["station_id"],
            "target_at": x["target_at"], "horizon_minutes": horizons[(x["station_id"], x["target_at"])],
            "predicted_demand": x["value"], "submitted_at": submitted_at} for x in payload["predictions"]]
        self.upsert("predictions", rows, "cycle_id,model_id,station_id,target_at", representation=False)
        return cycle_row["id"], model_row["id"], len(rows)
