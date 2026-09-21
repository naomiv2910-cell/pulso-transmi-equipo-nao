"""Incremental observations/context ingestion with dry-run as the default."""
from __future__ import annotations
import argparse, os, sys
from typing import Any
import pandas as pd
from predict import APIClient, PredictionError, git_commit
from supabase_logging import SupabaseLogger

def fetch_incremental(api: APIClient, path: str, params: dict[str, Any]) -> tuple[list[dict], str | None]:
    rows=[]; cursor=None; seen=set()
    while True:
        query={**params, "limit": 5000}
        if cursor: query["cursor"]=cursor
        page=api.get_json(path, params=query); rows.extend(page.get("data", []))
        nxt=page.get("next_cursor")
        if not nxt: return rows, cursor
        if nxt in seen: raise PredictionError(f"{path} devolvió un cursor repetido")
        seen.add(nxt); cursor=nxt

def latest(logger: SupabaseLogger, table: str) -> str | None:
    rows=logger.select(table, {"select":"observed_at", "order":"observed_at.desc", "limit":"1"})
    return rows[0]["observed_at"] if rows else None

def run(mode: str, *, api: APIClient | None=None, logger: SupabaseLogger | None=None) -> int:
    logger=logger or SupabaseLogger(); owned=api is None
    api=api or APIClient(api_key=os.getenv("PULSO_API_KEY"))
    try:
        clock=api.get_json("/v1/clock")
        if mode=="status":
            cutoff=latest(logger,"observations") if logger.enabled else None
            print(f"Reloj: {clock.get('state','desconocido')} | último dato: {cutoff or 'sin consultar'}"); return 0
        cutoff=latest(logger,"observations") if logger.enabled else None
        params={"after":cutoff} if cutoff else {}
        observations,cursor=fetch_incremental(api,"/v1/stream/observations",params)
        observations=list({(x["station_id"],x["observed_at"]):x for x in observations}.values())
        end=max((x["observed_at"] for x in observations),default=cutoff)
        context=[]
        if observations: context,_=fetch_incremental(api,"/v1/context",{"start":cutoff or min(x["observed_at"] for x in observations),"end":end})
        context=list({x["observed_at"]:x for x in context}.values())
        details={"initial_cutoff":cutoff,"final_cutoff":end,"rows_received":len(observations),
                 "context_rows":len(context),"final_cursor":cursor,"clock_state":clock.get("state")}
        print(f"Observaciones nuevas: {len(observations)} | contexto nuevo: {len(context)} | cutoff: {end}")
        if mode!="persist": print("Dry-run completado; no se escribió en Supabase."); return 0
        logger.start(end,git_commit(),run_type="ingest",details=details)
        try:
            if observations: logger.upsert("observations",observations,"station_id,observed_at",representation=False)
            if context: logger.upsert("context_observations",context,"observed_at",representation=False)
            logger.finish("succeeded",len(observations)+len(context),details=details)
        except Exception as exc: logger.finish("failed",error=str(exc)[:1000],details=details); raise
        return 0
    finally:
        if owned: api.client.close()

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); g=p.add_mutually_exclusive_group()
    g.add_argument("--status",action="store_true"); g.add_argument("--dry-run",action="store_true"); g.add_argument("--persist",action="store_true")
    a=p.parse_args(argv); mode="status" if a.status else "persist" if a.persist else "dry-run"
    try:return run(mode)
    except Exception as exc: print(f"Error: {exc}",file=sys.stderr); return 2
if __name__=="__main__": raise SystemExit(main())
