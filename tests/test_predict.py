from __future__ import annotations

import json
from pathlib import Path

import httpx
import pandas as pd
import pytest

import predict
from features import FEATURE_COLUMNS


def openapi_document() -> dict:
    return {
        "paths": {
            "/v1/me": {"get": {}},
            "/v1/submissions": {"post": {"parameters": [{"name": "Idempotency-Key"}]}},
            "/v1/submissions/{submission_id}": {"get": {}},
            "/v1/portal/login": {"post": {}},
            "/v1/portal/dashboard": {"get": {}},
            "/v1/portal/api-key": {"post": {}},
        }
    }


def cycle(target_count: int = 12) -> dict:
    cutoff = pd.Timestamp("2026-09-16T15:00:00Z")
    targets = []
    for index in range(target_count):
        horizon = (15, 30, 45, 60)[index % 4]
        targets.append(
            {
                "station_id": f"{2300 + index:05d}",
                "target_at": (cutoff + pd.Timedelta(horizon, unit="minutes")).isoformat(),
                "horizon_minutes": horizon,
            }
        )
    return {
        "cycle_id": "cyc_practice_1",
        "state": "open",
        "data_cutoff": cutoff.isoformat(),
        "expected_predictions": target_count,
        "targets": targets,
    }


def predictions_for(contract: dict) -> list[dict]:
    return [
        {"station_id": item["station_id"], "target_at": item["target_at"], "value": 123.0}
        for item in contract["targets"]
    ]


def test_loads_real_champion_with_four_horizons() -> None:
    artifact = predict.load_champion()
    assert artifact["artifact_type"] == "pulso_transmi_champion"
    assert set(artifact["models"]) == {15, 30, 45, 60}


def test_waiting_clock_stops_successfully_without_post() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=openapi_document())
        if request.url.path == "/v1/clock":
            return httpx.Response(200, json={"state": "waiting"})
        raise AssertionError(request.url.path)

    with predict.APIClient(transport=httpx.MockTransport(handler)) as api:
        assert predict.run_prediction(api, submit=False, assume_yes=False) == 0
    assert methods == ["GET", "GET"]


def test_missing_cycle_is_handled_without_post() -> None:
    methods: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        methods.append(request.method)
        if request.url.path == "/openapi.json":
            return httpx.Response(200, json=openapi_document())
        if request.url.path == "/v1/clock":
            return httpx.Response(200, json={"state": "running"})
        if request.url.path == "/v1/forecast-cycles/current":
            return httpx.Response(404, json={"detail": {"code": "no_open_cycle"}})
        raise AssertionError(request.url.path)

    with predict.APIClient(transport=httpx.MockTransport(handler)) as api:
        assert predict.run_prediction(api, submit=False, assume_yes=False) == 0
    assert "POST" not in methods


