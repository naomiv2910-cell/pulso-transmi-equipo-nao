"""Seasonally adjusted demand drift and accuracy on delivered, resolved cycles."""
from __future__ import annotations
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import numpy as np
import pandas as pd
from predict import git_commit
from supabase_logging import SupabaseLogger

ROOT = Path(__file__).resolve().parents[1]


def recommend_retraining(new_days, validation_accuracy, rolling_accuracy, strong_drift_windows):
    return new_days >= 7 and ((rolling_accuracy is not None and validation_accuracy-rolling_accuracy >= 5) or strong_drift_windows > 1)


def classify_drift(z_shift, accuracy_drop, samples):
    # Compatibility helper; the report uses per-station seasonal residuals below.
    if samples < 48: return 'insufficient_data'
    if (accuracy_drop is not None and accuracy_drop >= 5) or (z_shift is not None and z_shift >= 1): return 'retrain_recommended'
    if (accuracy_drop is not None and accuracy_drop >= 3) or (z_shift is not None and z_shift >= .5): return 'warning'
    return 'healthy'


def psi(reference, current):
    edges = np.array([-np.inf, -2, -1, -.5, 0, .5, 1, 2, np.inf])
    a = np.histogram(reference, bins=edges)[0].astype(float) + .5
    b = np.histogram(current, bins=edges)[0].astype(float) + .5
    a /= a.sum(); b /= b.sum()
    return float(np.sum((b-a)*np.log(b/a)))


def prepare_observations(rows):
    frame = pd.DataFrame(rows)
    if frame.empty: return frame
    frame['observed_at'] = pd.to_datetime(frame.observed_at, utc=True)
    frame['station_id'] = frame.station_id.astype(str).str.zfill(5)
    frame['demand'] = pd.to_numeric(frame.demand, errors='raise')
    if not np.isfinite(frame.demand).all() or (frame.demand < 0).any():
        raise ValueError('Demanda no válida')
    return frame.drop_duplicates(['station_id', 'observed_at']).sort_values(['observed_at', 'station_id'])


def data_drift(frame, training_end, names):
    if frame.empty:
        return {'status':'insufficient_data', 'stations':[], 'reason':'No hay observaciones'}
    end = frame.observed_at.max()
    start = end-pd.Timedelta(hours=24)
    reference = frame[frame.observed_at <= training_end].copy()
    current = frame[(frame.observed_at > start) & (frame.observed_at > training_end)].copy()
    for data in (reference, current):
        local = data.observed_at.dt.tz_convert('America/Bogota')
        data['weekday'] = local.dt.dayofweek
        data['hour'] = local.dt.hour
    results = []
    station_ids = sorted(set(names) | set(frame.station_id))
    for station in station_ids:
        ref = reference[reference.station_id == station]
        new = current[current.station_id == station]
        row = {'station_id':station, 'name':names.get(station, station), 'reference_samples':len(ref),
               'recent_samples':len(new), 'status':'insufficient_data', 'psi':None, 'mean_shift':None}
        if len(ref) >= 96*28 and len(new) >= 96:
            profile = ref.groupby(['weekday','hour']).demand.agg(['mean','std','count']).reset_index()
            profile['std'] = profile['std'].clip(lower=1)
            r = ref.merge(profile, on=['weekday','hour'], validate='many_to_one')
            n = new.merge(profile, on=['weekday','hour'], how='left', validate='many_to_one')
            if n['mean'].notna().all() and (n['count'] >= 8).all():
                a = (r.demand-r['mean'])/r['std']
                b = (n.demand-n['mean'])/n['std']
                shift = float(abs(b.mean()-a.mean()) / max(float(a.std()), .01))
                value = psi(a.to_numpy(), b.to_numpy())
                status = 'high' if value >= .3 or shift >= 1 else 'warning' if value >= .2 or shift >= .5 else 'stable'
                row.update(psi=round(value,4), mean_shift=round(shift,4), status=status,
                    reference_mean=round(float(ref.demand.mean()),2), recent_mean=round(float(new.demand.mean()),2))
        results.append(row)
    statuses = [r['status'] for r in results]
    overall = 'high' if 'high' in statuses else 'warning' if 'warning' in statuses else 'insufficient_data' if 'insufficient_data' in statuses else 'stable'
    return {'status':overall, 'window_start':start.isoformat(), 'window_end':end.isoformat(),
        'reference_start':reference.observed_at.min().isoformat() if len(reference) else None,
        'reference_end':training_end.isoformat(), 'stations':results,
        'method':'PSI de residuos normalizados por estación, día de semana y hora de Bogotá; referencia solo de entrenamiento.',
        'thresholds':{'psi_warning':.2,'psi_high':.3,'mean_shift_warning':.5,'mean_shift_high':1},
        'note':'Umbrales heurísticos de alerta; no constituyen una prueba causal de concept drift.'}


def summarize_accuracy(frame):
    scores = []
    for _, g in frame.groupby('station_id'):
        wape = float(abs(g.demand-g.predicted_demand).sum()/max(abs(g.demand).sum(),1))
        scores.append((wape,100*max(0,1-wape)))
    return {'accuracy':round(float(np.mean([x[1] for x in scores])),3),
            'wape':round(float(np.mean([x[0] for x in scores])),5),
            'mae':round(float(abs(frame.demand-frame.predicted_demand).mean()),3),
            'samples':len(frame)}


