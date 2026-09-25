type Props = { eyebrow: string; value: string; detail: string; accent?: "cyan" | "coral" | "navy" };

export function MetricCard({ eyebrow, value, detail, accent = "cyan" }: Props) {
  return (
    <article className={`metric-card accent-${accent}`}>
      <p>{eyebrow}</p>
      <strong>{value}</strong>
      <span>{detail}</span>
    </article>
  );
}
