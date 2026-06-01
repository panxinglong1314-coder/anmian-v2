import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";

export default function NotFound() {
  const { t } = useTranslation();
  return (
    <div className="h-full flex flex-col items-center justify-center text-center px-6">
      <div className="text-5xl mb-3">🤷</div>
      <h1 className="text-xl text-text">{t("notfound.title")}</h1>
      <p className="text-muted text-sm mt-2">{t("notfound.body")}</p>
      <Link to="/" className="mt-6 text-accent hover:underline">← {t("notfound.back")}</Link>
    </div>
  );
}
