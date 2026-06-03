// Shared audio helpers for TTS playback + mobile autoplay unlock.
//
// iOS/Safari block HTMLAudioElement.play() unless it happens inside a user
// gesture OR the element has already played once within a gesture. TTS arrives
// over SSE (no gesture), so we reuse ONE audio element and "unlock" it on a
// real gesture (tapping Send / enabling TTS) by playing a short silent clip.
// After that, swapping its src and calling play() works without a gesture.
//
// 2026-06: Added playsinline + Media Session API so the audio survives going
// to background / lockscreen on iOS-PWA. Also publishes a playing-state
// observable so the UI can show a "🔊 playing" indicator.

let ttsEl: HTMLAudioElement | null = null;
let queue: string[] = [];
let playing = false;
const playingListeners = new Set<(p: boolean) => void>();

function setPlaying(next: boolean) {
  if (playing === next) return;
  playing = next;
  playingListeners.forEach((cb) => {
    try { cb(next); } catch { /* noop */ }
  });
}

function getEl(): HTMLAudioElement {
  if (!ttsEl) {
    ttsEl = new Audio();
    ttsEl.preload = "auto";
    // iOS:必须设 playsinline,否则进入"全屏播放器"模式,后台立刻 pause
    ttsEl.setAttribute("playsinline", "");
    ttsEl.setAttribute("webkit-playsinline", "");
    // Media Session API:让锁屏 / 控制中心显示标题 + 播放图标,
    // 切到后台也不会立刻 pause(浏览器视为"媒体应用")
    if ("mediaSession" in navigator) {
      try {
        navigator.mediaSession.metadata = new MediaMetadata({
          title: "ZhiMian · 知眠",
          artist: "AI Sleep Companion",
          artwork: [
            { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
            { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          ],
        });
        navigator.mediaSession.setActionHandler("pause", () => { stopTts(); });
        navigator.mediaSession.setActionHandler("stop", () => { stopTts(); });
      } catch {
        /* noop — old Safari */
      }
    }
  }
  return ttsEl;
}

/** Build a tiny valid silent WAV data URI at runtime (no hardcoded base64). */
function silentWav(): string {
  const sr = 8000;
  const n = 400; // ~0.05s
  const buf = new Uint8Array(44 + n);
  const dv = new DataView(buf.buffer);
  const w = (o: number, s: string) => {
    for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i));
  };
  w(0, "RIFF");
  dv.setUint32(4, 36 + n, true);
  w(8, "WAVE");
  w(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true);
  dv.setUint16(22, 1, true);
  dv.setUint32(24, sr, true);
  dv.setUint32(28, sr, true);
  dv.setUint16(32, 1, true);
  dv.setUint16(34, 8, true);
  w(36, "data");
  dv.setUint32(40, n, true);
  for (let i = 0; i < n; i++) buf[44 + i] = 128; // 8-bit silence
  let bin = "";
  buf.forEach((x) => (bin += String.fromCharCode(x)));
  return "data:audio/wav;base64," + btoa(bin);
}

/** Call from within a user gesture (tap) to unlock audio on mobile. */
export function unlockAudio(): void {
  const a = getEl();
  try {
    a.muted = true;
    a.src = silentWav();
    const p = a.play();
    if (p && typeof p.then === "function") {
      p.then(() => {
        a.pause();
        a.muted = false;
      }).catch(() => {
        a.muted = false;
      });
    } else {
      a.muted = false;
    }
  } catch {
    /* noop */
  }
}

/** Queue a base64 mp3 TTS chunk; plays sequentially on the shared element. */
export function enqueueTts(b64: string): void {
  if (!b64) return;
  queue.push(`data:audio/mpeg;base64,${b64}`);
  if (!playing) playNext();
}

function playNext(): void {
  const a = getEl();
  const src = queue.shift();
  if (!src) {
    setPlaying(false);
    return;
  }
  setPlaying(true);
  a.src = src;
  a.onended = () => playNext();
  a.onerror = () => playNext();
  const p = a.play();
  if (p && typeof p.catch === "function") p.catch(() => playNext());
  // 告诉 Media Session 正在播
  if ("mediaSession" in navigator) {
    try { navigator.mediaSession.playbackState = "playing"; } catch { /* noop */ }
  }
}

/** Stop all TTS playback and clear the queue. */
export function stopTts(): void {
  queue = [];
  setPlaying(false);
  if (ttsEl) {
    try {
      ttsEl.pause();
      ttsEl.onended = null;
    } catch {
      /* noop */
    }
  }
  if ("mediaSession" in navigator) {
    try { navigator.mediaSession.playbackState = "paused"; } catch { /* noop */ }
  }
}

/** Subscribe to playing state changes. Returns an unsubscribe function. */
export function onTtsPlayingChange(cb: (playing: boolean) => void): () => void {
  playingListeners.add(cb);
  // 同步发一次当前状态
  try { cb(playing); } catch { /* noop */ }
  return () => { playingListeners.delete(cb); };
}

/** Current TTS playing state (synchronous getter for one-off checks). */
export function isTtsPlaying(): boolean {
  return playing;
}
