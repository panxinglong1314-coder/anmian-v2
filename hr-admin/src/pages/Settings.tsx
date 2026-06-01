import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getOrgInfo, type OrgInfo } from "../lib/api";

export default function Settings() {
  const { t } = useTranslation();
  const [org, setOrg] = useState<OrgInfo | null>(null);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getOrgInfo().then(setOrg).catch((e) => setErr((e as Error).message));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-text">{t("settings.title")}</h1>
        <p className="text-muted text-sm mt-1">{t("settings.subtitle")}</p>
      </header>

      {err && <div className="rounded-xl bg-bad/5 border border-bad/30 text-bad p-4 text-sm">{err}</div>}

      {org && (
        <div className="rounded-xl bg-card/60 border border-line p-5 space-y-4">
          <h2 className="text-lg font-semibold text-text">{t("settings.org.title")}</h2>
          <Row label={t("settings.org.name")} value={org.name} />
          <Row label={t("settings.org.industry")} value={org.industry || "—"} />
          <Row label={t("settings.org.orgId")} value={<span className="font-mono">{org.org_id}</span>} />
          <Row label={t("settings.org.hrContact")} value={org.contact_hr_email || "—"} />
          <Row label={t("settings.org.status")} value={
            <span className={org.status === "active" ? "text-ok" : "text-warn"}>{org.status}</span>
          } />
          <Row label={t("settings.org.periodEnd")} value={org.period_end || t("settings.org.noEnd")} />
          <Row label={t("settings.org.seats")} value={
            <span>
              <span className="text-text tabular-nums">{org.seats_used}</span>
              <span className="text-muted"> / {org.seat_quota}</span>
              <span className={`ml-2 text-xs ${org.seats_used >= org.seat_quota ? "text-bad" : "text-ok"}`}>
                {org.seat_quota > 0
                  ? `${Math.round(org.seats_used / org.seat_quota * 100)}%`
                  : ""}
              </span>
            </span>
          } />
        </div>
      )}

      <div className="rounded-xl bg-card/60 border border-line p-5 space-y-3">
        <h2 className="text-lg font-semibold text-text">{t("settings.privacy.title")}</h2>
        <p className="text-sm text-muted leading-relaxed">{t("settings.privacy.body")}</p>
        <div className="text-xs text-dim font-mono bg-bg/40 rounded p-3">
          admin:abconfig:k_anonymity_min → {t("settings.privacy.contactOps")}
        </div>
      </div>

      <div className="rounded-xl bg-card/30 border border-line p-4 text-xs text-muted leading-relaxed">
        💡 {t("settings.footer")}
      </div>
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between border-b border-line pb-3 last:border-0 last:pb-0">
      <span className="text-xs uppercase tracking-widest text-muted">{label}</span>
      <span className="text-sm text-text">{value}</span>
    </div>
  );
}
