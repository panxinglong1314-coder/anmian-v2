import { useEffect } from "react";
import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";
import LanguageToggle from "./LanguageToggle";

export type Block = { type: "p"; text: string } | { type: "ul"; items: string[] };
export interface Section {
  heading?: string;
  blocks: Block[];
}
export interface LegalDoc {
  title: string;
  updated?: string;
  intro?: string;
  sections: Section[];
}

/** Shared shell for /privacy, /terms, /contact — bilingual, dark theme to match Landing. */
export default function LegalLayout({ doc }: { doc: Record<"en" | "zh", LegalDoc> }) {
  const { t } = useTranslation();
  const locale = currentLocale();
  const d = doc[locale];

  // Keep document title in sync for SEO / tab label.
  useEffect(() => {
    document.title = `${d.title} · ${t("app.name")}`;
  }, [d.title, t]);

  return (
    <div className="min-h-full overflow-y-auto bg-deep text-text">
      {/* NAV */}
      <nav className="sticky top-0 z-50 h-16 flex items-center justify-between px-5 sm:px-8 bg-deep/80 backdrop-blur border-b border-white/5">
        <Link to="/" className="font-bold tracking-wide text-text">
          {t("app.name")}<span className="text-gold">.</span>
        </Link>
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <Link to="/" className="text-txt2 text-sm px-3 py-1.5 rounded-full hover:text-text hover:bg-white/5 transition">
            {locale === "en" ? "← Home" : "← 返回首页"}
          </Link>
        </div>
      </nav>

      <article className="max-w-3xl mx-auto px-6 py-12 sm:py-16">
        <h1 className="text-3xl font-bold text-text">{d.title}</h1>
        {d.updated && <p className="text-txt3 text-sm mt-2">{d.updated}</p>}
        {d.intro && <p className="text-txt2 mt-6 leading-relaxed">{d.intro}</p>}

        {d.sections.map((s, i) => (
          <section key={i} className="mt-8">
            {s.heading && (
              <h2 className="text-lg font-semibold text-gold border-l-2 border-gold pl-3 mb-3">{s.heading}</h2>
            )}
            {s.blocks.map((b, j) =>
              b.type === "p" ? (
                <p key={j} className="text-txt2 leading-relaxed mb-3">{b.text}</p>
              ) : (
                <ul key={j} className="list-disc pl-6 text-txt2 leading-relaxed mb-3 space-y-1">
                  {b.items.map((it, k) => (
                    <li key={k}>{it}</li>
                  ))}
                </ul>
              )
            )}
          </section>
        ))}

        <footer className="mt-12 pt-6 border-t border-white/5 text-txt3 text-xs">
          © {new Date().getFullYear()} {t("app.name")} · sleepai.chat
        </footer>
      </article>
    </div>
  );
}
