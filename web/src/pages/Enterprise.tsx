import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";
import LanguageToggle from "../components/LanguageToggle";

interface Card {
  icon: string;
  title: string;
  body: string;
}
interface Step {
  num: string;
  title: string;
  body: string;
}
interface Metric {
  label: string;
  value: string;
  hint: string;
}

export default function Enterprise() {
  const { t } = useTranslation();
  const locale = currentLocale();

  const problems = t("enterprise.problem.cards", { returnObjects: true }) as Card[];
  const steps = t("enterprise.how.steps", { returnObjects: true }) as Step[];
  const privacyPoints = t("enterprise.privacy.points", { returnObjects: true }) as Card[];
  const sampleMetrics = t("enterprise.sample.metrics", { returnObjects: true }) as Metric[];
  const faqItems = t("enterprise.faq.items", { returnObjects: true }) as { q: string; a: string }[];
  const salesEmail = "panxinglong-1@126.com";

  return (
    <div className="starfield min-h-full overflow-y-auto bg-deep text-text">
      {/* NAV */}
      <nav className="fixed top-0 inset-x-0 h-16 z-50 flex items-center justify-between px-5 sm:px-8 bg-deep/80 backdrop-blur border-b border-white/5">
        <Link to="/" className="font-bold tracking-wide text-text">
          {t("app.name")}<span className="text-gold">.</span>
          <span className="ml-2 text-xs text-gold/70 font-normal">{t("enterprise.nav.badge")}</span>
        </Link>
        <div className="hidden sm:flex items-center gap-1 text-sm">
          <a href="#problem" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("enterprise.nav.problem")}</a>
          <a href="#how" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("enterprise.nav.how")}</a>
          <a href="#privacy" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("enterprise.nav.privacy")}</a>
          <a href="#sample" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("enterprise.nav.sample")}</a>
          <Link to="/" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("enterprise.nav.consumer")}</Link>
        </div>
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <a
            href={`mailto:${salesEmail}?subject=${encodeURIComponent(t("enterprise.cta.emailSubject"))}`}
            className="rounded-full bg-gold text-deep text-sm font-medium px-4 py-1.5 hover:bg-goldlight transition"
          >
            {t("enterprise.nav.cta")}
          </a>
        </div>
      </nav>

      <main>
      {/* HERO */}
      <section
        id="top"
        className="min-h-[85vh] flex flex-col items-center justify-center text-center px-6 pt-24 pb-16 bg-cover bg-center relative"
        style={{
          backgroundImage:
            "linear-gradient(180deg, rgba(6,6,15,0.82), rgba(6,6,15,0.92)), url('/hero.jpg')"
        }}
      >
        <div className="text-[4.5rem] mb-6 drop-shadow-[0_0_60px_rgba(201,149,106,0.45)]">🏢</div>
        <p className="text-gold text-sm tracking-widest uppercase mb-3">{t("enterprise.hero.label")}</p>
        <h1 className="text-3xl sm:text-5xl font-bold leading-tight max-w-3xl bg-gradient-to-br from-text to-goldlight bg-clip-text text-transparent">
          {t("enterprise.hero.title").split("\n").map((l, i) => (
            <span key={i}>{i > 0 && <br />}{l}</span>
          ))}
        </h1>
        <p className="text-txt2 mt-5 max-w-2xl text-sm sm:text-base leading-relaxed">
          {t("enterprise.hero.tagline")}
        </p>
        <div className="flex flex-wrap gap-3 justify-center mt-8">
          <a
            href={`mailto:${salesEmail}?subject=${encodeURIComponent(t("enterprise.cta.emailSubject"))}`}
            className="rounded-full bg-gold text-deep font-medium px-6 py-3 hover:bg-goldlight transition"
          >
            {t("enterprise.hero.ctaPrimary")}
          </a>
          <a href="#how" className="rounded-full border border-white/15 text-text px-6 py-3 hover:bg-white/5 transition">
            {t("enterprise.hero.ctaSecondary")}
          </a>
        </div>
      </section>

      {/* PROBLEM */}
      <section id="problem" className="px-6 py-20 max-w-5xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("enterprise.problem.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.problem.title")}</h2>
        <p className="text-center text-txt2 mt-3 max-w-2xl mx-auto">{t("enterprise.problem.desc")}</p>
        <div className="grid sm:grid-cols-3 gap-4 mt-10">
          {problems.map((c, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-white/5 p-6">
              <div className="text-3xl mb-3">{c.icon}</div>
              <h3 className="font-semibold text-text">{c.title}</h3>
              <p className="text-txt2 text-sm mt-2 leading-relaxed">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* HOW IT WORKS */}
      <section id="how" className="px-6 py-20 bg-navyx/50">
        <div className="max-w-5xl mx-auto">
          <p className="text-center text-gold text-sm tracking-widest uppercase">{t("enterprise.how.label")}</p>
          <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.how.title")}</h2>
          <p className="text-center text-txt2 mt-3 max-w-2xl mx-auto">{t("enterprise.how.desc")}</p>
          <div className="grid sm:grid-cols-3 gap-4 mt-12">
            {steps.map((s, i) => (
              <div key={i} className="relative rounded-2xl bg-cardx/70 backdrop-blur-sm border border-gold/10 p-6">
                <div className="absolute -top-4 -left-2 w-10 h-10 rounded-full bg-gold text-deep font-bold text-xl flex items-center justify-center shadow-lg">
                  {s.num}
                </div>
                <h3 className="font-semibold text-text mt-3">{s.title}</h3>
                <p className="text-txt2 text-sm mt-2 leading-relaxed">{s.body}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* PRIVACY — 关键差异化 */}
      <section id="privacy" className="px-6 py-20 max-w-5xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("enterprise.privacy.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.privacy.title")}</h2>
        <p className="text-center text-txt2 mt-3 max-w-2xl mx-auto">{t("enterprise.privacy.desc")}</p>
        <div className="grid sm:grid-cols-2 gap-4 mt-10">
          {privacyPoints.map((p, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-emerald-500/15 p-6">
              <div className="text-3xl mb-3">{p.icon}</div>
              <h3 className="font-semibold text-text">{p.title}</h3>
              <p className="text-txt2 text-sm mt-2 leading-relaxed">{p.body}</p>
            </div>
          ))}
        </div>
        <div className="mt-8 rounded-2xl bg-rose-500/5 border border-rose-500/20 p-5 text-center">
          <p className="text-rose-300 text-sm font-medium">{t("enterprise.privacy.crisisTitle")}</p>
          <p className="text-txt2 text-xs mt-2 max-w-2xl mx-auto leading-relaxed">{t("enterprise.privacy.crisisBody")}</p>
        </div>
      </section>

      {/* SAMPLE REPORT */}
      <section id="sample" className="px-6 py-20 bg-navyx/50">
        <div className="max-w-5xl mx-auto">
          <p className="text-center text-gold text-sm tracking-widest uppercase">{t("enterprise.sample.label")}</p>
          <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.sample.title")}</h2>
          <p className="text-center text-txt2 mt-3 max-w-2xl mx-auto">{t("enterprise.sample.desc")}</p>

          {/* mock 报告卡片 */}
          <div className="mt-10 rounded-3xl bg-cardx/80 backdrop-blur-sm border border-gold/20 p-6 sm:p-8 shadow-2xl">
            <div className="flex items-center justify-between border-b border-white/5 pb-4 mb-6">
              <div>
                <p className="text-xs text-txt3">{t("enterprise.sample.reportFor")}</p>
                <p className="font-semibold text-text">{t("enterprise.sample.reportOrg")}</p>
              </div>
              <div className="text-right">
                <p className="text-xs text-txt3">{t("enterprise.sample.reportPeriod")}</p>
                <p className="font-semibold text-gold">2026-05</p>
              </div>
            </div>

            <div className="grid sm:grid-cols-3 gap-4">
              {sampleMetrics.map((m, i) => (
                <div key={i} className="rounded-xl bg-deep/40 border border-white/5 p-4">
                  <p className="text-xs text-txt3 uppercase tracking-wider">{m.label}</p>
                  <p className="text-2xl font-bold text-text mt-1">{m.value}</p>
                  <p className="text-xs text-txt2 mt-1">{m.hint}</p>
                </div>
              ))}
            </div>

            <div className="mt-6 rounded-xl bg-emerald-500/5 border border-emerald-500/15 p-4">
              <p className="text-xs uppercase tracking-wider text-emerald-400 font-medium">{t("enterprise.sample.insightLabel")}</p>
              <p className="text-sm text-text mt-2 leading-relaxed">{t("enterprise.sample.insightBody")}</p>
            </div>

            <p className="text-xs text-txt3 text-center mt-6 italic">{t("enterprise.sample.disclaimer")}</p>
          </div>
        </div>
      </section>

      {/* PRICING / FAQ */}
      <section className="px-6 py-20 max-w-3xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("enterprise.faq.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.faq.title")}</h2>
        <div className="mt-10 space-y-4">
          {faqItems.map((it, i) => (
            <div key={i} className="rounded-2xl bg-cardx/60 border border-white/5 p-5">
              <p className="font-medium text-text">{it.q}</p>
              <p className="text-txt2 text-sm mt-2 leading-relaxed">{it.a}</p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA */}
      <section className="px-6 py-20 bg-navyx/50 text-center">
        <p className="text-gold text-sm tracking-widest uppercase">{t("enterprise.cta.label")}</p>
        <h2 className="text-2xl sm:text-3xl font-bold mt-2">{t("enterprise.cta.title")}</h2>
        <p className="text-txt2 mt-3 max-w-xl mx-auto">{t("enterprise.cta.sub")}</p>
        <a
          href={`mailto:${salesEmail}?subject=${encodeURIComponent(t("enterprise.cta.emailSubject"))}`}
          className="inline-block mt-8 rounded-full bg-gold text-deep font-medium px-8 py-3.5 hover:bg-goldlight transition"
        >
          {t("enterprise.cta.button")}
        </a>
        <p className="text-txt3 text-xs mt-4">{salesEmail}</p>
      </section>

      </main>

      {/* FOOTER */}
      <footer className="px-6 py-10 text-center text-txt2 text-xs space-y-2 border-t border-white/5">
        <div className="flex gap-2 justify-center">
          <Link to="/" className="px-3 py-2 inline-block hover:text-text">{t("enterprise.footer.consumer")}</Link>
          <Link to="/privacy" className="px-3 py-2 inline-block hover:text-text">{t("landing.footer.privacy")}</Link>
          <Link to="/terms" className="px-3 py-2 inline-block hover:text-text">{t("landing.footer.terms")}</Link>
          <Link to="/contact" className="px-3 py-2 inline-block hover:text-text">{t("landing.footer.contact")}</Link>
        </div>
        <div>© {new Date().getFullYear()} {t("app.name")} · sleepai.chat</div>
        {locale !== "en" && (
          <a href="https://beian.miit.gov.cn" target="_blank" rel="noreferrer" className="hover:text-txt2 block">
            闽ICP备2026012092号-2
          </a>
        )}
      </footer>
    </div>
  );
}
