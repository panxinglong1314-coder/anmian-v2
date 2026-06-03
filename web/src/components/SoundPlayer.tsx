import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { soundUrl } from "../lib/api";
import type { SoundId } from "../lib/voiceIntent";

const TRACKS: { id: SoundId; icon: string }[] = [
  { id: "rain", icon: "🌧️" },
  { id: "waves", icon: "🌊" },
  { id: "forest", icon: "🌲" },
  { id: "fireplace", icon: "🔥" },
  { id: "pinknoise", icon: "🎚️" }
];

export interface SoundPlayerHandle {
  /** 程序化播放某条音轨。返回 true=已开始, false=失败(如浏览器拒绝自动播)。 */
  play: (id: SoundId) => Promise<boolean>;
  /** 停止当前播放。 */
  stop: () => void;
  /** 当前正在播放的音轨 id, 没在播则 null。 */
  current: () => SoundId | null;
}

/** White-noise / ambient sound player. Loops a single track; own audio element. */
const SoundPlayer = forwardRef<SoundPlayerHandle>(function SoundPlayer(_props, ref) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [current, setCurrent] = useState<SoundId | null>(null);
  const [volume, setVolume] = useState(0.6);
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const currentRef = useRef<SoundId | null>(null);

  useEffect(() => {
    if (!audioRef.current) {
      const a = new Audio();
      a.loop = true;
      a.preload = "none";
      // iOS:必须 playsinline, 否则后台/锁屏立刻 pause
      a.setAttribute("playsinline", "");
      a.setAttribute("webkit-playsinline", "");
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

  // 程序化播放(给 ref 用)。同 id 再播会 toggle off, 不同 id 切换。
  const playProgrammatic = async (id: SoundId): Promise<boolean> => {
    const a = audioRef.current!;
    if (currentRef.current === id) {
      // 同条 — 不重启,保持播放
      return true;
    }
    try {
      a.src = soundUrl(id);
      a.volume = volume;
      await a.play();
      currentRef.current = id;
      setCurrent(id);
      return true;
    } catch (e) {
      console.warn("[SoundPlayer] play failed:", e);
      return false;
    }
  };

  const stopProgrammatic = () => {
    audioRef.current?.pause();
    currentRef.current = null;
    setCurrent(null);
  };

  useImperativeHandle(ref, () => ({
    play: playProgrammatic,
    stop: stopProgrammatic,
    current: () => currentRef.current,
  }), [volume]);

  // 用户从 UI 点击 (toggle 行为不变)
  const select = (id: SoundId) => {
    if (currentRef.current === id) {
      stopProgrammatic();
    } else {
      void playProgrammatic(id);
    }
  };

  const stop = () => stopProgrammatic();

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
});

export default SoundPlayer;
