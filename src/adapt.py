"""Reproducible temporal candidate selection, locked holdout, and gated artifact export."""
from __future__ import annotations
import argparse, hashlib, json
from datetime import datetime, timezone
from pathlib import Path
import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from features import FEATURE_COLUMNS, ADAPTIVE_FEATURE_COLUMNS, CONTEXT_COLUMNS, add_origin_features
from predict import APIClient, fetch_pages

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw'
OUT=ROOT/'reports/adaptation'
# Declared before inspecting locked holdout. No hyperparameter search on holdout.
CONFIGS={
 'refit_21d':dict(days=21, adaptive=False, half_life=None),
 'adaptive_21d':dict(days=21, adaptive=True, half_life=None),
 'adaptive_7d':dict(days=7, adaptive=True, half_life=None),
 'adaptive_weighted_21d':dict(days=21, adaptive=True, half_life=4),
}

def snapshot(cutoff=None):
    RAW.mkdir(exist_ok=True)
    with APIClient() as api:
        stream=pd.DataFrame(fetch_pages(api,'/v1/stream/observations'))
    old=pd.read_csv(RAW/'observations.csv',dtype={'station_id':str})
    obs=pd.concat([old,stream],ignore_index=True)[['station_id','observed_at','demand']]
    obs['observed_at']=pd.to_datetime(obs.observed_at,utc=True,format='mixed')
    obs=obs.drop_duplicates(['station_id','observed_at'],keep='last').sort_values(['station_id','observed_at'])
    if cutoff is not None: obs=obs[obs.observed_at<=pd.Timestamp(cutoff)]
    obs.to_csv(RAW/'adaptation_observations.csv',index=False)
    return obs

def load_data():
    obs=pd.read_csv(RAW/'adaptation_observations.csv',dtype={'station_id':str})
    obs['observed_at']=pd.to_datetime(obs.observed_at,utc=True)
    if not obs.groupby('station_id').observed_at.diff().dropna().eq(pd.Timedelta(minutes=15)).all():
        raise ValueError('Historia no regular: no es seguro desplazar targets por filas')
    ctx=pd.read_csv(RAW/'context.csv');ctx['observed_at']=pd.to_datetime(ctx.observed_at,utc=True)
    data=obs.merge(ctx,on='observed_at',how='left',validate='many_to_one').sort_values(['station_id','observed_at'])
    data[list(CONTEXT_COLUMNS)]=data.groupby('station_id')[list(CONTEXT_COLUMNS)].ffill()
    return add_origin_features(data)

