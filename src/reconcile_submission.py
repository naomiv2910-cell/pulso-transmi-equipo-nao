"""Recover an accepted submission in Supabase without ever submitting again."""
from __future__ import annotations
import argparse, json, os, sys
from pathlib import Path
import pandas as pd
from predict import APIClient, PredictionError, git_commit
from supabase_logging import SupabaseLogger

ROOT = Path(__file__).resolve().parents[1]
SUBMISSIONS = ROOT / "artifacts/submissions"

def find_payload(cycle_id: str) -> tuple[Path, dict]:
    for path in SUBMISSIONS.glob("*.json"):
        if path.name.startswith("receipt-"): continue
        value = json.loads(path.read_text())
        if value.get("cycle_id") == cycle_id: return path, value
    encoded = os.getenv("PULSO_SUBMISSION_PAYLOAD")
    if encoded:
        value = json.loads(encoded)
        if value.get("cycle_id") == cycle_id:
            return Path("github-secret:PULSO_SUBMISSION_PAYLOAD"), value
    raise PredictionError("No existe el payload original; no se reconstruirán predicciones")

def validate(receipt: dict, payload: dict) -> dict:
    if receipt.get("status") != "accepted" or receipt.get("is_official") is not True:
        raise PredictionError("El recibo no corresponde a una submission oficial aceptada")
    if receipt.get("cycle_id") != payload.get("cycle_id"):
        raise PredictionError("El ciclo del recibo y payload no coincide")
    predictions = payload.get("predictions", [])
    if receipt.get("predictions_received") != 48 or len(predictions) != 48:
        raise PredictionError("Se requieren exactamente las 48 predicciones aceptadas")
    cutoff = pd.Timestamp(payload["data_cutoff"])
    targets = []
    for row in predictions:
        horizon = int((pd.Timestamp(row["target_at"]) - cutoff).total_seconds() / 60)
        if horizon not in (15, 30, 45, 60): raise PredictionError("Horizonte inesperado en payload")
        targets.append({"station_id": row["station_id"], "target_at": row["target_at"],
                        "horizon_minutes": horizon})
    if len({(x["station_id"], x["target_at"]) for x in targets}) != 48:
        raise PredictionError("El payload contiene objetivos duplicados")
    return {"cycle_id": receipt["cycle_id"], "data_cutoff": payload["data_cutoff"],
            "opens_at": payload["data_cutoff"], "closes_at": receipt.get("closes_at"), "targets": targets}

def run(submission_id: str, persist: bool, *, api: APIClient | None = None,
        logger: SupabaseLogger | None = None) -> int:
    owned = api is None
    api = api or APIClient(api_key=os.getenv("PULSO_API_KEY"))
    try:
        receipt = api.get_json(f"/v1/submissions/{submission_id}")
    except PredictionError:
        saved_receipt = os.getenv("PULSO_SUBMISSION_RECEIPT")
        if not saved_receipt:
            raise
        receipt = json.loads(saved_receipt)
        if receipt.get("submission_id") != submission_id:
            raise PredictionError("El recibo de respaldo no corresponde al submission_id solicitado")
        print("GET del recibo no disponible; se usa el recibo oficial aceptado y preservado.")
    finally:
        if owned: api.client.close()
    path, payload = find_payload(receipt["cycle_id"])
    cycle = validate(receipt, payload)
    model = payload.get("model", {})
    if not model.get("version") or not model.get("git_commit"): raise PredictionError("Metadata de modelo incompleta")
    print(f"Submission: {submission_id}\nEstado: accepted / oficial\nCiclo: {cycle['cycle_id']}")
    source = str(path) if str(path).startswith("github-secret:") else str(path.relative_to(ROOT))
    print(f"Payload original: {source}\nPredicciones verificadas: 48")
    if not persist:
        print("Dry-run completado; no se escribió en Supabase."); return 0
    logger = logger or SupabaseLogger()
    logger.start(payload["data_cutoff"], git_commit(), run_type="predict",
        details={"operation": "reconcile", "submission_id": submission_id})
    try:
        cycle_id, model_id, count = logger.persist_submission(cycle, payload, receipt["received_at"], submission_id=submission_id)
        cycles = logger.select("forecast_cycles", {"select": "id,status", "id": f"eq.{cycle_id}"})
        models = logger.select("model_versions", {"select": "id,is_champion", "id": f"eq.{model_id}"})
        predictions = logger.select("predictions", {"select": "station_id,target_at", "cycle_id": f"eq.{cycle_id}",
                                                    "model_id": f"eq.{model_id}"})
        logical_keys = {(row["station_id"], row["target_at"]) for row in predictions}
        if len(cycles) != 1 or cycles[0]["status"] != "submitted":
            raise PredictionError("La verificación no encontró exactamente el ciclo enviado")
        if len(models) != 1 or models[0]["is_champion"] is not True:
            raise PredictionError("La verificación no encontró exactamente el champion")
        if len(predictions) != 48 or len(logical_keys) != 48:
            raise PredictionError("La verificación no encontró 48 predicciones lógicas únicas")
        logger.finish("succeeded", count, details={"operation": "reconcile", "submission_id": submission_id,
            "predictions_verified": count, "source": "accepted_receipt_and_original_payload"})
        completed = logger.select("pipeline_runs", {"select": "status,finished_at", "id": f"eq.{logger.run_id}"})
        if len(completed) != 1 or completed[0]["status"] != "succeeded" or not completed[0]["finished_at"]:
            raise PredictionError("El pipeline_run no quedó finalizado correctamente")
    except Exception as exc:
        logger.finish("failed", error=str(exc)[:1000], details={"operation": "reconcile", "submission_id": submission_id})
        raise
    print("Verificación Supabase: 1 ciclo, 1 champion, 48 predicciones únicas, pipeline succeeded.")
    print("Reconciliación idempotente completada: 48 predicciones."); return 0

def main(argv=None) -> int:
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--submission-id", required=True)
    mode=p.add_mutually_exclusive_group(); mode.add_argument("--dry-run", action="store_true"); mode.add_argument("--persist", action="store_true")
    a=p.parse_args(argv)
    try: return run(a.submission_id, a.persist)
    except (PredictionError, KeyError, ValueError, OSError) as exc: print(f"Error: {exc}", file=sys.stderr); return 2
if __name__ == "__main__": raise SystemExit(main())
