import { useState } from "react";
import { useTranslation } from "react-i18next";
import { importEmployees, type ImportResult } from "../lib/api";

export default function Employees() {
  const { t } = useTranslation();
  const [csv, setCsv] = useState("");
  const [sendEmails, setSendEmails] = useState(true);
  const [expireDays, setExpireDays] = useState(14);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const onFile = (f: File | null) => {
    if (!f) return;
    const reader = new FileReader();
    reader.onload = () => setCsv(String(reader.result || ""));
    reader.readAsText(f, "utf-8");
  };

  const onSubmit = async () => {
    setErr(null);
    setBusy(true);
    setResult(null);
    try {
      const r = await importEmployees(csv, sendEmails, expireDays);
      setResult(r);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-text">{t("employees.title")}</h1>
        <p className="text-muted text-sm mt-1">{t("employees.subtitle")}</p>
      </header>

      {/* CSV 上传 / 粘贴 */}
      <div className="rounded-xl bg-card/60 border border-line p-5 space-y-4">
        <div>
          <label className="text-xs uppercase tracking-widest text-muted block mb-2">
            {t("employees.csv.label")}
          </label>
          <div className="flex gap-3 items-center">
            <input
              type="file"
              accept=".csv,text/csv"
              onChange={(e) => onFile(e.target.files?.[0] || null)}
              className="text-xs text-muted file:mr-3 file:py-1.5 file:px-3 file:rounded file:border-0 file:bg-accent/15 file:text-accent file:cursor-pointer"
            />
            <span className="text-xs text-dim">{t("employees.csv.or")}</span>
          </div>
          <textarea
            value={csv}
            onChange={(e) => setCsv(e.target.value)}
            rows={8}
            placeholder={t("employees.csv.placeholder")}
            className="w-full mt-3 px-3 py-2 rounded bg-bg border border-line text-text font-mono text-xs outline-none focus:border-accent transition"
          />
          <p className="text-[11px] text-dim mt-2">{t("employees.csv.format")}</p>
        </div>

        <div className="flex flex-wrap items-center gap-5 pt-3 border-t border-line">
          <label className="flex items-center gap-2 text-sm text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={sendEmails}
              onChange={(e) => setSendEmails(e.target.checked)}
              className="accent-accent"
            />
            {t("employees.opt.sendEmails")}
          </label>
          <label className="flex items-center gap-2 text-sm text-muted">
            {t("employees.opt.expireDays")}:
            <input
              type="number"
              min={1}
              max={90}
              value={expireDays}
              onChange={(e) => setExpireDays(Number(e.target.value) || 14)}
              className="w-16 px-2 py-1 rounded bg-bg border border-line text-text text-center"
            />
          </label>
        </div>

        <button
          onClick={() => void onSubmit()}
          disabled={busy || !csv.trim()}
          className="px-6 py-2.5 rounded bg-accent text-bg font-medium disabled:opacity-40 hover:bg-accent/90 transition"
        >
          {busy ? "…" : t("employees.submit")}
        </button>

        {err && <p className="text-bad text-sm">{err}</p>}
      </div>

      {/* 结果 */}
      {result && (
        <div className="rounded-xl bg-card/60 border border-line p-5 space-y-4">
          <h2 className="text-lg font-semibold text-text">{t("employees.result.title")}</h2>

          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-center">
            <div className="rounded-lg bg-bg/60 border border-line p-3">
              <div className="text-xs text-muted">{t("employees.result.total")}</div>
              <div className="text-2xl text-text tabular-nums mt-1">{result.total_rows}</div>
            </div>
            <div className="rounded-lg bg-ok/5 border border-ok/30 p-3">
              <div className="text-xs text-ok">{t("employees.result.invited")}</div>
              <div className="text-2xl text-ok tabular-nums mt-1">{result.succeeded}</div>
            </div>
            <div className="rounded-lg bg-card/40 border border-line p-3">
              <div className="text-xs text-muted">{t("employees.result.sent")}</div>
              <div className="text-2xl text-text tabular-nums mt-1">{result.emails_sent}</div>
            </div>
            <div className="rounded-lg bg-warn/5 border border-warn/30 p-3">
              <div className="text-xs text-warn">{t("employees.result.skipped")}</div>
              <div className="text-2xl text-warn tabular-nums mt-1">
                {result.skipped_already_in_org + result.skipped_in_other_org}
              </div>
            </div>
            <div className="rounded-lg bg-bad/5 border border-bad/30 p-3">
              <div className="text-xs text-bad">{t("employees.result.errors")}</div>
              <div className="text-2xl text-bad tabular-nums mt-1">{result.parse_errors.length}</div>
            </div>
          </div>

          {result.parse_errors.length > 0 && (
            <div className="rounded-lg bg-bad/5 border border-bad/30 p-3">
              <p className="text-xs uppercase text-bad mb-2">{t("employees.result.parseErrors")}</p>
              <ul className="text-xs text-text/80 space-y-1 list-disc list-inside">
                {result.parse_errors.map((e, i) => <li key={i}>{e}</li>)}
              </ul>
            </div>
          )}

          <div className="max-h-96 overflow-y-auto rounded border border-line">
            <table className="w-full text-xs">
              <thead className="bg-bg sticky top-0">
                <tr className="text-left">
                  <th className="px-3 py-2 text-muted">{t("employees.result.col.email")}</th>
                  <th className="px-3 py-2 text-muted">{t("employees.result.col.status")}</th>
                  <th className="px-3 py-2 text-muted font-mono">{t("employees.result.col.code")}</th>
                  <th className="px-3 py-2 text-muted">{t("employees.result.col.emailSent")}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-line">
                {result.items.map((it, i) => (
                  <tr key={i} className="hover:bg-card/40">
                    <td className="px-3 py-2 text-text">{it.email}</td>
                    <td className={`px-3 py-2 ${
                      it.status === "invited" ? "text-ok"
                      : it.status === "error" ? "text-bad"
                      : "text-warn"
                    }`}>{t(`employees.result.statusValue.${it.status}`)}</td>
                    <td className="px-3 py-2 font-mono text-muted">{it.code || "—"}</td>
                    <td className="px-3 py-2 text-muted">{it.email_sent === true ? "✓" : it.email_sent === false ? "—" : ""}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      <div className="rounded-xl bg-card/30 border border-line p-4 text-xs text-muted leading-relaxed">
        💡 {t("employees.footerHint")}
      </div>
    </div>
  );
}
