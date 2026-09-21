"""Shared forecasting metrics."""
from __future__ import annotations
import numpy as np
import pandas as pd

def wape(actual, predicted) -> float:
    a=np.asarray(actual,float); p=np.asarray(predicted,float); denom=np.abs(a).sum()
    return float(np.abs(a-p).sum()/denom) if denom else 0.0
def accuracy(actual, predicted) -> float: return 100.0*max(0.0,1.0-wape(actual,predicted))
def score(actual, predicted) -> dict[str,float]:
    a=np.asarray(actual,float); p=np.asarray(predicted,float); error=a-p
    return {"wape":wape(a,p),"accuracy":accuracy(a,p),"mae":float(np.abs(error).mean()),"rmse":float(np.sqrt(np.mean(error**2)))}
def mean_station_wape(frame: pd.DataFrame, actual="actual", predicted="predicted") -> float:
    values=[wape(g[actual],g[predicted]) for _,g in frame.groupby("station_id")]
    return float(np.mean(values)) if values else 0.0
