import { useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { soundUrl } from "../lib/api";

const TRACKS = [
  { id: "rain", icon: "🌧️" },
  { id: "waves", icon: "🌊" },
  { id: "forest", icon: "🌲" },
  { id: "fireplace", icon: "🔥" },
  { id: "pinknoise", icon: "🎚️" }
];

/** White-noise / ambient sound player. Loops a single track; own audio element. */
export default function SoundPlayer() {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<string | null>(null);
  const [volume, setVolume] = useState(0.6);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    if (!audioRef.current) {
      const a = new Audio();
      a.loop = true;
      a.preload = "none";
      audioRef.current = a;
    }
    audioRef.current.volume = volume;
  }, [volume]);

  useEffect(() => {
    // stop sound when component unmounts
    return () => {
      audioRef.current?.pause();
    };
  }, []);

  const select = (id: string) => {
    const a = audioRef.current!;
    if (current === id) {
      a.pause();
      setCurrent(null);
      return;
    }
    a.src = soundUrl(id);
    a.volume = volume;
    a.play().catch(() => {});
    setCurrent(id);
  };

  const stop = () => {
    audioRef.current?.pause();
    setCurrent(null);
  };

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((v) => !v)}
        aria-label="Ambient sounds"
        className={`text-xs px-2 py-1 rounded border transition ${
          current ? "border-accent text-accent" : "border-night-line text-muted hover:text-text"
        }`}
      >
        🎵
      </button>

      {open && (
        <>
          {/* click-away */}
          <div className="fixed inset-0 z-40" onClick={() => setOpen(false)} />
          <div className="absolute right-0 mt-2 z-50 w-56 rounded-2xl bg-night-card border border-night-line p-3 shadow-xl">
            <p className="text-xs text-muted mb-2">{t("sounds.title")}</p>
            <div className="grid grid-cols-1 gap-1.5">
              {TRACKS.map((tr) => (
                <button
                  key={tr.id}
                  onClick={() => select(tr.id)}
                  className={`flex items-center gap-2 px-3 py-2 rounded-xl text-sm transition ${
                    current === tr.id
                      ? "bg-accent/15 text-accent"
                      : "text-text hover:bg-night-line/40"
                  }`}
                >
                  <span className="text-base">{tr.icon}</span>
                  <span className="flex-1 text-left">{t(`sounds.${tr.id}`)}</span>
                  {current === tr.id && <span className="text-xs">❚❚</span>}
                </button>
              ))}
            </div>
            <div className="mt-3 flex items-center gap-2">
              <span className="text-xs text-muted">🔉</span>
              <input
                type="range"
                min={0}
                max={1}
                step={0.05}
                value={volume}
                onChange={(e) => setVolume(Number(e.target.value))}
                className="flex-1 accent-accent"
              />
            </div>
            {current && (
              <button onClick={stop} className="mt-2 w-full text-xs text-muted hover:text-text py-1">
                {t("sounds.off")}
              </button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
