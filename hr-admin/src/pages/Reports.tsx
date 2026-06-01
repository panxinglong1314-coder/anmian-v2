import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  insightsSleep, insightsAnxiety, insightsWorry, insightsCrisis, insightsEngagement,
  downloadMonthlyPdf,
  type InsightResult, type SleepMetrics, type AnxietyMetrics, type WorryMetrics,
  type CrisisMetrics, type EngagementMetrics,
} from "../lib/api";
import { currentLocale } from "../i18n";
import InsufficientNotice from "../components/InsufficientNotice";

const PERIODS = ["7d", "30d", "90d"] as const;
type Period = (typeof PERIODS)[number];

interface Bundle {
  sleep: InsightResult<SleepMetrics> | null;
  anxiety: InsightResult<AnxietyMetrics> | null;
  worry: InsightResult<WorryMetrics> | null;
  crisis: InsightResult<CrisisMetrics> | null;
  engagement: InsightResult<EngagementMetrics> | null;
}

export default function Reports() {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<Period>("30d");
  const [b, setB] = useState<Bundle>({ sleep: null, anxiety: null, worry: null, crisis: null, engagement: null });
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    setLoading(true);
    Promise.all([
      insightsSleep(period), insightsAnxiety(period), insightsWorry(period),
      insightsCrisis(period), insightsEngagement(period),
    ])
      .then(([s, a, w, c, e]) => setB({ sleep: s, anxiety: a, worry: w, crisis: c, engagement: e }))
      .catch((e) => console.error(e))
      .finally(() => setLoading(false));
  }, [period]);

  return (
    <div className="space-y-6">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-text">{t("reports.title")}</h1>
          <p className="text-muted text-sm mt-1">{t("reports.subtitle")}</p>
        </div>
        <div className="flex gap-1 rounded-lg bg-card/40 border border-line p-1">
          {PERIODS.map((p) => (
            <button key={p} onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 rounded text-xs transition ${
                period === p ? "bg-accent text-bg font-medium" : "text-muted hover:text-text"
              }`}>{t(`common.period.${p}`)}</button>
          ))}
        </div>
      </header>

      {loading && <div className="text-muted text-sm">{t("common.loading")}</div>}

      {/* Sleep section */}
      {b.sleep && (
        <Section title={t("reports.sec.sleep")} result={b.sleep}>
          {b.sleep.status === "ok" && (
            <SleepBlock m={b.sleep} />
          )}
        </Section>
      )}

      {/* Anxiety */}
      {b.anxiety && (
        <Section title={t("reports.sec.anxiety")} result={b.anxiety}>
          {b.anxiety.status === "ok" && (
            <div className="space-y-3 text-sm">
              <div>{t("reports.anxiety.recovery")}: <span className="text-text font-medium">{b.anxiety.avg_recovery_turns ?? "—"}</span></div>
              <div>{t("reports.anxiety.momentum")}:</div>
              <DistroBar dist={b.anxiety.momentum_distribution} />
            </div>
          )}
        </Section>
      )}

      {/* Worry */}
      {b.worry && (
        <Section title={t("reports.sec.worry")} result={b.worry}>
          {b.worry.status === "ok" && (
            <div className="space-y-3 text-sm">
              <div>{t("reports.worry.top")}: <span className="text-accent font-medium">
                {b.worry.top_domain ? t(`worryDomain.${b.worry.top_domain}`) : "—"}
              </span></div>
              <DistroBar dist={b.worry.distribution_pct} pct />
            </div>
          )}
        </Section>
      )}

      {/* Crisis */}
      {b.crisis && (
        <Section title={t("reports.sec.crisis")} result={b.crisis}>
          {b.crisis.status === "ok" && (
            <div className="grid grid-cols-4 gap-3 text-sm">
              <Cell label={t("reports.crisis.high")} value={b.crisis.high} tone="bad" />
              <Cell label={t("reports.crisis.medium")} value={b.crisis.medium} tone="warn" />
              <Cell label={t("reports.crisis.low")} value={b.crisis.low} tone="neutral" />
              <Cell label={t("reports.crisis.total")} value={b.crisis.total} tone="neutral" />
              <div className="col-span-4 text-[11px] text-muted leading-relaxed">
                🔒 {t("reports.crisis.noteAnonymous")}
              </div>
            </div>
          )}
        </Section>
      )}

      {/* Engagement */}
      {b.engagement && (
        <Section title={t("reports.sec.engagement")} result={b.engagement}>
          {b.engagement.status === "ok" && (
            <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
              <Cell label={t("reports.engagement.activeTotal")} value={`${b.engagement.active_users}/${b.engagement.total_users}`} tone="neutral" />
              <Cell label={t("reports.engagement.activation")} value={`${b.engagement.activation_rate}%`} tone={b.engagement.activation_rate >= 50 ? "ok" : "warn"} />
              <Cell label={t("reports.engagement.sessions")} value={b.engagement.total_sessions} tone="neutral" />
              <Cell label={t("reports.engagement.completion")} value={b.engagement.completion_rate != null ? `${b.engagement.completion_rate}%` : "—"} tone={b.engagement.completion_rate != null && b.engagement.completion_rate >= 60 ? "ok" : "warn"} />
            </div>
          )}
        </Section>
      )}

      <PdfDownload />
    </div>
  );
}

function PdfDownload() {
  const { t } = useTranslation();
  const locale = currentLocale();
  const now = new Date();
  // 默认上月(月报通常生成上月数据)
  const lastMonth = new Date(now.getFullYear(), now.getMonth() - 1, 15);
  const defaultYm = `${lastMonth.getFullYear()}-${String(lastMonth.getMonth() + 1).padStart(2, "0")}`;
  const [ym, setYm] = useState(defaultYm);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  const onDownload = async () => {
    setErr(null);
    setBusy(true);
    try {
      await downloadMonthlyPdf(ym, locale);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="rounded-xl bg-card/60 border border-line p-5">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div>
          <h3 className="text-sm font-medium text-text">📥 {t("reports.pdf.title")}</h3>
          <p className="text-xs text-muted mt-1">{t("reports.pdf.hint")}</p>
        </div>
        <div className="flex items-center gap-2">
          <input
            type="month"
            value={ym}
            onChange={(e) => setYm(e.target.value)}
            className="px-3 py-2 rounded bg-bg border border-line text-text text-sm outline-none focus:border-accent transition"
          />
          <button
            onClick={() => void onDownload()}
            disabled={busy}
            className="px-5 py-2 rounded bg-accent text-bg font-medium text-sm disabled:opacity-40 hover:bg-accent/90 transition"
          >
            {busy ? "…" : t("reports.pdf.download")}
          </button>
        </div>
      </div>
      {err && <p className="text-bad text-xs mt-3">{err}</p>}
    </div>
  );
}

function Section({ title, result, children }: { title: string; result: { status: string; n: number; k_min?: number }; children: React.ReactNode }) {
  return (
    <section className="rounded-xl bg-card/60 border border-line p-5">
      <h2 className="text-lg font-semibold text-text mb-4">{title}</h2>
      {result.status === "insufficient_data" ? (
        <InsufficientNotice n={result.n} kMin={result.k_min!} />
      ) : children}
    </section>
  );
}

function Cell({ label, value, tone }: { label: string; value: string | number; tone: "ok" | "warn" | "bad" | "neutral" }) {
  const cls = tone === "ok" ? "text-ok border-ok/30 bg-ok/5"
    : tone === "warn" ? "text-warn border-warn/30 bg-warn/5"
    : tone === "bad" ? "text-bad border-bad/30 bg-bad/5"
    : "text-text border-line bg-bg/40";
  return (
    <div className={`rounded-lg border p-3 ${cls}`}>
      <div className="text-[11px] uppercase text-muted">{label}</div>
      <div className="text-xl mt-1 tabular-nums font-semibold">{value}</div>
    </div>
  );
}

function SleepBlock({ m }: { m: SleepMetrics & { status: "ok"; n: number } }) {
  const { t } = useTranslation();
  return (
    <div className="space-y-3 text-sm">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Cell label={t("reports.sleep.avgSE")} value={m.avg_se_pct != null ? `${m.avg_se_pct}%` : "—"} tone={m.avg_se_pct != null && m.avg_se_pct >= 80 ? "ok" : "warn"} />
        <Cell label={t("reports.sleep.avgTST")} value={m.avg_tst_hours != null ? `${m.avg_tst_hours}h` : "—"} tone={m.avg_tst_hours != null && m.avg_tst_hours >= 7 ? "ok" : "warn"} />
        <Cell label={t("reports.sleep.lowSeRatio")} value={m.low_se_ratio != null ? `${m.low_se_ratio}%` : "—"} tone={m.low_se_ratio != null && m.low_se_ratio < 20 ? "ok" : "warn"} />
        <Cell label={t("reports.sleep.shortTstRatio")} value={m.short_tst_ratio != null ? `${m.short_tst_ratio}%` : "—"} tone={m.short_tst_ratio != null && m.short_tst_ratio < 20 ? "ok" : "warn"} />
      </div>
      <div className="pt-2">
        <div className="text-xs uppercase text-muted mb-2">{t("reports.sleep.distribution")}</div>
        <DistroBar dist={m.se_distribution} />
      </div>
    </div>
  );
}

function DistroBar({ dist, pct = false }: { dist: Record<string, number>; pct?: boolean }) {
  const total = Object.values(dist).reduce((a, b) => a + b, 0) || 1;
  return (
    <div className="space-y-1.5">
      {Object.entries(dist).map(([k, v]) => (
        <div key={k} className="flex items-center gap-2">
          <span className="text-xs text-muted w-24 truncate">{k}</span>
          <div className="flex-1 h-2 rounded bg-bg/60 overflow-hidden">
            <div className="h-full bg-accent" style={{ width: `${(pct ? v : (v / total) * 100).toFixed(1)}%` }} />
          </div>
          <span className="text-xs text-text tabular-nums w-12 text-right">{pct ? `${v.toFixed(1)}%` : v}</span>
        </div>
      ))}
    </div>
  );
}
