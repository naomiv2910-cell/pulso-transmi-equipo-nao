create index context_snapshot_id_idx
  on public.context_observations (snapshot_id);

create index observations_snapshot_id_idx
  on public.observations (snapshot_id);

create index predictions_model_id_idx
  on public.predictions (model_id);

create index predictions_station_id_idx
  on public.predictions (station_id);

create index evaluation_metrics_model_id_idx
  on public.evaluation_metrics (model_id);

create index evaluation_metrics_station_id_idx
  on public.evaluation_metrics (station_id);

