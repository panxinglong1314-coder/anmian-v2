import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";
import LanguageToggle from "../components/LanguageToggle";

interface Card {
  icon: string;
  title: string;
  body: string;
}
interface Stat {
  k: string;
  v: string;
}
interface Testimonial {
  quote: string;
  name: string;
  role: string;
  avatar: string;
}
interface WhyRow {
  f: string;
  a: string;
  b: string;
  c: string;
}

function lines(s: string) {
  return s.split("\n").map((l, i) => (
    <span key={i}>
      {i > 0 && <br />}
      {l}
    </span>
  ));
}

export default function Landing() {
  const { t } = useTranslation();
  const locale = currentLocale();

  const scenes = t("landing.scene.cards", { returnObjects: true }) as Card[];
  const features = t("landing.features.cards", { returnObjects: true }) as Card[];
  const stats = t("landing.science.stats", { returnObjects: true }) as Stat[];
  const testimonials = t("landing.testimonials.cards", { returnObjects: true }) as Testimonial[];
  const whyCols = t("landing.why.cols", { returnObjects: true }) as string[];
  const whyRows = t("landing.why.rows", { returnObjects: true }) as WhyRow[];
  const ctaSteps = t("landing.cta.steps", { returnObjects: true }) as string[];

  const Cross = () => <span className="text-txt3">✗</span>;
  const cell = (v: string) =>
    v.startsWith("✓") ? <span className="text-gold">{v}</span> : v === "✗" ? <Cross /> : v;

  return (
    <div className="landing-stars min-h-full overflow-y-auto bg-deep text-text">
      {/* NAV */}
      <nav className="fixed top-0 inset-x-0 h-16 z-50 flex items-center justify-between px-5 sm:px-8 bg-deep/80 backdrop-blur border-b border-white/5">
        <a href="#top" className="font-bold tracking-wide text-text">
          {t("app.name")}<span className="text-gold">.</span>
        </a>
        <div className="hidden sm:flex items-center gap-1 text-sm">
          <a href="#scene" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("landing.nav.scene")}</a>
          <a href="#product" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("landing.nav.product")}</a>
          <a href="#features" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("landing.nav.features")}</a>
          <a href="#science" className="px-3 py-1.5 rounded-full text-text/75 hover:text-text hover:bg-white/5 transition">{t("landing.nav.science")}</a>
        </div>
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <Link to="/app" className="rounded-full bg-gold text-deep text-sm font-medium px-4 py-1.5 hover:bg-goldlight transition">
            {t("landing.nav.cta")}
          </Link>
        </div>
      </nav>

      {/* HERO */}
      <section
        id="top"
        className="min-h-screen flex flex-col items-center justify-center text-center px-6 pt-24 pb-16 bg-cover bg-center bg-fixed relative"
        style={{
          backgroundImage:
            "linear-gradient(180deg, rgba(6,6,15,0.78), rgba(6,6,15,0.9)), url('/hero.jpg')"
        }}
      >
        <div className="text-[5rem] mb-6 drop-shadow-[0_0_60px_rgba(201,149,106,0.45)] animate-pulse">🌙</div>
        <h1 className="text-3xl sm:text-5xl font-bold leading-tight max-w-3xl bg-gradient-to-br from-text to-goldlight bg-clip-text text-transparent">
          {lines(t("landing.hero.title"))}
        </h1>
        <p className="text-gold/90 mt-5 tracking-wide">{t("landing.hero.brand")}</p>
        <p className="text-txt2 mt-2 text-sm sm:text-base">{t("landing.hero.tagline")}</p>
        <div className="flex flex-wrap gap-3 justify-center mt-8">
          <Link to="/app" className="rounded-full bg-gold text-deep font-medium px-6 py-3 hover:bg-goldlight transition">
            {t("landing.hero.ctaPrimary")}
          </Link>
          <a href="#product" className="rounded-full border border-white/15 text-text px-6 py-3 hover:bg-white/5 transition">
            {t("landing.hero.ctaSecondary")}
          </a>
        </div>
        <div className="absolute bottom-8 text-txt3 text-xs animate-bounce">{t("landing.hero.scroll")}</div>
      </section>

      {/* SCENE */}
      <section id="scene" className="px-6 py-20 max-w-5xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("landing.scene.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("landing.scene.title")}</h2>
        <p className="text-center text-txt2 mt-3 max-w-xl mx-auto">{t("landing.scene.desc")}</p>
        <div className="grid sm:grid-cols-3 gap-4 mt-10">
          {scenes.map((c, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-white/5 p-6">
              <div className="text-3xl mb-3">{c.icon}</div>
              <h3 className="font-semibold text-text">{c.title}</h3>
              <p className="text-txt2 text-sm mt-2 leading-relaxed">{c.body}</p>
            </div>
          ))}
        </div>
        <p className="text-center text-gold mt-10">{t("landing.scene.note")}</p>
      </section>

      {/* PRODUCT */}
      <section id="product" className="px-6 py-20 bg-navyx/50">
        <div className="max-w-5xl mx-auto grid md:grid-cols-2 gap-10 items-center">
          <div className="rounded-2xl overflow-hidden border border-white/5 aspect-[4/3] bg-cover bg-center" style={{ backgroundImage: "url('/product.jpg')" }} />
          <div>
            <p className="text-gold text-sm tracking-widest uppercase">{t("landing.product.label")}</p>
            <h2 className="text-2xl sm:text-3xl font-bold mt-2">{t("landing.product.title")}</h2>
            <p className="text-txt2 mt-4">{t("landing.product.lead")}</p>
            <p className="text-gold text-lg font-medium mt-1">{t("landing.product.highlight")}</p>
            <p className="text-txt2 mt-4 leading-relaxed">{t("landing.product.body")}</p>
          </div>
        </div>
      </section>

      {/* FEATURES */}
      <section id="features" className="px-6 py-20 max-w-5xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("landing.features.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("landing.features.title")}</h2>
        <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-4 mt-10">
          {features.map((c, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-white/5 p-6">
              <div className="text-3xl mb-3">{c.icon}</div>
              <h3 className="font-semibold text-text">{c.title}</h3>
              <p className="text-txt2 text-sm mt-2 leading-relaxed">{c.body}</p>
            </div>
          ))}
        </div>
      </section>

      {/* SCIENCE */}
      <section id="science" className="px-6 py-20 bg-navyx/50 text-center">
        <span className="inline-block rounded-full border border-gold/30 text-gold text-xs px-3 py-1">CBT-I</span>
        <h2 className="text-2xl sm:text-3xl font-bold mt-4">{t("landing.science.title")}</h2>
        <p className="text-txt2 mt-4 max-w-xl mx-auto leading-relaxed">{t("landing.science.body")}</p>
        <div className="grid grid-cols-3 gap-4 mt-10 max-w-2xl mx-auto">
          {stats.map((s, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-white/5 p-5">
              <div className="text-gold text-xl font-bold">{s.k}</div>
              <p className="text-txt2 text-xs mt-2">{lines(s.v)}</p>
            </div>
          ))}
        </div>
      </section>

      {/* TESTIMONIALS */}
      <section className="px-6 py-20 max-w-5xl mx-auto">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("landing.testimonials.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("landing.testimonials.title")}</h2>
        <div className="grid sm:grid-cols-3 gap-4 mt-10">
          {testimonials.map((tm, i) => (
            <div key={i} className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-white/5 p-6 flex flex-col">
              <p className="text-text/90 text-sm leading-relaxed flex-1">"{tm.quote}"</p>
              <div className="flex items-center gap-3 mt-4">
                <div className="w-9 h-9 rounded-full bg-gold/20 text-gold flex items-center justify-center font-semibold">{tm.avatar}</div>
                <div>
                  <div className="text-text text-sm font-medium">{tm.name}</div>
                  <div className="text-txt3 text-xs">{tm.role}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* WHY */}
      <section className="px-6 py-20 bg-navyx/50">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("landing.why.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("landing.why.title")}</h2>
        <div className="max-w-3xl mx-auto mt-10 overflow-x-auto">
          <table className="w-full text-sm border-collapse">
            <thead>
              <tr className="text-txt2">
                <th className="text-left p-3"></th>
                {whyCols.map((c, i) => (
                  <th key={i} className="p-3 font-medium whitespace-nowrap">{c}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {whyRows.map((r, i) => (
                <tr key={i} className="border-t border-white/5">
                  <td className="p-3 text-txt2">{r.f}</td>
                  <td className="p-3 text-center">{cell(r.a)}</td>
                  <td className="p-3 text-center">{cell(r.b)}</td>
                  <td className="p-3 text-center">{cell(r.c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* STORY */}
      <section className="px-6 py-20 max-w-2xl mx-auto text-center">
        <p className="text-gold text-sm tracking-widest uppercase">{t("landing.story.label")}</p>
        <h2 className="text-2xl sm:text-3xl font-bold mt-2">{t("landing.story.title")}</h2>
        <p className="text-xl text-goldlight font-light mt-6 leading-relaxed">"{t("landing.story.quote")}"</p>
        <p className="text-txt2 mt-6 leading-relaxed">{t("landing.story.body")}</p>
      </section>

      {/* CTA */}
      <section className="px-6 py-20 bg-navyx/50 text-center">
        <h2 className="text-2xl sm:text-3xl font-bold">{t("landing.cta.title")}</h2>
        <p className="text-txt2 mt-3">{t("landing.cta.sub")}</p>
        {locale === "en" ? (
          <Link to="/app" className="inline-block mt-8 rounded-full bg-gold text-deep font-medium px-8 py-3.5 hover:bg-goldlight transition">
            {t("landing.cta.button")}
          </Link>
        ) : (
          <div className="mt-8 max-w-md mx-auto">
            <div className="rounded-2xl bg-cardx/70 backdrop-blur-sm border border-gold/20 p-6">
              <p className="text-text font-medium">{t("landing.cta.wechatTitle")} 🌙</p>
              <ol className="text-left text-txt2 text-sm mt-4 space-y-2">
                {ctaSteps.map((s, i) => (
                  <li key={i} className="flex gap-2">
                    <span className="w-5 h-5 rounded-full bg-gold/20 text-gold text-xs flex items-center justify-center flex-shrink-0">{i + 1}</span>
                    {s}
                  </li>
                ))}
              </ol>
            </div>
            <Link to="/app" className="inline-block mt-4 text-gold text-sm hover:underline">
              {t("landing.cta.button")} →
            </Link>
          </div>
        )}
      </section>

      {/* FOOTER */}
      <footer className="px-6 py-10 text-center text-txt3 text-xs space-y-2 border-t border-white/5">
        <div className="flex gap-4 justify-center">
          <Link to="/privacy" className="hover:text-txt2">{t("landing.footer.privacy")}</Link>
          <Link to="/terms" className="hover:text-txt2">{t("landing.footer.terms")}</Link>
          <Link to="/contact" className="hover:text-txt2">{t("landing.footer.contact")}</Link>
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
