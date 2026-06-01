import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { getTeams, type TeamSummary } from "../lib/api";

export default function Teams() {
  const { t } = useTranslation();
  const [teams, setTeams] = useState<TeamSummary[] | null>(null);
  const [total, setTotal] = useState<number>(0);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    getTeams()
      .then((r) => {
        setTeams(r.teams);
        setTotal(r.total_members);
      })
      .catch((e) => setErr((e as Error).message));
  }, []);

  return (
    <div className="space-y-6">
      <header>
        <h1 className="text-2xl font-bold text-text">{t("teams.title")}</h1>
        <p className="text-muted text-sm mt-1">
          {t("teams.subtitle", { n: total })}
        </p>
      </header>

      {err && <div className="rounded-xl bg-bad/5 border border-bad/30 text-bad p-4 text-sm">{err}</div>}

      <div className="rounded-xl border border-line overflow-hidden bg-card/40">
        <table className="w-full text-sm">
          <thead className="bg-bg/60">
            <tr className="text-left">
              <th className="px-4 py-3 text-xs uppercase tracking-widest text-muted">{t("teams.col.name")}</th>
              <th className="px-4 py-3 text-xs uppercase tracking-widest text-muted">{t("teams.col.manager")}</th>
              <th className="px-4 py-3 text-xs uppercase tracking-widest text-muted text-right">{t("teams.col.members")}</th>
              <th className="px-4 py-3 text-xs uppercase tracking-widest text-muted">{t("teams.col.created")}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {teams && teams.length === 0 && (
              <tr>
                <td colSpan={4} className="px-4 py-8 text-center text-muted">
                  {t("teams.empty")}
                </td>
              </tr>
            )}
            {teams?.map((t) => (
              <tr key={t.team_id} className="hover:bg-card/60 transition">
                <td className="px-4 py-3 text-text font-medium">{t.team_name}</td>
                <td className="px-4 py-3 text-muted text-xs">{t.manager_email || "—"}</td>
                <td className="px-4 py-3 text-right tabular-nums">{t.member_count}</td>
                <td className="px-4 py-3 text-muted text-xs">{t.created_at.slice(0, 10)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="rounded-xl bg-card/30 border border-line p-4 text-xs text-muted leading-relaxed">
        💡 {t("teams.footerHint")}
      </div>
    </div>
  );
}
