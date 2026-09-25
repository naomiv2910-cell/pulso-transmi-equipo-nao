import json
import numpy as np
import pandas as pd
import pytest
from monitor import prepare_observations, data_drift, performance, psi
from supabase_logging import SupabaseLogger


def synthetic(days=37, shift=0):
    times = pd.date_range('2026-07-01', periods=days*96, freq='15min', tz='UTC')
    local = times.tz_convert('America/Bogota')
    demand = 100 + local.dayofweek*12 + local.hour*3 + np.tile([-3,-1,1,3],len(times)//4)
    frame = pd.DataFrame({'station_id':'00001','observed_at':times,'demand':demand.astype(float)})
    cutoff=times[35*96-1]
    frame.loc[frame.observed_at > cutoff,'demand'] += shift
    return frame, cutoff


def test_seasonality_alone_does_not_raise_drift():
    f,cutoff=synthetic()
    report=data_drift(f,cutoff,{'00001':'Station'})
    assert report['status']=='stable'
    assert report['stations'][0]['recent_samples']==96
    assert report['stations'][0]['reference_samples']==35*96


def test_shift_detected_with_same_seasonal_profile():
    f,cutoff=synthetic(shift=60)
    report=data_drift(f,cutoff,{'00001':'Station'})
    assert report['status']=='high'
    assert report['stations'][0]['mean_shift'] > 1
    json.dumps(report,allow_nan=False)


def test_not_enough_recent_observations_is_not_healthy():
    f,cutoff=synthetic(); f=f.iloc[:35*96+48]
    assert data_drift(f,cutoff,{'00001':'Station'})['status']=='insufficient_data'


def test_psi_identity_and_finite_empty_bins():
    assert psi([0]*100,[0]*100)==pytest.approx(0)
    assert np.isfinite(psi([0]*100,[100]*100))


def test_only_complete_delivered_cycles_are_evaluated():
    obs=prepare_observations([{'station_id':'00001','observed_at':'2026-09-13T06:15:00Z','demand':100}])
    cycles=[{'id':'c','external_cycle_id':'official','target_end':'2026-09-13T06:30:00Z'}]
    predictions=[{'cycle_id':'c','model_id':'m','station_id':'00001','target_at':'2026-09-13T06:15:00Z','predicted_demand':90},
                 {'cycle_id':'c','model_id':'m','station_id':'00001','target_at':'2026-09-13T06:30:00Z','predicted_demand':90}]
    assert performance(obs,predictions,cycles)['evaluated_cycles']==0
    obs=pd.concat([obs,prepare_observations([{'station_id':'00001','observed_at':'2026-09-13T06:30:00Z','demand':100}])])
    result=performance(obs,predictions,cycles)
    assert result['accuracy']==90
    assert result['samples']==2
    assert result['evaluated_cycles']==1


def test_pagination_handles_server_cap_smaller_than_requested():
    class Client:
        select_all=SupabaseLogger.select_all
        def select(self,table,params):
            offset=int(params['offset'])
            return [{'id':i} for i in range(offset,min(offset+2,5))]
    assert len(Client().select_all('observations',{'order':'id.asc'}))==5
