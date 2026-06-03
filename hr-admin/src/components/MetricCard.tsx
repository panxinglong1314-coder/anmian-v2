import type { MetricDelta } from "../lib/api";

interface Props {
  label: string;
  value: string | number | null | undefined;
  hint?: string;
  /** V2-2 同比环比 delta;若提供则覆盖 legacy trend/trendLabel。 */
  delta?: MetricDelta | null;
  /** 单位后缀,仅用于显示 prev 值 (例如 "%"、"h")。 */
  unit?: string;
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

function deltaPresentation(d: MetricDelta) {
  // arrow direction = 数值方向; color = 业务方向 (trend)
  const dpct = d.delta_pct;
  const arrow = dpct == null || dpct === 0 ? "→" : dpct > 0 ? "↑" : "↓";
  const color =
    d.trend === "improving" ? "text-ok"
    : d.trend === "deteriorating" ? "text-bad"
    : d.trend === "stable" ? "text-muted"
    : "text-muted/60";
  const label =
    dpct == null ? "vs 上期"
    : `${dpct > 0 ? "+" : ""}${dpct.toFixed(1)}% vs 上期`;
  return { arrow, color, label };
}

export default function MetricCard({
  label, value, hint, delta, unit, trend, trendLabel, tone = "neutral",
}: Props) {
  const display = value == null ? "—" : value;
  const showDelta = !!delta && delta.prev != null;
  return (
    <div className={`rounded-xl bg-card/60 border px-5 py-4 ${TONE[tone]}`}>
      <div className="text-[11px] uppercase tracking-widest text-muted">{label}</div>
      <div className="text-3xl font-semibold mt-2 tabular-nums">{display}</div>
      <div className="mt-1 flex items-baseline gap-2 flex-wrap">
        {showDelta && (() => {
          const { arrow, color, label: deltaLabel } = deltaPresentation(delta!);
          return (
            <span
              className={`text-xs ${color}`}
              title={delta!.prev != null ? `上期: ${delta!.prev}${unit ?? ""}` : ""}
            >
              {arrow} {deltaLabel}
            </span>
          );
        })()}
        {!showDelta && trend && (
          <span className={`text-xs ${trend === "up" ? "text-ok" : trend === "down" ? "text-bad" : "text-muted"}`}>
            {trend === "up" ? "↑" : trend === "down" ? "↓" : "→"} {trendLabel || ""}
          </span>
        )}
        {hint && <span className="text-[11px] text-muted">{hint}</span>}
      </div>
    </div>
  );
}
