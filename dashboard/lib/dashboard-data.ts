import "server-only";
export type Prediction = { station_id:string; station_name:string; horizon_minutes:number; predicted_demand:number; target_at:string };
export type DriftStation = { station_id:string; name:string; reference_samples:number; recent_samples:number; status:string; psi:number|null; mean_shift:number|null };
export type DashboardData = {
 schema_version:number; generated_at:string; stale:boolean;
 observations:{count:number;last_at:string|null};
 model:{version:string;algorithm:string;training_end:string};
 drift:{status:string;window_start?:string;window_end?:string;reference_start?:string;reference_end?:string;stations:DriftStation[];method:string;note:string};
 performance:{status:string;accuracy:number|null;wape:number|null;mae:number|null;samples:number;evaluated_cycles:number;pending_cycles:number;history:{cycle_id:string;target_end:string;accuracy:number;samples:number}[]};
 deliveries:{stored_cycles:number;latest_cycle:string|null;latest_submitted_at:string|null;latest_predictions:Prediction[]};
 recommendation:string;
};
export const snapshotURL = "https://raw.githubusercontent.com/naomiv2910-cell/pulso-transmi-equipo-nao/dashboard-data/dashboard.json";
export async function getDashboardData():Promise<DashboardData|null> {
 try {
  const response=await fetch(snapshotURL,{cache:"no-store",signal:AbortSignal.timeout(10000)});
  if(!response.ok)return null;
  const data=await response.json();
  if(data.schema_version!==1||!Number.isFinite(Date.parse(data.generated_at))||!Array.isArray(data.drift?.stations)||!Array.isArray(data.performance?.history)||!Array.isArray(data.deliveries?.latest_predictions))return null;
  return {...data, stale: Date.now()-Date.parse(data.generated_at)>7200000} as DashboardData;
 }catch{return null;}
}
