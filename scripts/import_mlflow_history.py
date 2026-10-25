"""Import preserved results into MLflow; does not pretend these were live-tracked runs."""
from pathlib import Path
from datetime import datetime, timezone
import csv, hashlib, json
import mlflow
from mlflow import MlflowClient

ROOT=Path(__file__).resolve().parents[1]
STORE=ROOT/'.mlflow'
STORE.mkdir(exist_ok=True)
mlflow.set_tracking_uri(f"sqlite:///{STORE/'mlflow.db'}")
client=MlflowClient()
manifest=[]

def record(experiment,name,source,key,params,metrics,extra_tags=None):
    path=ROOT/source
    fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
    exp=client.get_experiment_by_name(experiment)
    eid=exp.experiment_id if exp else client.create_experiment(experiment,artifact_location=(STORE/'artifacts').as_uri())
    import_id=hashlib.sha256(f'{source}:{fingerprint}:{key}'.encode()).hexdigest()
    found=client.search_runs([eid],f"tags.import_id = '{import_id}'")
    if found:
        run_id=found[0].info.run_id
    else:
        with mlflow.start_run(experiment_id=eid,run_name=name,tags={
          'import_id':import_id,'registro':'historico_importado','source_file':source,
          'source_sha256':fingerprint,'imported_at':datetime.now(timezone.utc).isoformat(),
          'mlflow.note.content':'Resultados históricos importados desde evidencia conservada. No se ejecutó ni reentrenó este experimento durante la importación.',
          **(extra_tags or {})}) as run:
            mlflow.log_params(params)
            mlflow.log_metrics(metrics)
            mlflow.log_artifact(str(path),artifact_path='evidence')
            run_id=run.info.run_id
    # Independently compare persisted values with the original source.
    saved=client.get_run(run_id)
    for k,v in metrics.items():
        if abs(saved.data.metrics[k]-v)>1e-9:raise ValueError(f'Métrica distinta: {k}')
    manifest.append({'experiment':experiment,'experiment_id':eid,'name':name,'run_id':run_id,'source':source,'sha256':fingerprint,'metrics':metrics})

source='reports/adaptation/decision.json'
r=json.loads((ROOT/source).read_text())
for name,score in r['selection_scores'].items():
    record('Pulso TransMi - Seleccion - Historicos importados',name,source,'selection:'+name,
      {'candidate':name,'validation_start':r['development_start'],'validation_end':r['holdout_start']},
      {'accuracy_pct':score},{'original_recorded_at':r['created_at']})
labels={'candidate':'Champion 2 - adaptado','champion':'Champion 1 - anterior','last':'Baseline - ultima observacion','daily':'Baseline - diario','weekly':'Baseline - semanal'}
for name,values in r['holdout'].items():
    record('Pulso TransMi - Holdout drift - Historicos importados',labels[name],source,'holdout:'+name,
      {'model':name,'validation_start':r['holdout_start'],'validation_end':r['data_end'],'evaluation':'holdout temporal reservado','samples':values['samples']},
      {'accuracy_pct':values['accuracy'],'wape':values['wape']},
      {'original_recorded_at':r['created_at'],'data_sha256':r['data_sha256']})
source='reports/tables/model_metrics.csv'
with (ROOT/source).open() as f:
    for row in csv.DictReader(f):
        key=f"{row['model']}-h{row['horizon_minutes']}"
        record('Pulso TransMi - Inicial - Historicos importados',key,source,key,
          {k:row[k] for k in ['model','horizon_minutes','train_rows','validation_rows','version']},
          {'accuracy_pct':float(row['accuracy_pct']),'mean_station_wape':float(row['mean_station_wape']),'mae':float(row['mae'])})
(ROOT/'reports/evidence/mlflow-import-manifest.json').write_text(json.dumps(manifest,indent=2,ensure_ascii=False)+'\n')
print(json.dumps({'runs':len(manifest),'experiments':{x['experiment']:x['experiment_id'] for x in manifest}},ensure_ascii=False))
