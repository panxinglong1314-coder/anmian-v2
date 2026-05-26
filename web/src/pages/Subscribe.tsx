import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getUsage, AuthError, type Usage } from "../lib/api";
import { clearToken } from "../lib/auth";

type Cycle = "monthly" | "yearly";

// Prices match the WeChat mini-program (CNY): monthly base, yearly = monthly * 12 * 0.85.
const PRICE = { basic: 30, core: 45 };

function fmtPrice(plan: "basic" | "core", cycle: Cycle): string {
  const m = PRICE[plan];
  if (cycle === "monthly") return `¥${m}`;
  return `¥${Math.round(m * 12 * 0.85)}`;
}

export default function Subscribe() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [cycle, setCycle] = useState<Cycle>("monthly");
  const [usage, setUsage] = useState<Usage | null>(null);

  useEffect(() => {
    getUsage()
      .then((u) => setUsage(u))
      .catch((e) => {
        if (e instanceof AuthError) {
          clearToken();
          navigate("/login", { replace: true });
        }
      });
  }, [navigate]);

  const tier = usage?.tier ?? "free";
  const cycleLabel = (c: Cycle) => (c === "monthly" ? t("subscribe.monthly") : t("subscribe.yearly"));
  const periodLabel = usage?.period === "month" ? t("subscribe.perMonth") : t("subscribe.perDay");

  const plans: {
    id: "free" | "basic" | "core";
    price: string;
    recommended?: boolean;
  }[] = [
    { id: "free", price: "¥0" },
    { id: "basic", price: fmtPrice("basic", cycle), recommended: true },
    { id: "core", price: fmtPrice("core", cycle) }
  ];

  return (
    <div className="h-full overflow-y-auto no-scrollbar px-4 py-6 space-y-5 max-w-xl mx-auto">
      <div>
        <h1 className="text-xl font-semibold text-text">{t("subscribe.title")}</h1>
        <p className="text-sm text-muted mt-1">{t("subscribe.subtitle")}</p>
      </div>

      {/* Current usage */}
      {usage && (
        <div className="rounded-2xl bg-night-card border border-night-line p-4">
          <div className="flex items-center justify-between">
            <span className="text-sm text-text">{t("subscribe.current")}</span>
            <span className="text-sm text-accent font-medium">{t(`subscribe.tier.${tier}`)}</span>
          </div>
          <div className="mt-3 space-y-2 text-xs text-muted">
            <UsageRow
              label={`💬 ${t("subscribe.text")}`}
              remaining={usage.text.remaining_minutes ?? Math.floor(usage.text.remaining / 300)}
              limit={usage.text.limit_minutes ?? Math.floor(usage.text.limit / 300)}
              unit={t("subscribe.minutes")}
              period={periodLabel}
            />
            <UsageRow
              label={`🎙️ ${t("subscribe.voice")}`}
              remaining={usage.voice.remaining_minutes ?? Math.floor(usage.voice.remaining / 60)}
              limit={usage.voice.limit_minutes ?? Math.floor(usage.voice.limit / 60)}
              unit={t("subscribe.minutes")}
              period={periodLabel}
            />
          </div>
        </div>
      )}

      {/* Billing cycle toggle */}
      <div className="flex justify-center">
        <div className="inline-flex rounded-full border border-night-line p-1 bg-night-card">
          {(["monthly", "yearly"] as Cycle[]).map((c) => (
            <button
              key={c}
              onClick={() => setCycle(c)}
              className={`px-4 py-1.5 rounded-full text-sm transition ${
                cycle === c ? "bg-accent text-night font-medium" : "text-muted"
              }`}
            >
              {cycleLabel(c)}
              {c === "yearly" && <span className="ml-1 text-[10px]">{t("subscribe.save15")}</span>}
            </button>
          ))}
        </div>
      </div>

      {/* Plans */}
      <div className="space-y-3">
        {plans.map((p) => {
          const isCurrent = tier === p.id;
          return (
            <div
              key={p.id}
              className={`rounded-2xl border p-4 ${
                p.recommended ? "border-accent bg-accent/5" : "border-night-line bg-night-card"
              }`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-text">{t(`subscribe.tier.${p.id}`)}</span>
                  {p.recommended && (
                    <span className="text-[10px] px-2 py-0.5 rounded-full bg-accent/20 text-accent">
                      {t("subscribe.recommended")}
                    </span>
                  )}
                </div>
                <div className="text-right">
                  <span className="text-lg font-bold text-text">{p.price}</span>
                  {p.id !== "free" && (
                    <span className="text-xs text-muted">
                      {cycle === "monthly" ? t("subscribe.perMonthShort") : t("subscribe.perYearShort")}
                    </span>
                  )}
                </div>
              </div>
              <ul className="mt-3 space-y-1 text-sm text-muted">
                <li>💬 {t(`subscribe.feat.${p.id}.text`)}</li>
                <li>🎙️ {t(`subscribe.feat.${p.id}.voice`)}</li>
              </ul>
              <div className="mt-3">
                {isCurrent ? (
                  <div className="text-center text-xs text-muted py-2">{t("subscribe.currentPlan")}</div>
                ) : p.id === "free" ? null : (
                  <button
                    disabled
                    className="w-full rounded-full border border-night-line text-muted py-2.5 cursor-not-allowed"
                  >
                    {t("subscribe.comingSoon")}
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      <p className="text-center text-[11px] text-muted/60 leading-relaxed">{t("subscribe.note")}</p>
    </div>
  );
}

function UsageRow({
  label,
  remaining,
  limit,
  unit,
  period
}: {
  label: string;
  remaining: number;
  limit: number;
  unit: string;
  period: string;
}) {
  const pctLeft = limit > 0 ? Math.max(0, Math.min(100, (remaining / limit) * 100)) : 0;
  return (
    <div>
      <div className="flex justify-between">
        <span>{label}</span>
        <span>
          {remaining}/{limit} {unit} · {period}
        </span>
      </div>
      <div className="mt-1 h-1.5 rounded-full bg-night overflow-hidden">
        <div className="h-full bg-accent" style={{ width: `${pctLeft}%` }} />
      </div>
    </div>
  );
}
