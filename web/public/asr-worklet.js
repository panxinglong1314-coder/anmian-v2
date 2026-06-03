// AudioWorklet processor — runs on a separate thread for stable timing.
// Forwards raw Float32 PCM frames + computes RMS volume per chunk.
//
// IMPORTANT: AudioWorklet processors must live in a separate file served as
// a module; the main bundle can't include them. This file is served from
// /public/asr-worklet.js → https://sleepai.chat/asr-worklet.js.
//
// Posts to main thread:
//   { type: 'pcm', pcm: Float32Array }   ← raw samples (AudioContext rate)
//   { type: 'vol', rms: number }         ← 0..1 volume (smoothed)
class ASRProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this._volEma = 0; // exponential moving average for stable visualisation
    this._volTick = 0;
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch || ch.length === 0) return true;
    // Copy because the underlying buffer is reused next quantum.
    const pcm = new Float32Array(ch.length);
    pcm.set(ch);
    this.port.postMessage({ type: 'pcm', pcm }, [pcm.buffer]);

    // RMS volume — EMA, only emit every ~50ms to limit message rate.
    let sum = 0;
    for (let i = 0; i < ch.length; i++) sum += ch[i] * ch[i];
    const rms = Math.sqrt(sum / ch.length);
    this._volEma = this._volEma * 0.6 + rms * 0.4;
    this._volTick++;
    if (this._volTick >= 3) {
      this._volTick = 0;
      this.port.postMessage({ type: 'vol', rms: this._volEma });
    }
    return true;
  }
}

registerProcessor('asr-processor', ASRProcessor);
