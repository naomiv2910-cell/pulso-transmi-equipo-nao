import type { Prediction } from "@/lib/dashboard-data";

const colors: Record<number, string> = { 15: "#02b8d1", 30: "#3374db", 45: "#ff6f7d", 60: "#9a5bce" };

export function PredictionChart({ predictions }: { predictions: Prediction[] }) {
  if (!predictions.length) return <div className="empty-chart">Sin predicciones disponibles en Supabase.</div>;
  const stations = [...new Set(predictions.map((item) => item.station_id))];
  const max = Math.max(...predictions.map((item) => item.predicted_demand), 1);
  const width = 960, height = 360, left = 58, top = 24, chartHeight = 260;
  const stationWidth = (width - left - 20) / stations.length;
  const barWidth = Math.max(3, stationWidth / 5.4);

  return (
    <div className="chart-wrap">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-labelledby="chart-title chart-desc">
        <title id="chart-title">Predicciones por estación y horizonte</title>
        <desc id="chart-desc">Barras agrupadas para horizontes de 15, 30, 45 y 60 minutos.</desc>
        {[0, .25, .5, .75, 1].map((ratio) => {
          const y = top + chartHeight * (1 - ratio);
          return <g key={ratio}><line x1={left} x2={width - 14} y1={y} y2={y} className="grid-line" /><text x={left - 10} y={y + 4} textAnchor="end" className="axis-label">{Math.round(max * ratio)}</text></g>;
        })}
        {stations.map((station, stationIndex) => {
          const rows = predictions.filter((item) => item.station_id === station);
          const baseX = left + stationIndex * stationWidth;
          return <g key={station}>{rows.map((item, index) => {
            const barHeight = (item.predicted_demand / max) * chartHeight;
            return <rect key={`${station}-${item.horizon_minutes}`} x={baseX + 8 + index * barWidth} y={top + chartHeight - barHeight} width={barWidth - 2} height={barHeight} rx="3" fill={colors[item.horizon_minutes] ?? "#02b8d1"}><title>{station} · {item.horizon_minutes} min: {item.predicted_demand.toFixed(1)}</title></rect>;
          })}<text x={baseX + stationWidth / 2} y={top + chartHeight + 25} textAnchor="middle" className="station-label">{station}</text></g>;
        })}
      </svg>
      <div className="legend">{[15, 30, 45, 60].map((horizon) => <span key={horizon}><i style={{ background: colors[horizon] }} />{horizon} min</span>)}</div>
    </div>
  );
}