def examples(data,h):
    x=data.copy();g=x.groupby('station_id').demand
    x['target']=g.shift(-h//15)
    x['target_at']=x.observed_at+pd.Timedelta(minutes=h)
    x['horizon_minutes']=h
    x['last']=x.demand;x['daily']=x[f'daily_target_{h}'];x['weekly']=x[f'weekly_target_{h}']
    return x.dropna(subset=ADAPTIVE_FEATURE_COLUMNS+['target'])

def fit(x,cutoff,config):
    train=x[(x.target_at<=cutoff)&(x.observed_at>=cutoff-pd.Timedelta(days=config['days']))].copy()
    columns=ADAPTIVE_FEATURE_COLUMNS if config['adaptive'] else FEATURE_COLUMNS
    model=Pipeline([('features',ColumnTransformer([('station',OneHotEncoder(handle_unknown='ignore',sparse_output=False),['station_id'])],remainder='passthrough')),
      ('regressor',HistGradientBoostingRegressor(learning_rate=.08,max_iter=250,max_leaf_nodes=31,min_samples_leaf=30,l2_regularization=1,early_stopping=False,random_state=42))])
    # Equal station influence, computed only from the training partition.
    weights=1/train.groupby('station_id').target.transform('mean').clip(lower=1)
    if config['half_life']:
        age=(cutoff-train.target_at).dt.total_seconds()/86400
        weights*=np.power(.5,age/config['half_life'])
    weights/=weights.mean()
    model.fit(train[columns],train.target,regressor__sample_weight=weights)
    return model,columns,{'rows':len(train),'origin_start':train.observed_at.min().isoformat(),'target_end':train.target_at.max().isoformat()}

def metrics(x,col):
    per=[]
    for station,g in x.groupby('station_id'):
        w=float(abs(g.target-g[col]).sum()/max(g.target.sum(),1))
        per.append({'station_id':station,'wape':w,'accuracy':100*max(0,1-w)})
    return {'accuracy':float(np.mean([v['accuracy'] for v in per])), 'wape':float(np.mean([v['wape'] for v in per])), 'samples':len(x),'stations':per}

def evaluate(data,artifact,config,start,end):
    predictions=[];models={};training={}
    for h in (15,30,45,60):
        x=examples(data,h)
        # Origins are at/after fit cutoff: even the shortest forecast is out of sample.
        valid=x[(x.observed_at>=start)&(x.target_at<=end)].copy()
        m,cols,trace=fit(x,start,config)
        valid['candidate']=np.clip(m.predict(valid[cols]),0,None)
        old=artifact['models'][h]
        valid['champion']=np.clip(old['model'].predict(valid[old['features']]),0,None)
        predictions.append(valid[['station_id','observed_at','target_at','target','horizon_minutes','candidate','champion','last','daily','weekly']])
        models[h]=(m,cols);training[h]=trace
    return pd.concat(predictions,ignore_index=True),models,training

def promotion_gate(frame,mid):
    scores={name:metrics(frame,name) for name in ['candidate','champion','last','daily','weekly']}
    windows=[]
    for mask in (frame.target_at<=mid,frame.target_at>mid):
        f=frame[mask]
        windows.append({name:metrics(f,name)['accuracy'] for name in ['candidate','champion']})
    loss=max(o['accuracy']-n['accuracy'] for o,n in zip(scores['champion']['stations'],scores['candidate']['stations']))
    checks={'gain_at_least_2pp':scores['candidate']['accuracy']>=scores['champion']['accuracy']+2,
      'both_windows_improve':all(w['candidate']>w['champion'] for w in windows),
      'no_station_loses_over_5pp':loss<=5,
      'beats_all_baselines':all(scores['candidate']['accuracy']>scores[b]['accuracy'] for b in ['last','daily','weekly'])}
    return all(checks.values()),scores,windows,checks

def run(download=False, cutoff=None):
    if download:snapshot(cutoff)
    data=load_data();end=data.observed_at.max();holdout_start=end-pd.Timedelta(days=2);dev_start=end-pd.Timedelta(days=4)
    reference_path=ROOT/'artifacts/versions/champion-1.0.0.joblib'
    old=joblib.load(reference_path)
    OUT.mkdir(parents=True,exist_ok=True)
    dev={}
    for name,config in CONFIGS.items():
        f,_,_=evaluate(data,old,config,dev_start,holdout_start)
        dev[name]=metrics(f,'candidate')['accuracy']
        print('development',name,round(dev[name],3),flush=True)
    winner=max(dev,key=dev.get); config=CONFIGS[winner]
    print('locked choice',winner,flush=True)
    f,_,trace=evaluate(data,old,config,holdout_start,end)
    passed,scores,windows,checks=promotion_gate(f,holdout_start+pd.Timedelta(days=1))
    f.to_csv(OUT/'holdout_predictions.csv',index=False)
    report={'created_at':datetime.now(timezone.utc).isoformat(),'data_sha256':hashlib.sha256((RAW/'adaptation_observations.csv').read_bytes()).hexdigest(),
      'context_sha256':hashlib.sha256((RAW/'context.csv').read_bytes()).hexdigest(),
      'previous_artifact_sha256':hashlib.sha256(reference_path.read_bytes()).hexdigest(),
      'data_end':end.isoformat(),'development_start':dev_start.isoformat(),'holdout_start':holdout_start.isoformat(),
      'selection_scores':dev,'selected':winner,'config':config,'training_trace_holdout':trace,
      'holdout':scores,'windows':windows,'checks':checks,'promotable':passed,
      'by_horizon':{str(h):{n:metrics(g,n) for n in ['candidate','champion']} for h,g in f.groupby('horizon_minutes')}}
    print(json.dumps({'holdout_accuracy':{n:s['accuracy'] for n,s in scores.items()},'windows':windows,'checks':checks,'promotable':passed}),flush=True)
    if passed:
        models={};trace={}
        for h in (15,30,45,60):
            model,cols,t=fit(examples(data,h),end,config);trace[h]=t
            models[h]={'model':model,'features':cols,'horizon_steps':h//15,'trained_until':end.isoformat(),'version':'champion-2.0.0'}
        summary={str(h):{'model':'HistGradientBoostingRegressor','accuracy_pct':metrics(g,'candidate')['accuracy'], 'wape':metrics(g,'candidate')['wape']} for h,g in f.groupby('horizon_minutes')}
        artifact={'artifact_type':'pulso_transmi_champion','artifact_version':'2.0.0','model_version':'champion-2.0.0','created_at':report['created_at'],
          'frequency_minutes':15,'horizons_minutes':[15,30,45,60],'validation_start':holdout_start.isoformat(),'validation_end':end.isoformat(),
          'training_start':min(t['origin_start'] for t in trace.values()),'champion_by_horizon':summary,'models':models,'adaptation':{'config':config,'data_sha256':report['data_sha256']}}
        joblib.dump(artifact,ROOT/'artifacts/candidate-2.0.0.joblib',compress=3)
        report['final_training_trace']=trace
        report['candidate_sha256']=hashlib.sha256((ROOT/'artifacts/candidate-2.0.0.joblib').read_bytes()).hexdigest()
    (OUT/'decision.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--download',action='store_true');p.add_argument('--cutoff');a=p.parse_args();run(a.download,a.cutoff)
