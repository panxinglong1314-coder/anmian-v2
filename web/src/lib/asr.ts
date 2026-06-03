import { API_BASE } from "./config";
import { getToken } from "./auth";

// Backend ASR WebSocket expects 16 kHz mono 16-bit PCM binary frames,
// then a {"type":"end"} JSON message. Browsers' MediaRecorder produces
// webm/opus (not PCM), so we capture raw samples via Web Audio, downsample
// to 16 kHz, and convert to Int16 ourselves.
//
// 2026-06: Migrated from ScriptProcessor (deprecated 2014) to AudioWorklet
// — separate worker thread, no main-thread jank on low-end Android.
// Falls back to ScriptProcessor on browsers without worklet support.

export interface ASRCallbacks {
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (err: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
  /** RMS volume 0..1 sampled ~every 50ms; for waveform visualisation. */
  onVolume?: (rms: number) => void;
}

function wsBase(): string {
  const base = API_BASE || `${location.protocol}//${location.host}`;
  return base.replace(/^http/, "ws");
}

function floatTo16BitPCM(input: Float32Array): ArrayBuffer {
  const view = new DataView(new ArrayBuffer(input.length * 2));
  for (let i = 0; i < input.length; i++) {
    const s = Math.max(-1, Math.min(1, input[i]));
    view.setInt16(i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return view.buffer;
}

function downsample(buffer: Float32Array, inRate: number, outRate: number): Float32Array {
  if (outRate >= inRate) return buffer;
  const ratio = inRate / outRate;
  const newLen = Math.round(buffer.length / ratio);
  const result = new Float32Array(newLen);
  let offsetResult = 0;
  let offsetBuffer = 0;
  while (offsetResult < newLen) {
    const nextOffset = Math.round((offsetResult + 1) * ratio);
    let accum = 0;
    let count = 0;
    for (let i = offsetBuffer; i < nextOffset && i < buffer.length; i++) {
      accum += buffer[i];
      count++;
    }
    result[offsetResult] = count ? accum / count : 0;
    offsetResult++;
    offsetBuffer = nextOffset;
  }
  return result;
}

export class ASRClient {
  private ws: WebSocket | null = null;
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private processor: ScriptProcessorNode | null = null;  // fallback only
  private source: MediaStreamAudioSourceNode | null = null;
  private inRate = 16000;

  constructor(private locale: string, private cb: ASRCallbacks) {}

  async start(): Promise<void> {
    const token = getToken();
    const url = `${wsBase()}/api/v1/asr/ws?token=${encodeURIComponent(token || "")}&locale=${this.locale}`;
    this.ws = new WebSocket(url);
    this.ws.binaryType = "arraybuffer";

    this.ws.onopen = () => this.cb.onOpen?.();
    this.ws.onerror = () => this.cb.onError?.("ws_error");
    this.ws.onmessage = (e) => {
      try {
        const data = JSON.parse(typeof e.data === "string" ? e.data : "");
        if (data.error) {
          this.cb.onError?.(String(data.error));
          return;
        }
        if (data.done) {
          this.cb.onClose?.();
          return;
        }
        if (typeof data.text === "string") {
          if (data.is_final || data.slice_type === 2) this.cb.onFinal?.(data.text);
          else this.cb.onPartial?.(data.text);
        }
      } catch {
        /* ignore non-JSON */
      }
    };

    // mic capture — guard for browsers/contexts without mediaDevices (e.g. insecure context)
    if (!navigator.mediaDevices || typeof navigator.mediaDevices.getUserMedia !== "function") {
      const err = new Error("getUserMedia unavailable (insecure context or unsupported browser)");
      err.name = "SecurityError";
      throw err;
    }
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true }
    });
    const Ctx = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    this.ctx = new Ctx();
    if (this.ctx.state === "suspended") {
      try {
        await this.ctx.resume();
      } catch {
        /* noop */
      }
    }
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.inRate = this.ctx.sampleRate;

    // Prefer AudioWorklet (Chrome 66+, Firefox 76+, Safari 14.5+).
    // Fall back to ScriptProcessor on ancient browsers.
    const hasWorklet = !!(this.ctx.audioWorklet && typeof this.ctx.audioWorklet.addModule === "function");
    if (hasWorklet) {
      try {
        await this.ctx.audioWorklet.addModule("/asr-worklet.js");
        this.workletNode = new AudioWorkletNode(this.ctx, "asr-processor");
        this.workletNode.port.onmessage = (e) => {
          const msg = e.data as { type: string; pcm?: Float32Array; rms?: number };
          if (msg.type === "pcm" && msg.pcm) {
            if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
            const ds = downsample(msg.pcm, this.inRate, 16000);
            this.ws.send(floatTo16BitPCM(ds));
          } else if (msg.type === "vol" && typeof msg.rms === "number") {
            this.cb.onVolume?.(msg.rms);
          }
        };
        this.source.connect(this.workletNode);
        this.workletNode.connect(this.ctx.destination);
        return;
      } catch (err) {
        console.warn("[ASR] AudioWorklet failed, falling back to ScriptProcessor:", err);
      }
    }

    // Fallback: ScriptProcessor (deprecated but universal)
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    let volTick = 0;
    let volEma = 0;
    this.processor.onaudioprocess = (ev) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const input = ev.inputBuffer.getChannelData(0);
      const ds = downsample(input, this.inRate, 16000);
      this.ws.send(floatTo16BitPCM(ds));
      // RMS volume EMA, emit every ~50ms (every 3rd quantum @ 4096/44100)
      let sum = 0;
      for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
      const rms = Math.sqrt(sum / input.length);
      volEma = volEma * 0.6 + rms * 0.4;
      volTick++;
      if (volTick >= 3) {
        volTick = 0;
        this.cb.onVolume?.(volEma);
      }
    };
    this.source.connect(this.processor);
    this.processor.connect(this.ctx.destination);
  }

  async stop(): Promise<void> {
    try {
      this.workletNode?.port?.close?.();
      this.workletNode?.disconnect();
      this.processor?.disconnect();
      this.source?.disconnect();
    } catch {
      /* noop */
    }
    try {
      this.stream?.getTracks().forEach((t) => t.stop());
    } catch {
      /* noop */
    }
    try {
      await this.ctx?.close();
    } catch {
      /* noop */
    }
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ type: "end" }));
      // let the server flush the final transcript before closing
      setTimeout(() => {
        try {
          this.ws?.close();
        } catch {
          /* noop */
        }
      }, 1800);
    }
    this.workletNode = null;
    this.processor = null;
    this.source = null;
    this.ctx = null;
    this.stream = null;
  }
}
