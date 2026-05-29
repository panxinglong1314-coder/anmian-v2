import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";

/**
 * 404 page rendered for unknown routes. We render content (not redirect) so
 * Google doesn't treat the URL as a soft redirect / duplicate of "/".
 */
export default function NotFound() {
  const { t } = useTranslation();
  const locale = currentLocale();

  useEffect(() => {
    // hint to crawlers that this is a not-found URL
    document.title = `404 · ${t("app.name")}`;
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => {
      try { document.head.removeChild(meta); } catch { /* noop */ }
    };
  }, [t]);

  return (
    <div className="starfield min-h-full flex flex-col items-center justify-center text-center px-6 py-20 bg-deep text-text">
      <div className="text-[5rem] mb-4">🌙</div>
      <h1 className="text-3xl sm:text-4xl font-bold">404</h1>
      <p className="text-txt2 mt-3 max-w-md">
        {locale === "en"
          ? "That page is somewhere else tonight. Let's get you home."
          : "这个页面今晚不在这里。带你回首页。"}
      </p>
      <Link
        to="/"
        className="mt-8 rounded-full bg-gold text-deep font-medium px-6 py-3 hover:bg-goldlight transition"
      >
        {locale === "en" ? "Back to home" : "回到首页"}
      </Link>
    </div>
  );
}
