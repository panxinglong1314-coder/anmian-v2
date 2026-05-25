import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
  getTodayDiary,
  getSleepDashboard,
  getDiaryHistory,
  submitSleepDiary,
  AuthError,
  type SleepDiary,
  type SleepDashboard
} from "../lib/api";
import { clearToken } from "../lib/auth";

function pct(se?: number): number {
  if (se == null) return 0;
  return se <= 1 ? Math.round(se * 100) : Math.round(se);
}

export default function Sleep() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [today, setToday] = useState<SleepDiary | null>(null);
  const [dash, setDash] = useState<SleepDashboard | null>(null);
  const [records, setRecords] = useState<SleepDiary[]>([]);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [bed, setBed] = useState("23:00");
  const [wake, setWake] = useState("07:00");
  const [latency, setLatency] = useState(15);
  const [wakeCount, setWakeCount] = useState(0);
  const [quality, setQuality] = useState(3);
  const [note, setNote] = useState("");

  const onAuthErr = (e: unknown) => {
    if (e instanceof AuthError) {
      clearToken();
      navigate("/login", { replace: true });
      return true;
    }
    return false;
  };

  const load = async () => {
    setLoading(true);
    try {
      const [td, db, hist] = await Promise.all([getTodayDiary(), getSleepDashboard(7), getDiaryHistory(7)]);
      setRecords(hist.records ?? []);
      if (td.exists && td.diary) {
        setToday(td.diary);
        if (td.diary.actual_bed_time) setBed(td.diary.actual_bed_time);
        if (td.diary.actual_wake_time) setWake(td.diary.actual_wake_time);
        if (td.diary.sleep_latency_minutes != null) setLatency(td.diary.sleep_latency_minutes);
        if (td.diary.wake_count != null) setWakeCount(td.diary.wake_count);
        if (td.diary.sleep_quality) setQuality(td.diary.sleep_quality);
        if (td.diary.note) setNote(td.diary.note);
      }
      setDash(db);
    } catch (e) {
      if (!onAuthErr(e)) setError(t("sleep.error"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const save = async () => {
    if (saving) return;
    setSaving(true);
    setMsg(null);
    setError(null);
    try {
      const r = await submitSleepDiary({
        bed_time: bed,
        wake_time: wake,
        sleep_latency_minutes: latency,
        wake_count: wakeCount,
        quality,
        note
      });
      setMsg(t("sleep.saved", { se: pct(r.se) }));
      await load();
    } catch (e) {
      if (!onAuthErr(e)) setError(t("sleep.error"));
    } finally {
      setSaving(false);
    }
  };

  const stats = dash?.stats ?? null;
  const hasData = !!dash?.has_data && !!stats;

  return (
    <div className="h-full overflow-y-auto no-scrollbar px-4 py-6 space-y-5 max-w-xl mx-auto">
      <div>
        <h1 className="text-xl font-semibold text-text">{t("sleep.title")}</h1>
        <p className="text-sm text-muted mt-1">{t("sleep.subtitle")}</p>
      </div>

      {/* Dashboard summary */}
      {hasData && (
        <div className="grid grid-cols-3 gap-3">
          <div className="rounded-2xl bg-night-card border border-night-line p-4 text-center">
            <div className="text-2xl font-bold text-accent">{Math.round(stats?.avg_se ?? 0)}%</div>
            <div className="text-[11px] text-muted mt-1">{t("sleep.avgSE")}</div>
          </div>
          <div className="rounded-2xl bg-night-card border border-night-line p-4 text-center">
            <div className="text-2xl font-bold text-text">{stats?.avg_tst_hours ?? 0}h</div>
            <div className="text-[11px] text-muted mt-1">{t("sleep.avgTST")}</div>
          </div>
          <div className="rounded-2xl bg-night-card border border-night-line p-4 text-center">
            <div className="text-2xl">{dash?.trend_emoji ?? "📝"}</div>
            <div className="text-[11px] text-muted mt-1">{t("sleep.trend")}</div>
          </div>
        </div>
      )}
      {hasData && (stats?.se_level || stats?.se_message) && (
        <p className="text-sm text-muted text-center">
          {stats?.se_level ? t(`sleep.level.${stats.se_level}`) : stats?.se_message}
        </p>
      )}

      {/* Log form */}
      <div className="rounded-2xl bg-night-card border border-night-line p-4 space-y-4">
        <p className="text-sm font-medium text-text">{today ? t("sleep.todayLogged") : t("sleep.log")}</p>
        <div className="grid grid-cols-2 gap-3">
          <label className="text-xs text-muted">
            {t("sleep.bedTime")}
            <input type="time" value={bed} onChange={(e) => setBed(e.target.value)}
              className="mt-1 w-full rounded-xl bg-night border border-night-line px-3 py-2 text-text text-sm focus:outline-none focus:border-accent" />
          </label>
          <label className="text-xs text-muted">
            {t("sleep.wakeTime")}
            <input type="time" value={wake} onChange={(e) => setWake(e.target.value)}
              className="mt-1 w-full rounded-xl bg-night border border-night-line px-3 py-2 text-text text-sm focus:outline-none focus:border-accent" />
          </label>
          <label className="text-xs text-muted">
            {t("sleep.latency")}
            <input type="number" min={0} value={latency} onChange={(e) => setLatency(Number(e.target.value))}
              className="mt-1 w-full rounded-xl bg-night border border-night-line px-3 py-2 text-text text-sm focus:outline-none focus:border-accent" />
          </label>
          <label className="text-xs text-muted">
            {t("sleep.wakeCount")}
            <input type="number" min={0} value={wakeCount} onChange={(e) => setWakeCount(Number(e.target.value))}
              className="mt-1 w-full rounded-xl bg-night border border-night-line px-3 py-2 text-text text-sm focus:outline-none focus:border-accent" />
          </label>
        </div>
        <div>
          <p className="text-xs text-muted mb-1.5">{t("sleep.quality")}</p>
          <div className="flex gap-2">
            {[1, 2, 3, 4, 5].map((q) => (
              <button key={q} onClick={() => setQuality(q)}
                className={`flex-1 py-2 rounded-xl text-sm border transition ${
                  quality === q ? "border-accent text-accent bg-accent/10" : "border-night-line text-muted hover:text-text"
                }`}>
                {q}
              </button>
            ))}
          </div>
        </div>
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder={t("sleep.note")}
          className="w-full rounded-xl bg-night border border-night-line px-3 py-2 text-text text-sm placeholder:text-muted/60 focus:outline-none focus:border-accent" />
        <button onClick={() => void save()} disabled={saving}
          className="w-full rounded-full bg-accent text-night font-medium py-2.5 disabled:opacity-50 transition">
          {saving ? t("sleep.saving") : t("sleep.save")}
        </button>
        {msg && <p className="text-accent text-sm text-center">{msg}</p>}
        {error && <p className="text-coral text-sm text-center">{error}</p>}
      </div>

      {/* History */}
      {records.length > 0 && (
        <div>
          <p className="text-sm font-medium text-text mb-2">{t("sleep.history")}</p>
          <div className="space-y-2">
            {records.map((r) => (
              <div key={r.date} className="flex items-center justify-between rounded-xl bg-night-card border border-night-line px-4 py-2.5">
                <span className="text-sm text-muted">{r.date}</span>
                <div className="flex items-center gap-3 text-sm">
                  <span className="text-text">{Math.round((r.tst_minutes ?? 0) / 6) / 10}h</span>
                  <span className="text-accent font-medium">{pct(r.se)}%</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {!loading && !hasData && !today && (
        <p className="text-center text-muted text-sm">{t("sleep.noData")}</p>
      )}
    </div>
  );
}
