interface Props {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  trend?: "up" | "down" | "flat";
  trendLabel?: string;
  tone?: "ok" | "warn" | "bad" | "neutral";
}

const TONE: Record<NonNullable<Props["tone"]>, string> = {
  ok: "border-ok/20 text-ok",
  warn: "border-warn/20 text-warn",
  bad: "border-bad/30 text-bad",
  neutral: "border-line text-text",
};

export default function MetricCard({ label, value, hint, trend, trendLabel, tone = "neutral" }: Props) {
  const display = value == null ? "—" : value;
  return (
    <div className={`rounded-xl bg-card/60 border px-5 py-4 ${TONE[tone]}`}>
      <div className="text-[11px] uppercase tracking-widest text-muted">{label}</div>
      <div className="text-3xl font-semibold mt-2 tabular-nums">{display}</div>
      <div className="mt-1 flex items-baseline gap-2">
        {trend && (
          <span className={`text-xs ${trend === "up" ? "text-ok" : trend === "down" ? "text-bad" : "text-muted"}`}>
            {trend === "up" ? "↑" : trend === "down" ? "↓" : "→"} {trendLabel || ""}
          </span>
        )}
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
    </div>
  );
}
