"""Lightweight, interpretable data/performance drift monitor."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd
from predict import git_commit
from supabase_logging import SupabaseLogger

ROOT=Path(__file__).resolve().parents[1]
def recommend_retraining(new_days: float, validation_accuracy: float, rolling_accuracy: float|None,
                         strong_drift_windows: int) -> bool:
    return new_days>=7 and ((rolling_accuracy is not None and validation_accuracy-rolling_accuracy>=5) or strong_drift_windows>1)
def classify_drift(z_shift: float|None, accuracy_drop: float|None, samples: int) -> str:
    if samples<48:return "insufficient_data"
    if (accuracy_drop is not None and accuracy_drop>=5) or (z_shift is not None and z_shift>=1):return "retrain_recommended"
    if (accuracy_drop is not None and accuracy_drop>=3) or (z_shift is not None and z_shift>=0.5):return "warning"
    return "healthy"
def run(persist: bool, *, logger: SupabaseLogger|None=None)->int:
    logger=logger or SupabaseLogger(); summary=json.loads((ROOT/"artifacts/training_summary.json").read_text())
    reference=float(np.mean([x["accuracy_pct"] for x in summary["champion_by_horizon"].values()]))
    obs=logger.select("observations",{"select":"station_id,observed_at,demand","order":"observed_at.desc","limit":"8064"}) if logger.enabled else []
    metrics=logger.select("evaluation_metrics",{"select":"metric_name,metric_value,sample_size,window_end","metric_name":"eq.accuracy","order":"window_end.desc","limit":"1"}) if logger.enabled else []
    recent=float(metrics[0]["metric_value"]) if metrics else None
    frame=pd.DataFrame(obs); z=None
    if len(frame)>=96*14:
        frame["observed_at"]=pd.to_datetime(frame.observed_at,utc=True); split=frame.observed_at.max()-pd.Timedelta(days=7)
        old=frame[frame.observed_at<split].demand; new=frame[frame.observed_at>=split].demand
        z=abs(float(new.mean()-old.mean()))/max(float(old.std()),1.0)
    drop=None if recent is None else reference-recent; state=classify_drift(z,drop,len(frame))
    details={"state":state,"thresholds":{"warning_z":0.5,"strong_z":1.0,"accuracy_drop_pp":5},
        "data":{"samples":len(frame),"standardized_mean_shift":z},"performance":{"champion_validation_accuracy":reference,"recent_accuracy":recent,"drop_pp":drop}}
    print(json.dumps(details,indent=2))
    if persist:
        logger.start(None,git_commit(),run_type="monitor",details=details); logger.finish("succeeded",len(frame),details=details)
    else: print("Dry-run completado; no se escribió en Supabase.")
    return 0
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__);g=p.add_mutually_exclusive_group();g.add_argument("--dry-run",action="store_true");g.add_argument("--persist",action="store_true");a=p.parse_args(argv)
    try:return run(a.persist)
    except Exception as exc:print(f"Error: {exc}",file=sys.stderr);return 2
if __name__=="__main__":raise SystemExit(main())
