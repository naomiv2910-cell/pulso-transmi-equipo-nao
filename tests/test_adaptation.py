import json
import numpy as np
import pandas as pd
import pytest
from features import ADAPTIVE_FEATURE_COLUMNS, add_origin_features, build_target_features
from test_features import history
from adapt import examples, metrics, promotion_gate
from predict import build_payload, PredictionError
from test_predict import cycle, predictions_for


def test_adaptive_features_match_live_and_ignore_future():
    obs,ctx=history(800);cutoff=obs.observed_at.iloc[750]
    targets=[{'station_id':'02300','target_at':(cutoff+pd.Timedelta(minutes=h)).isoformat(),'horizon_minutes':h} for h in (15,30,45,60)]
    live=build_target_features(obs,ctx,targets,cutoff.isoformat())
    train=add_origin_features(obs.merge(ctx,on='observed_at'))
    expected=train[train.observed_at==cutoff][ADAPTIVE_FEATURE_COLUMNS].iloc[0]
    for _,row in live.iterrows():
        pd.testing.assert_series_equal(row[ADAPTIVE_FEATURE_COLUMNS],expected,check_names=False)
    changed=obs.copy();changed.loc[changed.observed_at>cutoff,'demand']=1e9
    future_ctx=ctx.copy();future_ctx.loc[future_ctx.observed_at>cutoff,'rain_mm']=1e9
    altered=build_target_features(changed,future_ctx,targets,cutoff.isoformat())
    pd.testing.assert_frame_equal(live[ADAPTIVE_FEATURE_COLUMNS],altered[ADAPTIVE_FEATURE_COLUMNS])
    assert live.origin_demand.eq(obs.demand.iloc[750]).all()


def test_training_targets_purged_before_validation_origins():
    obs,ctx=history(900);x=examples(add_origin_features(obs.merge(ctx,on='observed_at')),60)
    cutoff=obs.observed_at.iloc[800]
    train=x[x.target_at<=cutoff];valid=x[x.observed_at>=cutoff]
    assert train.target_at.max()<valid.target_at.min()
    assert (x.target_at-x.observed_at).eq(pd.Timedelta(minutes=60)).all()
    assert (x.target-x.origin_demand).eq(4).all()


def test_payload_version_and_training_cutoff():
    c=cycle();artifact={'model_version':'champion-2.0.0','created_at':'2026-09-30T00:00:00Z',
        'models':{h:{'trained_until':c['data_cutoff']} for h in (15,30,45,60)}}
    payload,_=build_payload(c,artifact,predictions_for(c),'a'*40)
    assert payload['model']['version']=='champion-2.0.0'
    artifact['models'][60]['trained_until']='2027-01-01T00:00:00Z'
    with pytest.raises(PredictionError,match='posteriores'):build_payload(c,artifact,predictions_for(c),'a'*40)


def test_promotion_rejects_station_regression_even_when_mean_improves():
    times=pd.date_range('2026-01-01',periods=2,freq='D',tz='UTC')
    rows=[]
    for station in ['a','b','c']:
        for t in times:rows.append(dict(station_id=station,target_at=t,target=100,champion=70,candidate=60 if station=='a' else 100,last=50,daily=50,weekly=50))
    passed,_,_,checks=promotion_gate(pd.DataFrame(rows),times[0])
    assert checks['gain_at_least_2pp'] and not checks['no_station_loses_over_5pp'] and not passed


def test_version_registry_demotes_before_upsert_and_keeps_archived_metadata(tmp_path,monkeypatch):
    import joblib
    import supabase_logging as sl
    (tmp_path/'artifacts/versions').mkdir(parents=True)
    def meta(version,features):
        return dict(model_version=version,created_at='2026-09-30T00:00:00Z',training_start='2026-08-28T00:00:00Z',models={15:{'features':features}},champion_by_horizon={})
    joblib.dump(meta('champion-2.0.0',['new_feature']),tmp_path/'artifacts/champion.joblib')
    joblib.dump(meta('champion-1.0.0',['old_feature']),tmp_path/'artifacts/versions/champion-1.0.0.joblib')
    monkeypatch.setattr(sl,'ROOT',tmp_path)
    class Registry:
        persist_submission=sl.SupabaseLogger.persist_submission
        def __init__(self):self.calls=[]
        def request(self,method,table,**kw):self.calls.append((method,table,kw));return []
        def upsert(self,table,payload,*a,**kw):self.calls.append(('upsert',table,payload));return [{'id':table}]
    c={'cycle_id':'x','targets':[{'station_id':'02300','target_at':'2026-09-18T02:00:00Z','horizon_minutes':15}]}
    for version in ['champion-2.0.0','champion-1.0.0']:
        client=Registry();payload={'data_cutoff':'2026-09-18T01:45:00Z','model':{'version':version,'training_data_end':'2026-09-18T01:30:00Z'},'predictions':[{'station_id':'02300','target_at':'2026-09-18T02:00:00Z','value':1}]}
        client.persist_submission(c,payload,'2026-09-30T18:00:00Z')
        model=[v for action,table,v in client.calls if action=='upsert' and table=='model_versions'][0]
        assert model['features']==(['new_feature'] if version.endswith('2.0.0') else ['old_feature'])
        assert model['training_start']=='2026-08-28T00:00:00+00:00'
        patches=[i for i,(action,_,_) in enumerate(client.calls) if action=='PATCH']
        if version.endswith('2.0.0'):
            assert patches and patches[0]<next(i for i,(action,table,_) in enumerate(client.calls) if action=='upsert' and table=='model_versions')
        else:assert not patches and not model['is_champion']
