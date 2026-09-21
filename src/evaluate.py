"""Evaluate persisted forecasts against exact station/timestamp ground truth."""
from __future__ import annotations
import argparse, sys
import pandas as pd
from metrics import mean_station_wape, score
from predict import git_commit
from supabase_logging import SupabaseLogger

def joined_truth(logger: SupabaseLogger) -> pd.DataFrame:
    predictions=logger.select("predictions",{"select":"cycle_id,model_id,station_id,target_at,horizon_minutes,predicted_demand,forecast_cycles!inner(status)","forecast_cycles.status":"in.(submitted,closed)"})
    if not predictions:return pd.DataFrame()
    start=min(x["target_at"] for x in predictions); end=max(x["target_at"] for x in predictions)
    observations=logger.select("observations",{"select":"station_id,observed_at,demand","observed_at":f"gte.{start}","and":f"(observed_at.lte.{end})"})
    p=pd.DataFrame(predictions); o=pd.DataFrame(observations)
    if o.empty:return pd.DataFrame()
    return p.merge(o,left_on=["station_id","target_at"],right_on=["station_id","observed_at"],how="inner",validate="many_to_one")

def metric_rows(frame: pd.DataFrame) -> list[dict]:
    rows=[]
    for (cycle,model), group in frame.groupby(["cycle_id","model_id"]):
        start,end=group.target_at.min(),group.target_at.max()
        groups=[(None,None,group)]+[(s,None,g) for s,g in group.groupby("station_id")]+[(None,int(h),g) for h,g in group.groupby("horizon_minutes")]
        for station,horizon,g in groups:
            values=score(g.demand,g.predicted_demand)
            if station is None and horizon is None:
                values["wape"]=mean_station_wape(g,"demand","predicted_demand"); values["accuracy"]=100*max(0,1-values["wape"])
            for name,value in values.items(): rows.append({"cycle_id":cycle,"model_id":model,"station_id":station,
                "horizon_minutes":horizon,"window_start":start,"window_end":end,"metric_name":name,"metric_value":value,"sample_size":len(g)})
    return rows

def run(persist: bool, *, logger: SupabaseLogger|None=None) -> int:
    logger=logger or SupabaseLogger(); frame=joined_truth(logger)
    if frame.empty: print("Aún no hay ground truth coincidente; evaluación terminada correctamente."); return 0
    rows=metric_rows(frame); print(f"Verdades unidas exactamente: {len(frame)} | métricas: {len(rows)}")
    if not persist: print("Dry-run completado; no se escribió en Supabase."); return 0
    logger.start(frame.target_at.max(),git_commit(),run_type="evaluate",details={"matched_predictions":len(frame)})
    try:
        logger.upsert("evaluation_metrics",rows,"cycle_id,model_id,station_id,horizon_minutes,window_start,window_end,metric_name",representation=False)
        logger.finish("succeeded",len(rows),details={"matched_predictions":len(frame),"metrics_upserted":len(rows)})
    except Exception as exc: logger.finish("failed",error=str(exc)[:1000]); raise
    return 0
def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); g=p.add_mutually_exclusive_group(); g.add_argument("--dry-run",action="store_true"); g.add_argument("--persist",action="store_true")
    a=p.parse_args(argv)
    try:return run(a.persist)
    except Exception as exc: print(f"Error: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