def test_dry_run_with_open_cycle_never_calls_submit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    contract = cycle()
    artifact = {
        "created_at": "2026-09-18T22:48:01Z",
        "models": {h: {"trained_until": "2026-09-02T05:00:00Z"} for h in (15, 30, 45, 60)},
    }

    class NoPostAPI:
        def submit(self, *_: object, **__: object) -> dict:
            raise AssertionError("dry-run intentó hacer POST")

    monkeypatch.setattr(predict, "status", lambda api: ({"state": "running"}, contract))
    monkeypatch.setattr(predict, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(predict, "load_champion", lambda: artifact)
    monkeypatch.setattr(predict, "download_history", lambda api, current: (pd.DataFrame(), pd.DataFrame()))
    monkeypatch.setattr(predict, "build_target_features", lambda *args: pd.DataFrame())
    monkeypatch.setattr(predict, "predict_targets", lambda *args: predictions_for(contract))
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    monkeypatch.setattr(predict, "ROOT", tmp_path)
    assert predict.run_prediction(NoPostAPI(), submit=False, assume_yes=False) == 0


def test_validates_exact_twelve_targets() -> None:
    contract = cycle()
    predict.validate_predictions(predictions_for(contract), contract)


def test_rejects_duplicate_targets() -> None:
    contract = cycle()
    values = predictions_for(contract)
    values[-1] = values[0].copy()
    with pytest.raises(predict.PredictionError, match="duplicados"):
        predict.validate_predictions(values, contract)


@pytest.mark.parametrize("value", [None, float("nan"), -1.0, float("inf")])
def test_rejects_null_negative_or_nonfinite_values(value: float | None) -> None:
    contract = cycle()
    values = predictions_for(contract)
    values[0]["value"] = value
    with pytest.raises(predict.PredictionError):
        predict.validate_predictions(values, contract)


class ConstantModel:
    def __init__(self, value: float) -> None:
        self.value = value

    def predict(self, frame: pd.DataFrame) -> list[float]:
        return [self.value] * len(frame)


def test_selects_model_by_horizon_and_clips_negative() -> None:
    frame = pd.DataFrame(
        [
            {**{column: 0 for column in FEATURE_COLUMNS}, "station_id": "02300", "target_at": "2026-09-16T15:15:00Z", "horizon_minutes": 15},
            {**{column: 0 for column in FEATURE_COLUMNS}, "station_id": "02300", "target_at": "2026-09-16T16:00:00Z", "horizon_minutes": 60},
        ]
    )
    artifact = {
        "models": {
            15: {"model": ConstantModel(-5), "features": FEATURE_COLUMNS},
            60: {"model": ConstantModel(60), "features": FEATURE_COLUMNS},
        }
    }
    values = predict.predict_targets(artifact, frame)
    assert [item["value"] for item in values] == [0.0, 60.0]


def test_payload_and_idempotency_are_reproducible() -> None:
    contract = cycle()
    artifact = {
        "created_at": "2026-09-18T22:48:01Z",
        "models": {h: {"trained_until": "2026-09-02T05:00:00Z"} for h in (15, 30, 45, 60)},
    }
    commit = "a" * 40
    first, first_key = predict.build_payload(contract, artifact, predictions_for(contract), commit)
    second, second_key = predict.build_payload(contract, artifact, predictions_for(contract), commit)
    assert first == second
    assert first_key == second_key
    assert first["schema_version"] == "1.0"
    assert first["model"]["version"] == "champion-1.0.0"


def test_missing_key_only_errors_for_auth_or_submit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PULSO_API_KEY", raising=False)
    assert predict.main(["--check-auth"]) == 2
    assert predict.main(["--submit"]) == 2


def test_submit_accepts_idempotent_http_200() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Idempotency-Key"] == "ptm-stable1"
        return httpx.Response(200, json={"submission_id": "sub_existing"})

    with predict.APIClient(api_key="not-printed", transport=httpx.MockTransport(handler)) as api:
        assert api.submit({"safe": True}, "ptm-stable1")["submission_id"] == "sub_existing"


def test_saved_payload_contains_no_api_key(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    payload = {"cycle_id": "cyc_test", "model": {"git_commit": "a" * 40}, "predictions": []}
    path = predict.save_payload(payload)
    assert "PULSO_API_KEY" not in path.read_text()
    json.loads(path.read_text())


def test_existing_submission_skips_prediction_and_post(tmp_path, monkeypatch):
    monkeypatch.setattr(predict, "status", lambda api: ({}, cycle()))
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    class ExistingAPI:
        def current_submission(self):
            return {"submission_id": "sub_existing", "status": "accepted"}
    assert predict.run_prediction(ExistingAPI(), submit=True, assume_yes=True) == 0
    assert json.loads((tmp_path / "receipt-sub_existing.json").read_text())["status"] == "accepted"


@pytest.mark.parametrize("code", ["no_submission_for_cycle", "no_open_cycle"])
def test_expected_missing_receipt(code):
    with predict.APIClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": {"code": code}})
    )) as api:
        assert api.current_submission() is None


def test_unknown_404_fails():
    with predict.APIClient(transport=httpx.MockTransport(
        lambda request: httpx.Response(404, json={"detail": {"code": "unexpected"}})
    )) as api:
        with pytest.raises(predict.PredictionError):
            api.current_cycle()
        with pytest.raises(predict.PredictionError):
            api.current_submission()


def test_post_retry_keeps_payload_and_idempotency_key(monkeypatch):
    calls = []
    monkeypatch.setattr(predict.time, "sleep", lambda seconds: None)
    def handler(request):
        calls.append((request.headers["Idempotency-Key"], request.content))
        return httpx.Response(503 if len(calls) == 1 else 200,
                              json={"submission_id": "sub_replayed"})
    with predict.APIClient(transport=httpx.MockTransport(handler)) as api:
        assert api.submit({"test": 1}, "stable-key")["submission_id"] == "sub_replayed"
    assert len(calls) == 2
    assert calls[0] == calls[1]


