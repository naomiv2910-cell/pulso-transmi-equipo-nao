type Props = { label: string; tone?: "success" | "warning" | "neutral" };

export function StatusPill({ label, tone = "neutral" }: Props) {
  return <span className={`status-pill status-${tone}`}><span aria-hidden="true" />{label}</span>;
}
