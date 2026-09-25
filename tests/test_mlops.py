import json
from pathlib import Path
import pandas as pd
import pytest

from backtest import fold_boundaries
from evaluate import metric_rows
from ingest import fetch_incremental
from metrics import accuracy, mean_station_wape, score, wape
from monitor import classify_drift, recommend_retraining
from reconcile_submission import validate
from reconcile_submission import find_payload

def test_wape_is_mean_across_stations():
    frame=pd.DataFrame({"station_id":["a","a","b"],"actual":[10,10,100],"predicted":[0,0,100]})
    assert mean_station_wape(frame)==pytest.approx(.5)
def test_accuracy_and_rmse():
    assert accuracy([10,10],[9,11])==pytest.approx(90)
    assert score([0,2],[0,0])["rmse"]==pytest.approx(2**.5)
def test_exact_truth_metrics():
    f=pd.DataFrame({"cycle_id":["c"],"model_id":["m"],"station_id":["1"],"target_at":["2026-01-01T00:00:00Z"],"horizon_minutes":[15],"demand":[10],"predicted_demand":[9]})
    assert {x["metric_name"] for x in metric_rows(f)}=={"wape","accuracy","mae","rmse"}
def test_three_expanding_folds_have_no_overlap():
    folds=fold_boundaries(pd.Timestamp("2026-01-01",tz="UTC"));assert len(folds)==3
    assert all(a<b for a,b in folds) and folds[0][1]==folds[1][0]
def test_reconcile_validation_builds_exact_targets():
    payload={"cycle_id":"c","data_cutoff":"2026-01-01T00:00:00Z","predictions":[]}
    for h in (15,30,45,60):
        for s in range(12):payload["predictions"].append({"station_id":f"{s:05d}","target_at":(pd.Timestamp(payload["data_cutoff"])+pd.Timedelta(minutes=h)).isoformat(),"value":1})
    cycle=validate({"status":"accepted","is_official":True,"cycle_id":"c","predictions_received":48},payload)
    assert len(cycle["targets"])==48
def test_reconcile_rejects_non_official():
    with pytest.raises(Exception):validate({"status":"accepted","is_official":False},{})
def test_reconcile_can_read_payload_from_ci_secret(monkeypatch):
    monkeypatch.setenv("PULSO_SUBMISSION_PAYLOAD",json.dumps({"cycle_id":"ci-cycle"}))
    path,payload=find_payload("ci-cycle")
    assert str(path)=="github-secret:PULSO_SUBMISSION_PAYLOAD" and payload["cycle_id"]=="ci-cycle"
class Pages:
    def __init__(self,pages):self.pages=iter(pages)
    def get_json(self,*a,**k):return next(self.pages)
def test_incremental_preserves_final_cursor():
    rows,cursor=fetch_incremental(Pages([{"data":[{"x":1}],"next_cursor":"abc"},{"data":[{"x":2}]}]),"/x",{})
    assert len(rows)==2 and cursor=="abc"
def test_repeated_cursor_fails():
    with pytest.raises(Exception):fetch_incremental(Pages([{"data":[],"next_cursor":"a"},{"data":[],"next_cursor":"a"}]),"/x",{})
def test_zero_new_rows():
    assert fetch_incremental(Pages([{"data":[]}]),"/x",{})==( [], None)
@pytest.mark.parametrize("state,args",[("insufficient_data",(None,None,1)),("healthy",(.1,1,100)),("warning",(.6,1,100)),("retrain_recommended",(1.1,1,100))])
def test_drift_states(state,args):assert classify_drift(*args)==state
def test_retraining_rule():
    assert recommend_retraining(7,86,80,0);assert not recommend_retraining(6,86,70,3)
def test_workflow_manual_dry_run_and_scheduled_submit():
    text=(Path(__file__).parents[1]/".github/workflows/pipeline.yml").read_text()
    assert "default: dry-run" in text and "  schedule:" not in text
    assert "group: pulso-transmi-pipeline" in text
    assert "actions/upload-artifact@v4" in text
    assert "reconcile" in text and "--submit --yes" in text
def test_reconcile_source_contains_no_post_submission():
    text=(Path(__file__).parents[1]/"src/reconcile_submission.py").read_text()
    assert 'get_json(f"/v1/submissions/' in text and '.submit(' not in text
def test_no_literal_secret_in_workflow():
    text=(Path(__file__).parents[1]/".github/workflows/pipeline.yml").read_text()
    assert "sb_secret_" not in text and "ptm_live_" not in text
