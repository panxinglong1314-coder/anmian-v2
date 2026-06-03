import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { insightsOverview, type InsightResult, type OverviewMetrics } from "../lib/api";
import MetricCard from "../components/MetricCard";
import InsufficientNotice from "../components/InsufficientNotice";

const PERIODS = ["7d", "30d", "90d"] as const;
type Period = (typeof PERIODS)[number];

export default function Overview() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<Period>("30d");
  const [data, setData] = useState<InsightResult<OverviewMetrics> | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    setErr(null);
    insightsOverview(period)
      .then((d) => setData(d))
      .catch((e) => setErr((e as Error).message))
      .finally(() => setLoading(false));
  }, [period]);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text">{t("overview.title")}</h1>
          <p className="text-muted text-sm mt-1">{t("overview.subtitle")}</p>
        </div>
        <div className="flex gap-1 rounded-lg bg-card/40 border border-line p-1">
          {PERIODS.map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded text-xs transition ${
                period === p ? "bg-accent text-bg font-medium" : "text-muted hover:text-text"
              }`}
            >
              {t(`common.period.${p}`)}
            </button>
          ))}
        </div>
      </header>

      {loading && <div className="text-muted text-sm">{t("common.loading")}</div>}
      {err && <div className="rounded-xl bg-bad/5 border border-bad/30 text-bad p-4 text-sm">{err}</div>}

      {data && data.status === "insufficient_data" && (
        <InsufficientNotice n={data.n} kMin={data.k_min} />
      )}

      {data && data.status === "ok" && (
        <>
          {/* V2-2: deltas 字典 (可能为 undefined,例如旧 backend) */}
          {(() => null)()}
          {/* Engagement row */}
          <section>
            <h2 className="text-xs uppercase tracking-widest text-muted mb-3">{t("overview.engagement")}</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                label={t("overview.activeUsers")}
                value={`${data.engagement.active_users} / ${data.engagement.total_users}`}
                hint={t("overview.activationRateLabel", { pct: data.engagement.activation_rate })}
                tone={data.engagement.activation_rate >= 50 ? "ok" : "warn"}
                delta={data.deltas?.active_users}
              />
              <MetricCard
                label={t("overview.completionRate")}
                value={data.engagement.completion_rate != null ? `${data.engagement.completion_rate}%` : "—"}
                hint={t("overview.completionHint")}
                tone={
                  data.engagement.completion_rate == null
                    ? "neutral"
                    : data.engagement.completion_rate >= 60 ? "ok" : "warn"
                }
                delta={data.deltas?.completion_rate}
                unit="%"
              />
              <MetricCard
                label={t("overview.totalUsersN")}
                value={data.n}
                hint={t("overview.kAggregated")}
              />
            </div>
          </section>

          {/* Sleep row */}
          <section>
            <h2 className="text-xs uppercase tracking-widest text-muted mb-3">{t("overview.sleep")}</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                label={t("overview.avgSE")}
                value={data.sleep.avg_se_pct != null ? `${data.sleep.avg_se_pct}%` : "—"}
                hint={t("overview.benchmarkSE")}
                tone={
                  data.sleep.avg_se_pct == null ? "neutral"
                  : data.sleep.avg_se_pct >= 85 ? "ok"
                  : data.sleep.avg_se_pct >= 75 ? "warn" : "bad"
                }
                delta={data.deltas?.avg_se_pct}
                unit="%"
              />
              <MetricCard
                label={t("overview.avgTST")}
                value={data.sleep.avg_tst_hours != null ? `${data.sleep.avg_tst_hours}h` : "—"}
                hint={t("overview.benchmarkTST")}
                tone={
                  data.sleep.avg_tst_hours == null ? "neutral"
                  : data.sleep.avg_tst_hours >= 7 ? "ok"
                  : data.sleep.avg_tst_hours >= 6 ? "warn" : "bad"
                }
                delta={data.deltas?.avg_tst_hours}
                unit="h"
              />
              <MetricCard
                label={t("overview.lowSeRatio")}
                value={data.sleep.low_se_ratio != null ? `${data.sleep.low_se_ratio}%` : "—"}
                hint={t("overview.lowSeHint")}
                tone={
                  data.sleep.low_se_ratio == null ? "neutral"
                  : data.sleep.low_se_ratio < 15 ? "ok"
                  : data.sleep.low_se_ratio < 30 ? "warn" : "bad"
                }
                delta={data.deltas?.low_se_ratio}
                unit="%"
              />
              <MetricCard
                label={t("overview.usersWithSleepData")}
                value={data.sleep.users_with_data}
                hint={t("overview.usersWithSleepHint")}
              />
            </div>
          </section>

          {/* Worry + Anxiety + Crisis row */}
          <section>
            <h2 className="text-xs uppercase tracking-widest text-muted mb-3">{t("overview.psyche")}</h2>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
              <MetricCard
                label={t("overview.topWorryDomain")}
                value={data.worry.top_domain ? t(`worryDomain.${data.worry.top_domain}`) : "—"}
                hint={t("overview.totalWorryRecordsHint", { n: data.worry.total_records })}
              />
              <MetricCard
                label={t("overview.avgRecoveryTurns")}
                value={data.anxiety.avg_recovery_turns != null ? data.anxiety.avg_recovery_turns : "—"}
                hint={t("overview.recoveryTurnsHint")}
              />
              <MetricCard
                label={t("overview.crisisHighMed")}
                value={`${data.crisis.high} / ${data.crisis.medium}`}
                hint={t("overview.crisisHint")}
                tone={data.crisis.high > 0 ? "bad" : data.crisis.medium > 0 ? "warn" : "ok"}
                delta={data.deltas?.crisis_high}
              />
              <MetricCard
                label={t("overview.crisisTotal")}
                value={data.crisis.total}
                hint={t("overview.crisisAnonymousNote")}
                tone="neutral"
                delta={data.deltas?.crisis_total}
              />
            </div>
          </section>

          <div className="rounded-xl bg-card/30 border border-line p-4 text-xs text-muted leading-relaxed">
            🔒 {t("overview.privacyFooter", { k: data.n, period: t(`common.period.${period}`) })}
          </div>
        </>
      )}
    </div>
  );
}
