import { useTranslation } from "react-i18next";

export default function InsufficientNotice({ n, kMin }: { n: number; kMin: number }) {
  const { t } = useTranslation();
  return (
    <div className="rounded-xl bg-warn/5 border border-warn/30 p-5 text-warn">
      <div className="font-medium">{t("common.insufficient.title")}</div>
      <p className="text-sm mt-1 text-text/80 leading-relaxed">
        {t("common.insufficient.body", { n, kMin })}
      </p>
    </div>
  );
}
