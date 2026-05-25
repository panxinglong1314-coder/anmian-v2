import { useRef, useState } from "react";
import { useTranslation } from "react-i18next";

const SLIDES = ["/arch-1.png", "/arch-2.png", "/arch-3.png"];

/** 左右滚动的架构图轮播(scroll-snap + 箭头 + 圆点)。 */
export default function ArchCarousel() {
  const { t } = useTranslation();
  const captions = t("landing.arch.captions", { returnObjects: true }) as string[];
  const scroller = useRef<HTMLDivElement>(null);
  const [idx, setIdx] = useState(0);

  const go = (i: number) => {
    const el = scroller.current;
    if (!el) return;
    const n = Math.max(0, Math.min(SLIDES.length - 1, i));
    el.scrollTo({ left: n * el.clientWidth, behavior: "smooth" });
    setIdx(n);
  };

  const onScroll = () => {
    const el = scroller.current;
    if (!el) return;
    setIdx(Math.round(el.scrollLeft / el.clientWidth));
  };

  return (
    <div className="relative max-w-5xl mx-auto mt-10">
      <div
        ref={scroller}
        onScroll={onScroll}
        className="flex overflow-x-auto snap-x snap-mandatory no-scrollbar"
      >
        {SLIDES.map((src, i) => (
          <figure key={i} className="snap-center shrink-0 w-full px-1">
            <div className="rounded-2xl overflow-hidden border border-white/10 bg-cardx/60 backdrop-blur-sm">
              <img src={src} alt={captions[i] || `slide ${i + 1}`} className="w-full h-auto block" loading="lazy" />
            </div>
            {captions[i] && <figcaption className="text-center text-txt2 text-sm mt-3">{captions[i]}</figcaption>}
          </figure>
        ))}
      </div>

      {/* 左右箭头(桌面端) */}
      <button
        aria-label="Previous"
        onClick={() => go(idx - 1)}
        disabled={idx === 0}
        className="hidden sm:flex absolute left-2 top-[42%] -translate-y-1/2 w-10 h-10 items-center justify-center rounded-full bg-cardx/85 border border-white/10 text-text text-xl leading-none hover:bg-gold hover:text-deep transition disabled:opacity-25 disabled:pointer-events-none"
      >
        ‹
      </button>
      <button
        aria-label="Next"
        onClick={() => go(idx + 1)}
        disabled={idx === SLIDES.length - 1}
        className="hidden sm:flex absolute right-2 top-[42%] -translate-y-1/2 w-10 h-10 items-center justify-center rounded-full bg-cardx/85 border border-white/10 text-text text-xl leading-none hover:bg-gold hover:text-deep transition disabled:opacity-25 disabled:pointer-events-none"
      >
        ›
      </button>

      {/* 圆点指示 */}
      <div className="flex justify-center gap-2 mt-5">
        {SLIDES.map((_, i) => (
          <button
            key={i}
            aria-label={`Go to slide ${i + 1}`}
            onClick={() => go(i)}
            className={`h-2 rounded-full transition-all ${i === idx ? "w-6 bg-gold" : "w-2 bg-white/20 hover:bg-white/40"}`}
          />
        ))}
      </div>
    </div>
  );
}
