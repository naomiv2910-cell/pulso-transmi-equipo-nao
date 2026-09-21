"""Three-fold expanding-window temporal backtest; never writes model artifacts."""
from __future__ import annotations
from pathlib import Path
import numpy as np, pandas as pd, matplotlib.pyplot as plt
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from features import FEATURE_COLUMNS, add_origin_features
from metrics import mean_station_wape, score, wape
from train import load_frame

ROOT=Path(__file__).resolve().parents[1]; TABLES=ROOT/"reports/tables"; FIGURES=ROOT/"reports/figures"
HORIZONS=(1,2,3,4); MODELS=("baseline_last","baseline_daily","baseline_weekly","gradient_boosting")
PARAMS={"learning_rate":0.08,"max_iter":250,"max_leaf_nodes":31,"min_samples_leaf":30,"l2_regularization":1.0,"random_state":42}

def fold_boundaries(start: pd.Timestamp)->list[tuple[pd.Timestamp,pd.Timestamp]]:
    return [(start+pd.Timedelta(days=int(d)),start+pd.Timedelta(days=int(d)+7)) for d in (24,31,38)]
def prepare(data: pd.DataFrame,horizon:int)->pd.DataFrame:
    x=data.copy(); grouped=x.groupby("station_id",sort=False)["demand"]
    x["target"]=grouped.shift(-horizon);x["target_at"]=x.observed_at+pd.Timedelta(minutes=15*int(horizon))
    x["baseline_last"]=x.demand;x["baseline_daily"]=grouped.shift(96-horizon);x["baseline_weekly"]=grouped.shift(672-horizon)
    return x.dropna(subset=FEATURE_COLUMNS+["target","baseline_daily","baseline_weekly"])
def run_backtest()->tuple[pd.DataFrame,pd.DataFrame,pd.DataFrame]:
    data=add_origin_features(load_frame()); start=data.observed_at.min().floor("D"); all_predictions=[]
    for fold,(valid_start,valid_end) in enumerate(fold_boundaries(start),1):
        for horizon in HORIZONS:
            x=prepare(data,horizon); train=x[x.target_at<valid_start]; valid=x[(x.target_at>=valid_start)&(x.target_at<valid_end)].copy()
            if train.empty or valid.empty: raise ValueError(f"Fold {fold} no tiene filas suficientes")
            prep=ColumnTransformer([("station",OneHotEncoder(handle_unknown="ignore",sparse_output=False),["station_id"])],remainder="passthrough")
            model=Pipeline([("features",prep),("regressor",HistGradientBoostingRegressor(**PARAMS))])
            model.fit(train[FEATURE_COLUMNS],train.target);valid["gradient_boosting"]=np.clip(model.predict(valid[FEATURE_COLUMNS]),0,None)
            keep=valid[["target_at","station_id","target",*MODELS]].copy();keep["fold"]=fold;keep["horizon_minutes"]=15*horizon
            keep["train_end"]=valid_start.isoformat();keep["validation_end"]=valid_end.isoformat();all_predictions.append(keep)
    predictions=pd.concat(all_predictions,ignore_index=True); metrics=[]; stations=[]
    for (fold,horizon,model),group in predictions.melt(id_vars=["fold","horizon_minutes","station_id","target_at","target","train_end","validation_end"],value_vars=MODELS,var_name="model",value_name="predicted").groupby(["fold","horizon_minutes","model"]):
        s=score(group.target,group.predicted);s["mean_station_wape"]=mean_station_wape(group,"target","predicted")
        metrics.append({"fold":fold,"horizon_minutes":horizon,"model":model,**s,"train_end":group.train_end.iloc[0],"validation_end":group.validation_end.iloc[0],"seed":42,**PARAMS})
        for station,g in group.groupby("station_id"):stations.append({"fold":fold,"horizon_minutes":horizon,"model":model,"station_id":station,"wape":wape(g.target,g.predicted),**score(g.target,g.predicted)})
    return pd.DataFrame(metrics),pd.DataFrame(stations),predictions
def main():
    metrics,stations,predictions=run_backtest();TABLES.mkdir(parents=True,exist_ok=True);FIGURES.mkdir(parents=True,exist_ok=True)
    metrics.to_csv(TABLES/"backtest_metrics.csv",index=False);stations.to_csv(TABLES/"backtest_station_metrics.csv",index=False);predictions.to_csv(TABLES/"backtest_predictions.csv",index=False)
    summary=metrics.groupby("model").agg(accuracy_mean=("accuracy","mean"),accuracy_std=("accuracy","std"),wape_mean=("mean_station_wape","mean"),wape_std=("mean_station_wape","std"),mae_mean=("mae","mean"),rmse_mean=("rmse","mean")).reset_index()
    ax=metrics.groupby(["fold","model"]).accuracy.mean().unstack().plot.bar(figsize=(10,6));ax.set_ylabel("Accuracy (%)");ax.set_title("Backtesting temporal por fold");plt.tight_layout();plt.savefig(FIGURES/"10_backtest_accuracy.png",dpi=180);plt.close()
    gb=stations[stations.model=="gradient_boosting"].groupby("station_id").wape.mean().sort_values();ax=gb.plot.bar(figsize=(11,6));ax.set_ylabel("WAPE");ax.set_title("Error Gradient Boosting por estación");plt.tight_layout();plt.savefig(FIGURES/"11_backtest_station_error.png",dpi=180);plt.close()
    gb_score=summary.loc[summary.model=="gradient_boosting","wape_mean"].iloc[0];base=summary[summary.model!="gradient_boosting"].wape_mean.min(); conclusion="supera consistentemente el mejor baseline" if gb_score<base else "no supera consistentemente todos los baselines"
    table="```text\n"+summary.to_string(index=False)+"\n```"
    (ROOT/"reports/backtest_report.md").write_text("# Backtesting temporal\n\nTres folds expansivos de siete días, 12 estaciones y horizontes de 15, 30, 45 y 60 minutos. No se sobrescribió ningún artefacto.\n\n"+table+f"\n\nConclusión: Gradient Boosting {conclusion}. La estabilidad se determina con la media y desviación entre folds.\n",encoding="utf-8")
    print(summary.to_string(index=False))
if __name__=="__main__":main()
