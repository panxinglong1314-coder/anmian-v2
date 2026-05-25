// Shared audio helpers for TTS playback + mobile autoplay unlock.
//
// iOS/Safari block HTMLAudioElement.play() unless it happens inside a user
// gesture OR the element has already played once within a gesture. TTS arrives
// over SSE (no gesture), so we reuse ONE audio element and "unlock" it on a
// real gesture (tapping Send / enabling TTS) by playing a short silent clip.
// After that, swapping its src and calling play() works without a gesture.

let ttsEl: HTMLAudioElement | null = null;
let queue: string[] = [];
let playing = false;

function getEl(): HTMLAudioElement {
  if (!ttsEl) {
    ttsEl = new Audio();
    ttsEl.preload = "auto";
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
    playing = false;
    return;
  }
  playing = true;
  a.src = src;
  a.onended = () => playNext();
  a.onerror = () => playNext();
  const p = a.play();
  if (p && typeof p.catch === "function") p.catch(() => playNext());
}

/** Stop all TTS playback and clear the queue. */
export function stopTts(): void {
  queue = [];
  playing = false;
  if (ttsEl) {
    try {
      ttsEl.pause();
      ttsEl.onended = null;
    } catch {
      /* noop */
    }
  }
}
