"""Safe dry-run-first inference and submission client for Pulso TransMi."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx
import joblib
import numpy as np
import pandas as pd

from features import FEATURE_COLUMNS, build_target_features, normalize_station_ids
from supabase_logging import SupabaseLogger


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_PATH = ROOT / "artifacts" / "champion.joblib"
SUBMISSION_DIR = ROOT / "artifacts" / "submissions"
BASE_URL = os.getenv(
    "PULSO_API_BASE_URL",
    os.getenv("PULSO_API_URL", "https://pulso-transmi.72-60-245-2.sslip.io"),
).rstrip("/")
MODEL_VERSION = "champion-1.0.0"
ALLOWED_HORIZONS = {15, 30, 45, 60}
MAX_PREDICTION_VALUE = 100_000.0
TRANSIENT_STATUS = {429, 500, 502, 503, 504}


class PredictionError(RuntimeError):
    """Expected operational or validation failure safe to show to a user."""


class APIClient:
    def __init__(
        self,
        api_key: str | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        timeout: float | None = None,
    ) -> None:
        headers = {"User-Agent": "pulso-transmi-equipo-nao/1.0"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        self.client = httpx.Client(
            base_url=BASE_URL,
            headers=headers,
            timeout=timeout or float(os.getenv("PULSO_HTTP_TIMEOUT", "30")),
            follow_redirects=True,
            transport=transport,
        )

    def __enter__(self) -> "APIClient":
        return self

    def __exit__(self, *_: object) -> None:
        self.client.close()

    def request(
        self,
        method: str,
        path: str,
        *,
        retries: int = 2,
        **kwargs: Any,
    ) -> httpx.Response:
        for attempt in range(retries + 1):
            try:
                response = self.client.request(method, path, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == retries:
                    raise PredictionError(f"No fue posible conectar con {path}: {exc}") from exc
                time.sleep(2**attempt)
                continue
            if response.status_code in TRANSIENT_STATUS and attempt < retries:
                retry_after = response.headers.get("Retry-After")
                delay = float(retry_after) if retry_after and retry_after.isdigit() else 2**attempt
                time.sleep(min(delay, 10))
                continue
            return response
        raise AssertionError("bucle de reintentos inalcanzable")

    @staticmethod
    def _raise(response: httpx.Response, operation: str) -> None:
        if response.is_success:
            return
        request_id = response.headers.get("X-Request-ID", "no disponible")
        try:
            detail = response.json().get("detail", response.json())
        except (ValueError, AttributeError):
            detail = response.text[:300]
        raise PredictionError(
            f"{operation} falló (HTTP {response.status_code}, request {request_id}): {detail}"
        )

    def get_json(
        self, path: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        response = self.request("GET", path, params=params)
        self._raise(response, f"GET {path}")
        return response.json()

    def current_cycle(self) -> dict[str, Any] | None:
        response = self.request("GET", "/v1/forecast-cycles/current")
        if response.status_code == 404 and response.json().get("detail", {}).get("code") == "no_open_cycle":
            return None
        self._raise(response, "consulta del ciclo")
        return response.json()

    def current_submission(self) -> dict[str, Any] | None:
        response = self.request("GET", "/v1/submissions/current")
        if response.status_code == 404:
            code = response.json().get("detail", {}).get("code")
            if code in {"no_submission_for_cycle", "no_open_cycle"}:
                return None
        self._raise(response, "consulta del recibo actual")
        return response.json()

    def submit(self, payload: dict[str, Any], idempotency_key: str) -> dict[str, Any]:
        response = self.request(
            "POST",
            "/v1/submissions",
            headers={"Idempotency-Key": idempotency_key},
            json=payload,
        )
        self._raise(response, "submission")
        if response.status_code not in {200, 201}:
            raise PredictionError(
                f"Se esperaba HTTP 200 o 201 para una entrega y se recibió {response.status_code}"
            )
        return response.json()


def validate_openapi_contract(document: dict[str, Any]) -> None:
    """Fail closed if the required live API surface is absent."""
    paths = document.get("paths", {})
    required = {
        "/v1/me": "get",
        "/v1/submissions": "post",
        "/v1/submissions/{submission_id}": "get",
        "/v1/portal/login": "post",
        "/v1/portal/dashboard": "get",
        "/v1/portal/api-key": "post",
    }
    missing = [f"{method.upper()} {path}" for path, method in required.items() if method not in paths.get(path, {})]
    if missing:
        raise PredictionError(f"OpenAPI no contiene: {', '.join(missing)}")
    parameters = paths["/v1/submissions"]["post"].get("parameters", [])
    names = {item.get("name") for item in parameters}
    if "Idempotency-Key" not in names:
        raise PredictionError("OpenAPI no declara el header Idempotency-Key")


def git_commit() -> str:
    try:
        value = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise PredictionError("No fue posible obtener el SHA actual de Git") from exc
    if len(value) != 40 or any(character not in "0123456789abcdef" for character in value.lower()):
        raise PredictionError("El SHA actual de Git no es válido")
    return value.lower()


def load_champion(path: Path = ARTIFACT_PATH) -> dict[str, Any]:
    artifact = joblib.load(path)
    if artifact.get("artifact_type") != "pulso_transmi_champion":
        raise PredictionError("artifact_type inesperado en champion.joblib")
    if set(artifact.get("horizons_minutes", [])) != ALLOWED_HORIZONS:
        raise PredictionError("champion.joblib no contiene los cuatro horizontes")
    if set(artifact.get("models", {})) != ALLOWED_HORIZONS:
        raise PredictionError("champion.joblib no contiene cuatro pipelines utilizables")
    for horizon, item in artifact["models"].items():
        if item.get("features") != FEATURE_COLUMNS or not hasattr(item.get("model"), "predict"):
            raise PredictionError(f"Modelo inválido para horizonte {horizon}")
    for field in ("created_at", "validation_start", "validation_end", "champion_by_horizon"):
        if not artifact.get(field):
            raise PredictionError(f"Falta metadata {field} en champion.joblib")
    return artifact


def fetch_pages(
    api: APIClient, path: str, params: dict[str, Any] | None = None
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen: set[str] = set()
    while True:
        query = {**(params or {}), "limit": 5000}
        if cursor:
            query["cursor"] = cursor
        payload = api.get_json(path, params=query)
        rows.extend(payload.get("data", []))
        cursor = payload.get("next_cursor")
        if not cursor:
            return rows
        if cursor in seen:
            raise PredictionError(f"{path} devolvió un cursor repetido")
        seen.add(cursor)


def download_history(
    api: APIClient, cycle: dict[str, Any]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    stations = sorted({str(item["station_id"]).zfill(5) for item in cycle["targets"]})
    observation_rows: list[dict[str, Any]] = []
    for station_id in stations:
        observation_rows.extend(
            fetch_pages(api, "/v1/observations", {"station_id": station_id})
        )
    observation_rows.extend(fetch_pages(api, "/v1/stream/observations"))
    observations = pd.DataFrame(observation_rows)
    if observations.empty:
        raise PredictionError("La API no devolvió observaciones")
    observations["station_id"] = normalize_station_ids(observations["station_id"])
    observations = observations[observations["station_id"].isin(stations)]
    observations["observed_at"] = pd.to_datetime(observations["observed_at"], utc=True)
    observations = observations.drop_duplicates(
        ["station_id", "observed_at"], keep="last"
    ).sort_values(["station_id", "observed_at"])

    earliest = observations["observed_at"].min().isoformat()
    context_rows = fetch_pages(
        api,
        "/v1/context",
        {"start": earliest, "end": cycle["data_cutoff"]},
    )
    context = pd.DataFrame(context_rows)
    if context.empty:
        raise PredictionError("La API no devolvió contexto")
    return observations, context


def predict_targets(
    artifact: dict[str, Any], features: pd.DataFrame
) -> list[dict[str, Any]]:
    predictions: list[dict[str, Any]] = []
    for horizon, group in features.groupby("horizon_minutes", sort=False):
        horizon = int(horizon)
        if horizon not in artifact["models"]:
            raise PredictionError(f"No existe modelo para {horizon} minutos")
        item = artifact["models"][horizon]
        values = item["model"].predict(group[item["features"]])
        for row, value in zip(group.itertuples(index=False), values, strict=True):
            predictions.append(
                {
                    "station_id": str(row.station_id),
                    "target_at": pd.Timestamp(row.target_at).isoformat().replace("+00:00", "Z"),
                    "value": round(float(np.clip(value, 0, MAX_PREDICTION_VALUE)), 3),
                }
            )
    return predictions


def validate_predictions(
    predictions: list[dict[str, Any]], cycle: dict[str, Any]
) -> None:
    expected_count = int(cycle["expected_predictions"])
    if len(predictions) != expected_count or len(cycle["targets"]) != expected_count:
        raise PredictionError(
            f"Cantidad inválida: {len(predictions)} predicciones para {expected_count} objetivos"
        )
    actual: set[tuple[str, pd.Timestamp]] = set()
    for item in predictions:
        station_id = str(item["station_id"])
        if item.get("value") is None:
            raise PredictionError("Las predicciones no pueden contener nulos")
        value = float(item["value"])
        if not station_id.isdigit() or len(station_id) != 5:
            raise PredictionError("Todos los station_id deben tener cinco dígitos")
        if not math.isfinite(value) or not 0 <= value <= MAX_PREDICTION_VALUE:
            raise PredictionError("Las predicciones deben ser finitas y estar entre 0 y 100000")
        key = (station_id, pd.Timestamp(item["target_at"]))
        if key in actual:
            raise PredictionError("Hay objetivos duplicados en las predicciones")
        actual.add(key)
    expected = {
        (str(item["station_id"]), pd.Timestamp(item["target_at"]))
        for item in cycle["targets"]
    }
    if actual != expected:
        raise PredictionError("Las predicciones no coinciden exactamente con los objetivos del ciclo")


def stable_identifiers(cycle_id: str, commit: str) -> tuple[str, str]:
    source = f"{cycle_id}|{MODEL_VERSION}|{commit}".encode()
    digest = hashlib.sha256(source).hexdigest()
    short_cycle = cycle_id.removeprefix("cyc_")[:48]
    return f"manual-{short_cycle}-{commit[:8]}", f"ptm-{digest[:40]}"


def build_payload(
    cycle: dict[str, Any],
    artifact: dict[str, Any],
    predictions: list[dict[str, Any]],
    commit: str,
) -> tuple[dict[str, Any], str]:
    validate_predictions(predictions, cycle)
    client_run_id, idempotency_key = stable_identifiers(cycle["cycle_id"], commit)
    training_end = min(
        pd.Timestamp(item["trained_until"]) for item in artifact["models"].values()
    )
    payload = {
        "schema_version": "1.0",
        "cycle_id": cycle["cycle_id"],
        "client_run_id": client_run_id,
        "data_cutoff": cycle["data_cutoff"],
        "model": {
            "version": MODEL_VERSION,
            "trained_at": artifact["created_at"],
            "training_data_end": training_end.isoformat(),
            "git_commit": commit,
        },
        "predictions": predictions,
    }
    return payload, idempotency_key


def save_payload(payload: dict[str, Any]) -> Path:
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    safe_cycle = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in payload["cycle_id"]
    )
    path = SUBMISSION_DIR / f"{safe_cycle}-{payload['model']['git_commit'][:8]}.json"
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def save_receipt(receipt: dict[str, Any]) -> Path:
    SUBMISSION_DIR.mkdir(parents=True, exist_ok=True)
    submission_id = str(receipt["submission_id"])
    safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in submission_id)
    path = SUBMISSION_DIR / f"receipt-{safe_id}.json"
    path.write_text(json.dumps(receipt, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def print_summary(payload: dict[str, Any], cycle: dict[str, Any]) -> None:
    values = [item["value"] for item in payload["predictions"]]
    horizons = sorted({int(item["horizon_minutes"]) for item in cycle["targets"]})
    print(f"Ciclo: {payload['cycle_id']}")
    print(f"Corte: {payload['data_cutoff']}")
    print(f"Predicciones: {len(values)}")
    print(f"Horizontes: {', '.join(map(str, horizons))} minutos")
    print(f"Valores: min={min(values):.3f}, max={max(values):.3f}, promedio={np.mean(values):.3f}")
    print(f"Modelo: {payload['model']['version']}")
    print(f"Commit: {payload['model']['git_commit']}")


def status(api: APIClient) -> tuple[dict[str, Any], dict[str, Any] | None]:
    validate_openapi_contract(api.get_json("/openapi.json"))
    clock = api.get_json("/v1/clock")
    print(f"Reloj: {clock.get('state', 'desconocido')}")
    if clock.get("state") == "waiting":
        print("La API está en waiting; no se consultan ni envían predicciones.")
        return clock, None
    cycle = api.current_cycle()
    if cycle is None:
        print("No existe un ciclo de pronóstico abierto.")
        return clock, None
    print(
        f"Ciclo abierto: {cycle['cycle_id']} | corte {cycle['data_cutoff']} | "
        f"objetivos {cycle['expected_predictions']}"
    )
    return clock, cycle


def run_prediction(api: APIClient, *, submit: bool, assume_yes: bool) -> int:
    _, cycle = status(api)
    if cycle is None:
        return 0
    if submit:
        existing = api.current_submission()
        if existing:
            save_receipt(existing)
            print("El ciclo abierto ya tiene una entrega oficial; no se realiza otro POST.")
            return 0
    commit = git_commit()
    logger = SupabaseLogger()
    logger.start(cycle["data_cutoff"], commit)
    try:
        artifact = load_champion()
        observations, context = download_history(api, cycle)
        features = build_target_features(
            observations, context, cycle["targets"], cycle["data_cutoff"]
        )
        predictions = predict_targets(artifact, features)
        payload, idempotency_key = build_payload(cycle, artifact, predictions, commit)
        path = save_payload(payload)
        print_summary(payload, cycle)
        print(f"Payload de prueba: {path.relative_to(ROOT)}")
        if not submit:
            logger.finish("succeeded", len(predictions))
            print("Dry-run completado; no se realizó ningún POST.")
            return 0

        if not os.getenv("PULSO_API_KEY"):
            raise PredictionError(
                "Falta PULSO_API_KEY; es obligatoria únicamente para autenticar o enviar"
            )
        if not assume_yes:
            if not sys.stdin.isatty():
                raise PredictionError("El envío no interactivo requiere --yes además de --submit")
            answer = input("Escribe SUBMIT para confirmar el POST real: ").strip()
            if answer != "SUBMIT":
                logger.finish("skipped")
                print("Envío cancelado; no se realizó ningún POST.")
                return 0

        receipt = api.submit(payload, idempotency_key)
        submission_id = receipt["submission_id"]
        receipt_path = save_receipt(receipt)
        receipt_response = api.get_json(f"/v1/submissions/{submission_id}")
        receipt_path = save_receipt(receipt_response)
        submitted_at = receipt.get("received_at", datetime.now(timezone.utc).isoformat())
        logger.persist_submission(cycle, payload, submitted_at)
        logger.finish("succeeded", len(predictions))
    except Exception as exc:
        logger.finish("failed", error=str(exc)[:1000])
        raise
    print(f"Submission aceptada: {submission_id}")
    print(f"Recibo: {receipt_path.relative_to(ROOT)}")
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--status", action="store_true", help="consultar reloj y ciclo")
    modes.add_argument("--dry-run", action="store_true", help="generar sin enviar (predeterminado)")
    modes.add_argument("--check-auth", action="store_true", help="validar PULSO_API_KEY con /v1/me")
    modes.add_argument("--submit", action="store_true", help="enviar tras confirmación explícita")
    parser.add_argument("--yes", action="store_true", help="confirmar un --submit no interactivo")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    api_key = os.getenv("PULSO_API_KEY")
    if args.check_auth and not api_key:
        print("Error: falta PULSO_API_KEY para --check-auth.", file=sys.stderr)
        return 2
    if args.submit and not api_key:
        print("Error: falta PULSO_API_KEY para --submit.", file=sys.stderr)
        return 2
    try:
        with APIClient(api_key=api_key) as api:
            if args.check_auth:
                identity = api.get_json("/v1/me")
                print(f"Autenticación válida: {identity.get('display_name', identity.get('participant_id'))}")
                return 0
            if args.status:
                status(api)
                return 0
            return run_prediction(api, submit=args.submit, assume_yes=args.yes)
    except (PredictionError, httpx.HTTPError, ValueError, KeyError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
