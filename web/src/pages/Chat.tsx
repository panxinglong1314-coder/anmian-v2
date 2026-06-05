import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { streamChat, AuthError, QuotaError, getMe, type ChatEvent, type MeResponse } from "../lib/api";
import { clearToken } from "../lib/auth";
import { currentLocale } from "../i18n";
import { ASRClient } from "../lib/asr";
import { enqueueTts, unlockAudio, stopTts, onTtsPlayingChange } from "../lib/audio";
import { detectIntent, intentAck } from "../lib/voiceIntent";
import LanguageToggle from "../components/LanguageToggle";
import SoundPlayer, { type SoundPlayerHandle } from "../components/SoundPlayer";
import OnboardingModal, { shouldShowOnboarding } from "../components/OnboardingModal";

interface Msg {
  role: "user" | "assistant";
  text: string;
}

function newSessionId() {
  return `web_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
}

// Persist chat across tab switches, reloads, and browser restarts (localStorage).
const SS_MSGS = "zhimian_chat_msgs";
const SS_SID = "zhimian_chat_sid";
const MAX_PERSIST = 100; // cap stored history to avoid unbounded growth

function loadMessages(): Msg[] {
  try {
    const raw = localStorage.getItem(SS_MSGS);
    const arr = raw ? JSON.parse(raw) : [];
    return Array.isArray(arr) ? arr : [];
  } catch {
    return [];
  }
}

function loadSessionId(): string {
  try {
    let sid = localStorage.getItem(SS_SID);
    if (!sid) {
      sid = newSessionId();
      localStorage.setItem(SS_SID, sid);
    }
    return sid;
  } catch {
    return newSessionId();
  }
}

export default function Chat() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [messages, setMessages] = useState<Msg[]>(loadMessages);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  // v2026-06: TTS 默认开 — 让"语音陪伴"是默认体验,
  // 用户嫌吵再关。iOS unlock 在第一次 send/mic gesture 时触发。
  const [ttsOn, setTtsOn] = useState(true);
  const [ttsPlaying, setTtsPlaying] = useState(false);
  const [crisis, setCrisis] = useState(false);
  // P0-2a: 危机援助资源 (后端 SSE crisis_alert 事件填充)
  type Hotline = { name: string; contact: string; hours?: string };
  type OnlinePlatform = { name: string; contact: string; type?: string };
  const [crisisResources, setCrisisResources] = useState<{
    level: string;
    message: string;
    hotlines: Hotline[];
    online_platforms: OnlinePlatform[];
  } | null>(null);
  const [quotaReached, setQuotaReached] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  // 0..1 RMS volume during recording — 用于麦克风按钮的"呼吸 + 波形条"
  const [micVolume, setMicVolume] = useState(0);
  const [me, setMe] = useState<MeResponse | null>(null);
  const sessionRef = useRef(loadSessionId());
  const scrollRef = useRef<HTMLDivElement>(null);
  const asrRef = useRef<ASRClient | null>(null);
  const finalTranscriptRef = useRef("");
  // 白噪音播放器的 imperative handle, 给语音意图用
  const soundPlayerRef = useRef<SoundPlayerHandle | null>(null);
  // VAD 自动停发 — 防止 onFinal 多次触发 race
  const autoSentRef = useRef(false);

  // 订阅 TTS 播放状态,用于顶部三态条
  useEffect(() => {
    return onTtsPlayingChange((p) => setTtsPlaying(p));
  }, []);

  // 首次访问的 60 秒 onboarding 引导(localStorage 记一次性)
  const [showOnboarding, setShowOnboarding] = useState(() => shouldShowOnboarding());
  // 兼容老版本"voiceHint"清理(已被 onboarding 替代)
  try { localStorage.removeItem("zhimian_voice_hint_seen"); } catch { /* noop */ }

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  // v2.5: 加载身份 + 企业归属(用于头部 badge)。失败/无 org 静默不渲染 badge。
  useEffect(() => {
    let mounted = true;
    getMe()
      .then((d) => {
        if (mounted) setMe(d);
      })
      .catch(() => { /* ignore — 显示纯个人版即可 */ });
    return () => { mounted = false; };
  }, []);

  // persist messages so they survive tab switches, reloads, and browser restarts
  useEffect(() => {
    try {
      localStorage.setItem(SS_MSGS, JSON.stringify(messages.slice(-MAX_PERSIST)));
    } catch {
      /* noop */
    }
  }, [messages]);

  const send = async (override?: string) => {
    const text = (override ?? input).trim();
    if (!text || busy) return;
    if (ttsOn) unlockAudio(); // this call is within a user gesture → unlock mobile audio
    setError(null);
    setCrisis(false);
    setQuotaReached(false);
    setInput("");

    // ───── 语音/文字意图:听音乐 / 停止 ─────
    // 命中即同步执行播放/停止,UI 里加一条简短 assistant 确认气泡,
    // 同时仍把原文发给 LLM (让 AI 共情回应"为什么想听音乐") ——
    // 用户得到"音乐先响起 + AI 关心继续聊"的双重反馈。
    const intent = detectIntent(text);
    let ackBubble = "";
    if (intent.type === "play_sound") {
      const ok = await soundPlayerRef.current?.play(intent.track);
      if (ok) {
        const locale = (currentLocale() === "en" ? "en" : "zh") as "zh" | "en";
        ackBubble = intentAck(intent, locale);
      }
    } else if (intent.type === "stop_sound") {
      soundPlayerRef.current?.stop();
      const locale = (currentLocale() === "en" ? "en" : "zh") as "zh" | "en";
      ackBubble = intentAck(intent, locale);
    }

    // 先把 user 气泡 + (可选) 立即的 ack + 待填的 assistant placeholder 一次性塞入
    setMessages((m) => {
      const next = [...m, { role: "user" as const, text }];
      if (ackBubble) {
        next.push({ role: "assistant" as const, text: ackBubble });
      }
      // 永远再加一个 placeholder, 即使 ack 已经显示, LLM 仍会跟一段共情回应
      next.push({ role: "assistant" as const, text: "" });
      return next;
    });
    setBusy(true);

    const appendToLast = (chunk: string) =>
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", text: copy[copy.length - 1].text + chunk };
        return copy;
      });
    const setLast = (full: string) =>
      setMessages((m) => {
        const copy = [...m];
        copy[copy.length - 1] = { role: "assistant", text: full };
        return copy;
      });

    try {
      await streamChat(
        { message: text, sessionId: sessionRef.current, locale: currentLocale(), skipTts: !ttsOn },
        (evt: ChatEvent) => {
          if (evt.event === "cbt_state") {
            const data = (evt.data ?? {}) as Record<string, unknown>;
            if (data.safety_trigger === true || data.response_type === "safety") {
              setCrisis(true);
              if (typeof data.content === "string") setLast(data.content);
            }
          } else if (evt.event === "crisis_alert") {
            // P0-2a: 后端在 safety 响应时同步推这一条 — 铺前端援助资源面板
            const e = evt as Record<string, unknown>;
            setCrisis(true);
            setCrisisResources({
              level: typeof e.level === "string" ? e.level : "high",
              message: typeof e.message === "string" ? e.message : "",
              hotlines: Array.isArray(e.hotlines) ? (e.hotlines as Hotline[]).slice(0, 6) : [],
              online_platforms: Array.isArray(e.online_platforms)
                ? (e.online_platforms as OnlinePlatform[]).slice(0, 4) : [],
            });
          } else if (evt.event === "chunk") {
            if (typeof evt.data === "string") appendToLast(evt.data);
          } else if (evt.event === "tts_sentence" && ttsOn) {
            const audio = (evt as Record<string, unknown>).audio_base64;
            if (typeof audio === "string" && audio) enqueueTts(audio);
          } else if (evt.event === "error") {
            setError(typeof evt.message === "string" ? evt.message : t("chat.errorGeneric"));
          }
        }
      );
    } catch (e) {
      if (e instanceof AuthError) {
        setError(t("chat.sessionExpired"));
        setTimeout(() => navigate("/login", { replace: true }), 1200);
      } else if (e instanceof QuotaError) {
        // remove the empty assistant placeholder; show an upgrade banner instead
        setMessages((m) => (m.length && m[m.length - 1].role === "assistant" && !m[m.length - 1].text ? m.slice(0, -1) : m));
        setQuotaReached(true);
      } else {
        setError(t("chat.errorGeneric"));
      }
    } finally {
      setBusy(false);
    }
  };

  const signOut = () => {
    stopTts();
    try {
      localStorage.removeItem(SS_MSGS);
      localStorage.removeItem(SS_SID);
    } catch {
      /* noop */
    }
    clearToken();
    navigate("/login", { replace: true });
  };

  const startNew = () => {
    stopTts();
    sessionRef.current = newSessionId();
    try {
      localStorage.setItem(SS_SID, sessionRef.current);
      localStorage.removeItem(SS_MSGS);
    } catch {
      /* noop */
    }
    setMessages([]);
    setCrisis(false);
    setError(null);
  };

  const stopListening = async () => {
    const client = asrRef.current;
    asrRef.current = null;
    setListening(false);
    setMicVolume(0);
    await client?.stop();
    // Final transcript arrives via onFinal/onClose; auto-send if we got one.
    const finalText = finalTranscriptRef.current.trim();
    finalTranscriptRef.current = "";
    if (finalText && !autoSentRef.current) {
      autoSentRef.current = true;
      setInput("");
      void send(finalText);
    }
  };

  const toggleMic = async () => {
    if (listening) {
      await stopListening();
      return;
    }
    if (busy) return;
    setError(null);
    finalTranscriptRef.current = "";
    autoSentRef.current = false;
    // iOS Safari:第一次点 mic 也是用户 gesture,顺手 unlock TTS
    if (ttsOn) unlockAudio();
    const client = new ASRClient(currentLocale(), {
      onPartial: (txt) => setInput(txt),
      // 后端 needvad=1 → 静音 600ms 触发 is_final → 这里**自动停 + 自动发**,
      // 用户不用再点一次麦克风。autoSentRef 防止 onFinal + 手动 stop 双发。
      onFinal: async (txt) => {
        finalTranscriptRef.current = txt;
        setInput(txt);
        if (autoSentRef.current) return;
        autoSentRef.current = true;
        const inner = asrRef.current;
        asrRef.current = null;
        setListening(false);
        setMicVolume(0);
        try { await inner?.stop(); } catch { /* noop */ }
        const trimmed = txt.trim();
        if (trimmed) {
          setInput("");
          void send(trimmed);
        }
      },
      onVolume: (rms) => {
        // 用 sqrt 拉伸低音量段,让"小声说话"也能看到波动
        setMicVolume(Math.min(1, Math.sqrt(rms) * 2.4));
      },
      onError: () => {
        setError(t("chat.micError"));
        setListening(false);
        setMicVolume(0);
        asrRef.current = null;
      }
    });
    try {
      asrRef.current = client;
      await client.start();
      setListening(true);
    } catch (e) {
      const name = e instanceof Error ? e.name : "";
      const msg = e instanceof Error ? e.message : "";
      let key = "chat.micError";
      if (name === "NotAllowedError" || name === "SecurityError" || /denied|permission/i.test(msg)) {
        key = "chat.micDenied";
      } else if (name === "NotFoundError" || name === "OverconstrainedError" || /no microphone|not found/i.test(msg)) {
        key = "chat.micNotFound";
      } else if (name === "NotReadableError" || /in use|busy/i.test(msg)) {
        key = "chat.micInUse";
      } else if (/insecure|getusermedia|mediadevices/i.test(msg)) {
        key = "chat.micInsecure";
      }
      console.error("[mic] start failed:", name, msg);
      setError(t(key));
      asrRef.current = null;
    }
  };

  return (
    <div className="h-full flex flex-col">
      {showOnboarding && (
        <OnboardingModal onDone={() => setShowOnboarding(false)} />
      )}
      {/* v2.5 B2B: 企业 badge — 用户属于某企业时,顶部显示「XX 公司提供」+ 隐私链接 */}
      {me?.org && (
        <div className="bg-gold/10 border-b border-gold/20 px-4 py-1.5 text-[11px] text-gold/90 flex items-center justify-between gap-2">
          <span className="truncate">
            🏢 {t("chat.orgBadge.providedBy", { name: me.org.org_name })}
            {me.org.team_name ? ` · ${me.org.team_name}` : ""}
          </span>
          <Link to="/app/profile" className="underline whitespace-nowrap hover:text-gold">
            {t("chat.orgBadge.privacy")}
          </Link>
        </div>
      )}
      {/* v2026-06: 三态进行条 — 让用户随时知道系统在哪一步 */}
      {(listening || (busy && !listening) || ttsPlaying) && (
        <div className={`px-4 py-1 text-[11px] flex items-center justify-center gap-2 border-b ${
          listening ? "bg-coral/10 border-coral/20 text-coral"
          : ttsPlaying ? "bg-accent/10 border-accent/20 text-accent"
          : "bg-night-card border-night-line text-muted"
        }`}>
          {listening ? (
            <>
              <span className="inline-flex gap-0.5 items-end h-3">
                {[0, 1, 2, 3, 4].map((i) => {
                  // 用 volume 驱动 5 格波形条,每格根据 micVolume + i 的相位错峰
                  const h = Math.max(2, Math.min(12, micVolume * 12 * (1 + Math.sin(Date.now() / 100 + i)) / 1.5));
                  return (
                    <span key={i} className="w-0.5 bg-coral rounded-full"
                          style={{ height: `${h}px` }} />
                  );
                })}
              </span>
              <span>{t("chat.listening")}</span>
            </>
          ) : ttsPlaying ? (
            <>🔊 <span>{t("chat.statePlaying")}</span></>
          ) : (
            <>
              <span className="inline-flex gap-0.5">
                <span className="w-1 h-1 rounded-full bg-muted animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1 h-1 rounded-full bg-muted animate-bounce" style={{ animationDelay: "120ms" }} />
                <span className="w-1 h-1 rounded-full bg-muted animate-bounce" style={{ animationDelay: "240ms" }} />
              </span>
              <span>{t("chat.stateThinking")}</span>
            </>
          )}
        </div>
      )}
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-night-line">
        <div className="flex items-center gap-2">
          <span className="text-xl">🌙</span>
          <span className="font-semibold text-accent">{t("app.name")}</span>
        </div>
        <div className="flex items-center gap-2">
          <SoundPlayer ref={soundPlayerRef} />
          <button
            onClick={() => {
              setTtsOn((v) => {
                const next = !v;
                if (next) unlockAudio(); // gesture → unlock mobile audio
                else stopTts();
                return next;
              });
            }}
            aria-label="Toggle voice"
            className={`text-xs px-2 py-1 rounded border transition ${
              ttsOn ? "border-accent text-accent" : "border-night-line text-muted"
            }`}
          >
            {ttsOn ? "🔊" : "🔈"}
          </button>
          <button onClick={startNew} className="text-muted text-xs px-2 py-1 rounded border border-night-line hover:text-text transition">
            {t("chat.newSession")}
          </button>
          <LanguageToggle />
          <button onClick={signOut} className="text-muted text-xs px-2 py-1 hover:text-text transition">
            {t("common.signOut")}
          </button>
        </div>
      </header>

      {/* Messages */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto no-scrollbar px-4 py-6 space-y-4">
        {messages.length === 0 && (
          <div className="text-center text-muted mt-16">
            <div className="text-3xl mb-3">🌙</div>
            <p>{t("chat.greetingNew")}</p>
            <p className="text-xs text-muted/60 mt-2">{t("app.tagline")}</p>
          </div>
        )}
        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === "user" ? "justify-end" : "justify-start"}`}>
            <div
              className={`max-w-[80%] rounded-2xl px-4 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap ${
                m.role === "user"
                  ? "bg-accent text-night rounded-br-sm"
                  : "bg-night-card text-text rounded-bl-sm"
              }`}
            >
              {m.text || (busy && i === messages.length - 1 ? t("chat.thinking") : "")}
            </div>
          </div>
        ))}

        {crisis && (
          <div className="rounded-2xl border border-coral/40 bg-night-card/80 backdrop-blur px-4 py-4 text-sm space-y-3">
            <p className="text-coral font-semibold flex items-center gap-2">
              🤝 <span>{t("chat.crisisTitle")}</span>
            </p>
            {crisisResources?.message && (
              <p className="text-text/90 leading-relaxed text-[13.5px]">{crisisResources.message}</p>
            )}
            {crisisResources && crisisResources.hotlines.length > 0 ? (
              <>
                <p className="text-[11px] uppercase tracking-widest text-accent/70">24h 援助热线</p>
                <ul className="space-y-1.5">
                  {crisisResources.hotlines.slice(0, 6).map((h, i) => (
                    <li key={i} className="flex items-center justify-between gap-2 rounded-lg bg-accent/8 border border-accent/15 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="text-text text-[14px] truncate">{h.name}</div>
                        {h.hours && <div className="text-muted text-[11px]">{h.hours}</div>}
                      </div>
                      <a href={`tel:${(h.contact || "").replace(/[^0-9+]/g, "")}`} className="text-accent text-[13px] font-semibold whitespace-nowrap tabular-nums hover:underline">
                        {h.contact} ☎
                      </a>
                    </li>
                  ))}
                </ul>
                {crisisResources.online_platforms.length > 0 && (
                  <>
                    <p className="text-[11px] uppercase tracking-widest text-accent/70">在线咨询</p>
                    <ul className="space-y-1">
                      {crisisResources.online_platforms.map((p, i) => (
                        <li key={i} className="flex items-center justify-between gap-2 text-[13px]">
                          <a href={p.contact.startsWith("http") ? p.contact : `https://${p.contact}`} target="_blank" rel="noopener noreferrer" className="text-text/85 hover:text-accent">{p.name}</a>
                          {p.type && <span className="text-muted text-[11px]">{p.type}</span>}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </>
            ) : (
              // 后端没推 crisis_alert(或 SSE 丢)时的兜底:US 用户场景
              <p className="text-text/90 mt-1">
                988 Suicide &amp; Crisis Lifeline — call or text <strong>988</strong>
                <br />Crisis Text Line — text <strong>HOME to 741741</strong>
              </p>
            )}
            <p className="text-muted text-[11px] pt-1 border-t border-night-line/60">{t("chat.crisisCta")}</p>
            <button
              onClick={() => { setCrisis(false); }}
              className="w-full mt-1 rounded-full bg-accent/20 hover:bg-accent/30 text-accent text-[13px] font-medium py-2 transition"
            >
              我已了解,继续
            </button>
          </div>
        )}
        {quotaReached && (
          <div className="rounded-xl border border-accent/40 bg-accent/10 px-4 py-3 text-sm text-center">
            <p className="text-accent font-medium">{t("chat.quotaTitle")}</p>
            <p className="text-text/90 mt-1">{t("chat.quotaBody")}</p>
            <Link
              to="/app/subscribe"
              className="inline-block mt-3 rounded-full bg-accent text-night font-medium px-5 py-2 hover:opacity-90 transition"
            >
              {t("chat.quotaCta")}
            </Link>
          </div>
        )}
        {error && <p className="text-coral text-sm text-center">{error}</p>}
      </div>

      {/* Composer */}
      <div className="px-4 py-3 border-t border-night-line">
        {/* 首次访问引导:tell users they can talk */}
        {/* 旧的"试试说话"小条已被首次访问的 OnboardingModal 替代 (覆盖更全面) */}
        <div className="flex items-end gap-2">
          <button
            onClick={() => void toggleMic()}
            disabled={busy && !listening}
            aria-label="Voice input"
            className={`relative rounded-full px-3 py-2.5 border transition disabled:opacity-40 ${
              listening
                ? "border-coral text-coral"
                : "border-night-line text-muted hover:text-text hover:border-accent/40"
            }`}
            style={
              listening
                ? {
                    // 跟着音量"呼吸",最大缩到 1.18x
                    transform: `scale(${1 + micVolume * 0.18})`,
                    boxShadow: `0 0 ${8 + micVolume * 20}px rgba(255,127,127,${0.25 + micVolume * 0.45})`,
                    transition: "transform 60ms ease-out, box-shadow 60ms ease-out",
                  }
                : undefined
            }
          >
            🎙️
          </button>
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
            rows={1}
            placeholder={
              listening ? t("chat.listening")
              : messages.length === 0 ? t("chat.inputPlaceholderFirst")
              : t("chat.inputPlaceholder")
            }
            className="flex-1 resize-none rounded-2xl bg-night-card border border-night-line px-4 py-2.5 text-[15px] text-text placeholder:text-muted/60 focus:outline-none focus:border-accent max-h-32"
          />
          <button
            onClick={() => void send()}
            disabled={busy || !input.trim()}
            className="rounded-full bg-accent text-night font-medium px-4 py-2.5 disabled:opacity-40 transition"
          >
            {t("chat.send")}
          </button>
        </div>
        <p className="text-muted/50 text-[11px] mt-1.5 text-center">
          {listening
            ? t("chat.vadHint")     // "停下来 0.6 秒就自动发"
            : t("chat.tapMic")}
        </p>
      </div>
    </div>
  );
}