def test_receipt_survives_followup_failure(tmp_path, monkeypatch):
    contract = cycle()
    artifact = {"created_at": "2026-09-18T22:48:01Z", "models": {
        h: {"trained_until": "2026-09-02T05:00:00Z"} for h in (15, 30, 45, 60)}}
    monkeypatch.setattr(predict, "status", lambda api: ({}, contract))
    monkeypatch.setattr(predict, "git_commit", lambda: "a" * 40)
    monkeypatch.setattr(predict, "load_champion", lambda: artifact)
    monkeypatch.setattr(predict, "download_history", lambda *args: (None, None))
    monkeypatch.setattr(predict, "build_target_features", lambda *args: None)
    monkeypatch.setattr(predict, "predict_targets", lambda *args: predictions_for(contract))
    monkeypatch.setattr(predict, "SUBMISSION_DIR", tmp_path)
    monkeypatch.setattr(predict, "ROOT", tmp_path)
    monkeypatch.setenv("PULSO_API_KEY", "test-key")
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    class AcceptedAPI:
        def current_submission(self): return None
        def submit(self, *args): return {"submission_id": "sub_accepted", "status": "accepted"}
        def get_json(self, *args): raise predict.PredictionError("follow-up unavailable")
    with pytest.raises(predict.PredictionError, match="follow-up"):
        predict.run_prediction(AcceptedAPI(), submit=True, assume_yes=True)
    assert json.loads((tmp_path / "receipt-sub_accepted.json").read_text())["status"] == "accepted"


@pytest.mark.parametrize("supports_current", [False, True])
def test_legacy_receipt_route_requires_confirmed_missing_capability(supports_current):
    def handler(request):
        if request.url.path == "/v1/submissions/current":
            return httpx.Response(404, json={"detail": {"code": "submission_not_found"}})
        assert request.url.path == "/openapi.json"
        paths = {"/v1/submissions/{submission_id}": {"get": {}}}
        if supports_current:
            paths["/v1/submissions/current"] = {"get": {}}
        return httpx.Response(200, json={"paths": paths})
    with predict.APIClient(transport=httpx.MockTransport(handler)) as api:
        if supports_current:
            with pytest.raises(predict.PredictionError, match="submission_not_found"):
                api.current_submission()
        else:
            assert api.current_submission() is None


def test_saved_acceptance_skips_even_when_remote_lookup_unavailable(tmp_path, monkeypatch):
    contract = cycle()
    monkeypatch.setattr(predict, 'SUBMISSION_DIR', tmp_path)
    monkeypatch.setattr(predict, 'status', lambda api: ({}, contract))
    predict.remember_acceptance(contract['cycle_id'], {'submission_id': 'sub_ok'})
    assert predict.run_prediction(object(), submit=True, assume_yes=True) == 0


def test_pending_payload_survives_timeout_and_code_change(tmp_path, monkeypatch):
    contract = cycle()
    artifact = {'created_at': '2026-09-18T22:48:01Z', 'models': {
        h: {'trained_until': '2026-09-02T05:00:00Z'} for h in (15, 30, 45, 60)}}
    monkeypatch.setattr(predict, 'status', lambda api: ({}, contract))
    monkeypatch.setattr(predict, 'git_commit', lambda: 'a' * 40)
    monkeypatch.setattr(predict, 'load_champion', lambda: artifact)
    monkeypatch.setattr(predict, 'download_history', lambda *args: (None, None))
    monkeypatch.setattr(predict, 'build_target_features', lambda *args: None)
    monkeypatch.setattr(predict, 'predict_targets', lambda *args: predictions_for(contract))
    monkeypatch.setattr(predict, 'SUBMISSION_DIR', tmp_path)
    monkeypatch.setattr(predict, 'ROOT', tmp_path)
    monkeypatch.setenv('PULSO_API_KEY', 'test-key')
    class Logger:
        def start(self, *args): pass
        def finish(self, *args, **kwargs): pass
        def persist_submission(self, *args): pass
    monkeypatch.setattr(predict, 'SupabaseLogger', Logger)
    class API:
        calls = []
        def current_submission(self): return None
        def submit(self, payload, key):
            self.calls.append((payload, key))
            if len(self.calls) == 1: raise predict.PredictionError('timeout')
            return {'submission_id': 'sub_ok'}
        def get_json(self, path): return {'submission_id': 'sub_ok'}
    api = API()
    with pytest.raises(predict.PredictionError, match='timeout'):
        predict.run_prediction(api, submit=True, assume_yes=True)
    monkeypatch.setattr(predict, 'git_commit', lambda: 'b' * 40)
    monkeypatch.setattr(predict, 'load_champion', lambda: pytest.fail('Must reuse pending payload'))
    assert predict.run_prediction(api, submit=True, assume_yes=True) == 0
    assert api.calls[0] == api.calls[1]
    assert predict.accepted_cycle(contract['cycle_id'])
    assert predict.run_prediction(api, submit=True, assume_yes=True) == 0
    assert len(api.calls) == 2
