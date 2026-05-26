import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { streamChat, AuthError, QuotaError, type ChatEvent } from "../lib/api";
import { clearToken } from "../lib/auth";
import { currentLocale } from "../i18n";
import { ASRClient } from "../lib/asr";
import { enqueueTts, unlockAudio, stopTts } from "../lib/audio";
import LanguageToggle from "../components/LanguageToggle";
import SoundPlayer from "../components/SoundPlayer";

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
  const [ttsOn, setTtsOn] = useState(false);
  const [crisis, setCrisis] = useState(false);
  const [quotaReached, setQuotaReached] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [listening, setListening] = useState(false);
  const sessionRef = useRef(loadSessionId());
  const scrollRef = useRef<HTMLDivElement>(null);
  const asrRef = useRef<ASRClient | null>(null);
  const finalTranscriptRef = useRef("");

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

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
    setMessages((m) => [...m, { role: "user", text }, { role: "assistant", text: "" }]);
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
    await client?.stop();
    // Final transcript arrives via onFinal/onClose; auto-send if we got one.
    const finalText = finalTranscriptRef.current.trim();
    finalTranscriptRef.current = "";
    if (finalText) {
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
    const client = new ASRClient(currentLocale(), {
      onPartial: (txt) => setInput(txt),
      onFinal: (txt) => {
        finalTranscriptRef.current = txt;
        setInput(txt);
      },
      onError: () => {
        setError(t("chat.micError"));
        setListening(false);
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
      {/* Header */}
      <header className="flex items-center justify-between px-4 py-3 border-b border-night-line">
        <div className="flex items-center gap-2">
          <span className="text-xl">🌙</span>
          <span className="font-semibold text-accent">{t("app.name")}</span>
        </div>
        <div className="flex items-center gap-2">
          <SoundPlayer />
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
          <div className="rounded-xl border border-coral/50 bg-coral/10 px-4 py-3 text-sm">
            <p className="text-coral font-medium">{t("chat.crisisTitle")}</p>
            <p className="text-text/90 mt-1">
              988 Suicide &amp; Crisis Lifeline — call or text <strong>988</strong>
              <br />Crisis Text Line — text <strong>HOME to 741741</strong>
            </p>
            <p className="text-muted text-xs mt-1">{t("chat.crisisCta")}</p>
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
        <div className="flex items-end gap-2">
          <button
            onClick={() => void toggleMic()}
            disabled={busy}
            aria-label="Voice input"
            className={`rounded-full px-3 py-2.5 border transition disabled:opacity-40 ${
              listening ? "border-coral text-coral animate-pulse" : "border-night-line text-muted hover:text-text"
            }`}
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
            placeholder={listening ? t("chat.listening") : t("chat.inputPlaceholder")}
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
          {listening ? t("chat.tapToStop") : t("chat.tapMic")}
        </p>
      </div>
    </div>
  );
}