def performance(frame, predictions, cycles):
    empty = {'status':'insufficient_data', 'accuracy':None, 'wape':None, 'mae':None,
             'samples':0, 'evaluated_cycles':0, 'pending_cycles':0, 'history':[]}
    if frame.empty or not predictions: return empty
    end = frame.observed_at.max()
    p = pd.DataFrame(predictions)
    p['target_at'] = pd.to_datetime(p.target_at, utc=True)
    p['station_id'] = p.station_id.astype(str).str.zfill(5)
    # Models are evaluated separately; this dashboard follows the active champion only.
    if p.model_id.nunique() > 1: raise ValueError('Mezcla de modelos en evaluación')
    lookup = {c['id']:c for c in cycles}
    complete = []; history = []; pending = 0
    for cycle, group in p.groupby('cycle_id'):
        info = lookup.get(cycle)
        if info is None: continue
        cycle_end = pd.Timestamp(info['target_end'])
        if cycle_end <= end-pd.Timedelta(hours=24): continue
        matched = group.merge(frame[['station_id','observed_at','demand']],
            left_on=['station_id','target_at'],right_on=['station_id','observed_at'],how='inner',validate='many_to_one')
        if cycle_end > end or len(matched) != len(group):
            pending += 1; continue
        stats = summarize_accuracy(matched)
        history.append({'cycle_id':info['external_cycle_id'], 'target_end':cycle_end.isoformat(), **stats})
        complete.append(matched)
    if not complete: return {**empty, 'pending_cycles':pending}
    joined = pd.concat(complete, ignore_index=True)
    return {'status':'available', **summarize_accuracy(joined), 'evaluated_cycles':len(complete),
            'pending_cycles':pending, 'history':sorted(history,key=lambda x:x['target_end']),
            'window_end':end.isoformat(),
            'note':'Solo entregas guardadas con verdad completa de las últimas 24 horas virtuales. No es el ranking oficial ni incluye ciclos ausentes.'}


def build_report(observations, predictions, cycles, stations, model):
    frame = prepare_observations(observations)
    names = {s['station_id']:s['station_name'] for s in stations}
    training_end = pd.Timestamp(model['training_end'])
    perf = performance(frame,predictions,cycles)
    drift = data_drift(frame,training_end,names)
    latest = max(cycles, key=lambda c:c['target_end']) if cycles else None
    latest_predictions = [p for p in predictions if latest and p['cycle_id'] == latest['id']]
    # Allowlist public fields: no credentials, internal UUIDs, personal data or raw errors.
    return {'schema_version':1, 'generated_at':datetime.now(timezone.utc).isoformat(),
        'observations':{'count':len(frame),'last_at':frame.observed_at.max().isoformat() if len(frame) else None},
        'model':{'version':model['version'],'algorithm':model['algorithm'],'training_end':model['training_end']},
        'drift':drift, 'performance':perf,
        'deliveries':{'stored_cycles':len(cycles),'latest_cycle':latest['external_cycle_id'] if latest else None,
            'latest_submitted_at':max((p['submitted_at'] for p in predictions),default=None),
            'latest_predictions':[{'station_id':p['station_id'],'station_name':names.get(p['station_id'],p['station_id']),
                'horizon_minutes':p['horizon_minutes'],'target_at':p['target_at'],'predicted_demand':p['predicted_demand']} for p in latest_predictions]},
        'recommendation':'Revisar datos y evaluar un candidato antes de reentrenar; no se cambia el modelo automáticamente.' if drift['status'] in {'high','warning'} else 'Continuar recopilando datos y comprobar la precisión de las entregas evaluadas.'}


def run(persist, *, logger=None):
    logger = logger or SupabaseLogger()
    models = logger.select('model_versions',{'select':'id,version,algorithm,training_end','is_champion':'eq.true','limit':'1'})
    if not models: raise ValueError('No hay modelo champion registrado')
    model = models[0]
    obs = logger.select_all('observations',{'select':'station_id,observed_at,demand','order':'observed_at.asc,station_id.asc'})
    predictions = logger.select_all('predictions',{'select':'cycle_id,model_id,station_id,target_at,horizon_minutes,predicted_demand,submitted_at','model_id':f"eq.{model['id']}",'order':'id.asc'})
    cycles = logger.select_all('forecast_cycles',{'select':'id,external_cycle_id,target_start,target_end','status':'eq.submitted','order':'id.asc'})
    stations = logger.select('stations',{'select':'station_id,station_name'})
    report = build_report(obs,predictions,cycles,stations,model)
    path = ROOT/'reports/dashboard.json'; path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(report,indent=2,ensure_ascii=False,allow_nan=False)+'\n')
    print(json.dumps({'drift':report['drift']['status'],'performance':report['performance'], 'report':str(path)},ensure_ascii=False))
    if persist:
        logger.start(report['observations']['last_at'],git_commit(),run_type='monitor',details=report)
        logger.finish('succeeded',len(obs),details=report)
    return 0


def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    g=p.add_mutually_exclusive_group();g.add_argument('--dry-run',action='store_true');g.add_argument('--persist',action='store_true')
    a=p.parse_args(argv)
    try: return run(a.persist)
    except Exception as exc: print(f'Error: {exc}',file=__import__('sys').stderr);return 2
if __name__=='__main__':raise SystemExit(main())
