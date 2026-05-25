import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { getWorries, addWorry, AuthError, type WorryRecord } from "../lib/api";
import { currentLocale } from "../i18n";

export default function Worries() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [records, setRecords] = useState<WorryRecord[]>([]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [crisis, setCrisis] = useState<{ message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    try {
      const r = await getWorries();
      setRecords(r.records || []);
    } catch (e) {
      if (e instanceof AuthError) navigate("/login", { replace: true });
      else setError(t("worries.loadError"));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const add = async () => {
    const text = input.trim();
    if (!text || busy) return;
    setBusy(true);
    setError(null);
    setCrisis(null);
    try {
      const res = await addWorry(text, currentLocale());
      if (res.status === "crisis") {
        setCrisis({ message: res.message || "" });
      } else {
        setInput("");
        await load();
      }
    } catch (e) {
      if (e instanceof AuthError) navigate("/login", { replace: true });
      else setError(t("worries.addError"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <header className="px-4 py-3 border-b border-night-line">
        <h1 className="font-semibold text-accent">📥 {t("worries.title")}</h1>
        <p className="text-muted text-xs mt-0.5">{t("worries.subtitle")}</p>
      </header>

      <div className="flex-1 overflow-y-auto no-scrollbar px-4 py-4 space-y-3">
        {loading && <p className="text-muted text-center mt-8">…</p>}
        {!loading && records.length === 0 && !crisis && (
          <div className="text-center text-muted mt-16">
            <div className="text-3xl mb-2">📥</div>
            <p>{t("worries.empty")}</p>
          </div>
        )}
        {crisis && (
          <div className="rounded-xl border border-coral/50 bg-coral/10 px-4 py-3 text-sm">
            <p className="text-coral font-medium">{t("chat.crisisTitle")}</p>
            <p className="text-text/90 mt-1">{crisis.message}</p>
            <p className="text-text/90 mt-1">
              988 — call or text <strong>988</strong> · Crisis Text Line — text <strong>HOME to 741741</strong>
            </p>
          </div>
        )}
        {records.map((r, i) => (
          <div key={r.id || i} className="rounded-xl bg-night-card border border-night-line px-4 py-3">
            <p className="text-text text-[15px] whitespace-pre-wrap">{r.worry_text}</p>
            <div className="flex items-center gap-2 mt-2 text-[11px] text-muted">
              <span>{(r.recorded_at || "").slice(0, 16).replace("T", " ")}</span>
              {r.type && <span className="px-1.5 py-0.5 rounded bg-night-line/60">{r.type}</span>}
              {r.domain && r.domain !== "general" && (
                <span className="px-1.5 py-0.5 rounded bg-night-line/60">{r.domain}</span>
              )}
            </div>
          </div>
        ))}
        {error && <p className="text-coral text-sm text-center">{error}</p>}
      </div>

      <div className="px-4 py-3 border-t border-night-line">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void add();
              }
            }}
            rows={1}
            placeholder={t("worries.placeholder")}
            className="flex-1 resize-none rounded-2xl bg-night-card border border-night-line px-4 py-2.5 text-[15px] text-text placeholder:text-muted/60 focus:outline-none focus:border-accent max-h-32"
          />
          <button
            onClick={() => void add()}
            disabled={busy || !input.trim()}
            className="rounded-full bg-accent text-night font-medium px-4 py-2.5 disabled:opacity-40 transition"
          >
            {t("worries.add")}
          </button>
        </div>
      </div>
    </div>
  );
}
