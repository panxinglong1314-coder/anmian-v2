// 简单的客户端语音意图解析器 (front-end only, 不依赖后端)
//
// 设计:
// - 纯函数 + 正则,易测、可扩展、0 网络往返
// - 仅匹配高置信度模式,模糊不命中 → 走默认 LLM 路径
// - 中英双语;关键词带常见同义词
// - 命中后调用方仍可选择"同时发给 LLM 让 AI 共情" — 不互斥
//
// 已支持意图:
//   play_sound          → 播放白噪音 (含具体音轨识别)
//   stop_sound          → 停止当前播放
//
// 扩展指南:加新意图 = 加一个 detect 函数 + 在 detectIntent 里串。

export const SOUND_IDS = ["rain", "waves", "forest", "fireplace", "pinknoise"] as const;
export type SoundId = (typeof SOUND_IDS)[number];

export type VoiceIntent =
  | { type: "play_sound"; track: SoundId; raw: string }
  | { type: "stop_sound"; raw: string }
  | { type: "none" };

// ============== 关键词词典 ==============
// 命中规则: 任一关键词出现在 (经过 normalize 的) transcript 中
const PLAY_TRIGGERS = [
  // zh
  "想听", "想听音乐", "听点音乐", "听音乐", "来点音乐",
  "放点音乐", "放音乐", "放歌", "听首歌", "放点声音",
  "想听白噪音", "白噪音", "助眠音乐", "助眠声音", "助眠的声音",
  "放点歌", "听个歌", "来段音乐", "播放音乐", "播放白噪音",
  "想听雨声", "听点雨", "想听海", "想听森林",
  // en
  "play music", "put on music", "music please", "some music",
  "white noise", "ambient", "ambience", "play sound", "play sounds",
  "play rain", "play waves", "play ocean", "play forest", "play fireplace",
  "play some music", "i want music", "i'd like some music",
];

const STOP_TRIGGERS = [
  // zh
  "停", "停掉", "关掉", "关了", "别放了", "别放", "关音乐", "关掉音乐",
  "停音乐", "停止音乐", "停止播放", "静音", "安静",
  // en
  "stop", "stop music", "stop the music", "turn off", "turn it off",
  "quiet", "silence", "mute", "pause music",
];

// 具体音轨关键词
const TRACK_KEYWORDS: Record<SoundId, string[]> = {
  rain: [
    "雨", "雨声", "下雨", "雨水", "rain", "rainfall", "raining", "rainy",
  ],
  waves: [
    "海", "海浪", "浪", "海声", "水声", "ocean", "waves", "wave", "sea",
  ],
  forest: [
    "森林", "树林", "鸟叫", "鸟声", "鸟", "山林", "forest", "birds", "woods",
    "nature", "jungle",
  ],
  fireplace: [
    "壁炉", "火", "火堆", "篝火", "柴火", "炉火",
    "fireplace", "fire", "campfire", "crackle", "crackling",
  ],
  pinknoise: [
    "粉噪", "粉噪音", "粉色噪音", "pink noise", "pink",
  ],
};

// 经验:rain 是最经典的助眠白噪音,泛意"音乐/白噪音"默认用 rain
const DEFAULT_TRACK: SoundId = "rain";


// ============== 实用 ==============
function normalize(s: string): string {
  return (s || "").toLowerCase().trim().replace(/[.。!！?？,，;；:：]/g, " ");
}

function anyMatch(s: string, words: readonly string[]): boolean {
  const n = normalize(s);
  return words.some((w) => n.includes(normalize(w)));
}


// ============== 意图识别 ==============

/**
 * 从 transcript 解析语音意图。
 *
 * 注意:stop 比 play 优先级高 (用户说"停下放音乐" 应该停,不应播放)
 */
export function detectIntent(text: string): VoiceIntent {
  if (!text || !text.trim()) return { type: "none" };
  const raw = text.trim();

  // 1. 停止意图
  if (anyMatch(raw, STOP_TRIGGERS)) {
    // 但是 "我想停下来听点音乐" — 含 stop 又含 play, 这种边缘 case 走 play
    if (!anyMatch(raw, PLAY_TRIGGERS)) {
      return { type: "stop_sound", raw };
    }
  }

  // 2. 播放意图
  if (anyMatch(raw, PLAY_TRIGGERS)) {
    // 找最具体的音轨,若都没匹配则用默认
    let track: SoundId = DEFAULT_TRACK;
    for (const id of SOUND_IDS) {
      if (anyMatch(raw, TRACK_KEYWORDS[id])) {
        track = id;
        break;
      }
    }
    return { type: "play_sound", track, raw };
  }

  // 3. 用户只说了音轨名,没说 play/stop —— 这种也算播放意图
  //    e.g. "海浪" 单独一个词,显然要听
  if (raw.length <= 8) {
    for (const id of SOUND_IDS) {
      if (anyMatch(raw, TRACK_KEYWORDS[id])) {
        return { type: "play_sound", track: id, raw };
      }
    }
  }

  return { type: "none" };
}


// ============== 反馈文案 ==============
// 给 UI / TTS 用的确认句; 让用户知道命令收到了

const TRACK_LABEL_ZH: Record<SoundId, string> = {
  rain: "雨声",
  waves: "海浪",
  forest: "森林",
  fireplace: "壁炉",
  pinknoise: "粉色噪音",
};

const TRACK_LABEL_EN: Record<SoundId, string> = {
  rain: "rain",
  waves: "ocean waves",
  forest: "forest",
  fireplace: "fireplace",
  pinknoise: "pink noise",
};

export function intentAck(intent: VoiceIntent, locale: "zh" | "en" = "zh"): string {
  if (intent.type === "play_sound") {
    if (locale === "en") {
      return `🎵 Playing ${TRACK_LABEL_EN[intent.track]}…`;
    }
    return `🎵 已为你放${TRACK_LABEL_ZH[intent.track]}…`;
  }
  if (intent.type === "stop_sound") {
    return locale === "en" ? "🎵 Stopped." : "🎵 已停止。";
  }
  return "";
}
