import { Link } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { currentLocale } from "../i18n";
import LanguageToggle from "../components/LanguageToggle";
import ArchCarousel from "../components/ArchCarousel";

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
  const ctaSteps = t("landing.cta.steps", { returnObjects: true }) as string[];

  return (
    <div className="min-h-full overflow-y-auto text-text">
      {/* 视频背景由 MarketingShell 全局提供 — 不能在这里加 bg-deep / starfield,
          否则会盖住底层视频。各 section 内自己用 bg-navyx/50 半透明蒙层。 */}
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
          <Link to="/enterprise" className="px-3 py-1.5 rounded-full text-gold hover:text-goldlight hover:bg-gold/5 transition font-medium">{t("enterprise.nav.badge")}</Link>
        </div>
        <div className="flex items-center gap-2">
          <LanguageToggle />
          <Link to="/app" className="rounded-full bg-gold text-deep text-sm font-medium px-4 py-1.5 hover:bg-goldlight transition">
            {t("landing.nav.cta")}
          </Link>
        </div>
      </nav>

      <main>
      {/* HERO — 背景视频由 MarketingShell 全局提供,这里只放内容 */}
      <section
        id="top"
        className="min-h-screen flex flex-col items-center justify-center text-center px-6 pt-24 pb-16 relative"
      >
        <div className="flex flex-col items-center">
        <div className="text-[5rem] mb-6 drop-shadow-[0_0_60px_rgba(201,149,106,0.45)]">🌙</div>
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
        </div>{/* /content wrapper */}
        <div className="absolute bottom-8 left-0 right-0 text-txt3 text-xs animate-bounce">{t("landing.hero.scroll")}</div>
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

      {/* ARCHITECTURE — 左右滚动的架构图 */}
      <section id="architecture" className="px-6 py-20 bg-navyx/50">
        <p className="text-center text-gold text-sm tracking-widest uppercase">{t("landing.arch.label")}</p>
        <h2 className="text-center text-2xl sm:text-3xl font-bold mt-2">{t("landing.arch.title")}</h2>
        <ArchCarousel />
      </section>

      {/* ENTERPRISE callout — 链接到 /enterprise 全页 */}
      <section className="px-6 py-16 max-w-4xl mx-auto">
        <Link
          to="/enterprise"
          className="group block rounded-3xl bg-gradient-to-br from-gold/15 via-cardx/60 to-navyx/60 border border-gold/20 p-8 sm:p-10 hover:border-gold/40 transition"
        >
          <div className="flex flex-col sm:flex-row items-start sm:items-center gap-6">
            <div className="text-5xl flex-shrink-0">🏢</div>
            <div className="flex-1">
              <p className="text-gold text-xs tracking-widest uppercase mb-2">{t("enterprise.nav.badge")}</p>
              <h3 className="text-xl sm:text-2xl font-bold text-text">{t("enterprise.hero.title").split("\n").join(" ")}</h3>
              <p className="text-txt2 text-sm mt-3 leading-relaxed">{t("enterprise.hero.tagline")}</p>
            </div>
            <div className="flex-shrink-0 text-gold text-2xl group-hover:translate-x-1 transition">→</div>
          </div>
        </Link>
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

      </main>

      {/* FOOTER */}
      <footer className="px-6 py-10 text-center text-txt2 text-xs space-y-2 border-t border-white/5">
        <div className="flex gap-2 justify-center">
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
