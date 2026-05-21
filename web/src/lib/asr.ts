import { API_BASE } from "./config";
import { getToken } from "./auth";

// Backend ASR WebSocket expects 16 kHz mono 16-bit PCM binary frames,
// then a {"type":"end"} JSON message. Browsers' MediaRecorder produces
// webm/opus (not PCM), so we capture raw samples via Web Audio, downsample
// to 16 kHz, and convert to Int16 ourselves.

export interface ASRCallbacks {
  onPartial?: (text: string) => void;
  onFinal?: (text: string) => void;
  onError?: (err: string) => void;
  onOpen?: () => void;
  onClose?: () => void;
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
  private processor: ScriptProcessorNode | null = null;
  private source: MediaStreamAudioSourceNode | null = null;

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

    // mic capture
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true }
    });
    this.ctx = new AudioContext();
    this.source = this.ctx.createMediaStreamSource(this.stream);
    this.processor = this.ctx.createScriptProcessor(4096, 1, 1);
    const inRate = this.ctx.sampleRate;

    this.processor.onaudioprocess = (ev) => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const input = ev.inputBuffer.getChannelData(0);
      const ds = downsample(input, inRate, 16000);
      this.ws.send(floatTo16BitPCM(ds));
    };

    this.source.connect(this.processor);
    // Connect to destination so onaudioprocess fires; output buffer is never
    // written, so nothing is actually played back (no echo).
    this.processor.connect(this.ctx.destination);
  }

  async stop(): Promise<void> {
    try {
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
    this.processor = null;
    this.source = null;
    this.ctx = null;
    this.stream = null;
  }
}
