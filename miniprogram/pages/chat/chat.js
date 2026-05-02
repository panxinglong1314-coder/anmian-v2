// pages/chat/chat.js
// Tab 1: 今晚聊聊 - 接真实 MiniMax API

const app = getApp()
const recorderManager = wx.getRecorderManager()

// 创建音频上下文（真机兼容性设置）
const innerAudioContext = wx.createInnerAudioContext({
  useWebAudioImplement: false // 使用原生音频播放更稳定
})
// 禁用静音开关限制，确保可以播放
innerAudioContext.obeyMuteSwitch = false

const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

function _decodeUTF8(buf) {
  if (typeof TextDecoder !== "undefined") {
    return new TextDecoder("utf-8").decode(buf)
  }
  const bytes = new Uint8Array(buf)
  let out = "", i = 0
  while (i < bytes.length) {
    const c = bytes[i++]
    if (c < 0x80) {
      out += String.fromCharCode(c)
    } else if (c < 0xC0) {
    } else if (c < 0xE0) {
      const c2 = bytes[i++]
      out += String.fromCharCode(((c & 0x1F) << 6) | (c2 & 0x3F))
    } else if (c < 0xF0) {
      const c2 = bytes[i++]
      const c3 = bytes[i++]
      out += String.fromCharCode(((c & 0x0F) << 12) | ((c2 & 0x3F) << 6) | (c3 & 0x3F))
    } else {
      const c2 = bytes[i++]
      const c3 = bytes[i++]
      const c4 = bytes[i++]
      let code = ((c & 0x07) << 18) | ((c2 & 0x3F) << 12) | ((c3 & 0x3F) << 6) | (c4 & 0x3F)
      if (code > 0xFFFF) {
        code -= 0x10000
        out += String.fromCharCode(0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF))
      } else {
        out += String.fromCharCode(code)
      }
    }
  }
  return out
}

// VAD 参数
const VAD = {
  SILENCE_THRESHOLD: 0.05,
  SPEECH_TIMEOUT: 3000,  // 静音 3000ms 停止录音（给长句子留时间）
  MIN_UTTERANCE: 400,    // 最少录音 400ms
}

Page({
  data: {
    mode: 'sleep',
    isPremium: false,

    // 睡眠模式
    sleepModeActive: false,
    _asrPending: false,  // 防重复 ASR 发送
    isListening: false,
    isRecording: false,
    audioLevel: 0,
    statusText: '准备入睡',
    statusHint: '点击下方按钮，将手机放在枕边',
    conversationLog: [],
    isAIResponding: false,

    // 文字模式
    isLoading: false,
    messages: [],
    isPlayingTTS: false,
    ttsProgress: 0,
    ttsCurrentTime: '0:00',
    ttsDuration: '0:00',
    anxiety: { level: 'normal' },
    quickChips: ['脑子停不下来', '担心某件事', '就是不安', '有点难过'],
    inputText: '',
    usageDisplay: '',  // 本地计算的剩余用量显示（分钟）
    usageQuota: null,  // 后端返回的用量配额

    // 关闭仪式
    showClosure: false,
    conversationRound: 0,   // 对话轮次计数，达到3轮自动触发关闭仪式
    closureStep: 1,
    breathPhase: 'inhale',
    breathPhaseText: '吸气',
    breathTip: '用鼻子轻轻吸气',
    breathCycle: 1,
    breathProgress: 0,
    breathPhaseColor: '#F5C869',
    breathCountdown: 0,
    breathPhasePercent: 0,
    pmrCurrentPart: '全身',
    pmrTip: '放松每一个部位...',
    pmrTimer: null,
    _pmrActive: false,
    _autoCloseTimer: null,
    _dimming: false,

    // 担忧捕获（CBT 担忧写下来）
    showWorryPrompt: false,
    worryCaptureActive: false,
    worryCaptureTimer: null,
    worryPendingText: '',   // 用户刚说的担忧内容

    // 白噪音
    currentSound: null,
    sounds: [
      { id: 'rain', name: '🌧️ 雨声' },
      { id: 'forest', name: '🌲 森林' },
      { id: 'fireplace', name: '🔥 壁炉' },
      { id: 'pinknoise', name: '📻 粉噪音' },
      { id: 'waves', name: '🌊 海浪' },
    ],

    // 隐私协议
    showPrivacyModal: false,

    // 内部
    _listenTimer: null,
    _volumeSim: null,
    _silenceTimer: null,
    _ttsTimer: null,
    _textTtsTimer: null,
    _recordingFilePath: null,
    ttsQueue: [],
    vizBarHeights: [12, 20, 16, 28, 10, 24, 14, 32, 18, 26, 12, 30, 16, 22, 14, 36],

    // 夜间陪伴模式
    companionLevel: 0,  // 0=未触发, 每触发一次+1

    // 入睡检测
    sleepDetectionQuietMs: 0,
    isSleepFadingOut: false,
  },

  // 入睡检测常量
  SLEEP_DETECTION_THRESHOLD_MS: 8 * 60 * 1000,  // 连续安静 8 分钟触发入睡淡出

  // 陪伴模式常量
  COMPANION_SILENCE_MS: 3 * 60 * 1000,  // 3分钟静默后触发
  COMPANION_POOL: [
    { text: '肩膀松了', speed: 70 },
    { text: '呼吸还在', speed: 70 },
    { text: '把呼吸放长', speed: 70 },
    { text: '不急', speed: 70 },
    { text: '躺平就好', speed: 70 },
  ],

  // ================================================
  // 模式切换
  // ================================================
  goToSubscribe() {
    wx.navigateTo({ url: '/pages/subscribe/subscribe' })
  },

  toggleMode() {
    if (this.data.mode === 'sleep') {
      this.exitSleepMode()
      this.stopAll()
      // 先切模式，在 setData 回调中再清空 messages，避免与后续 _sendToAI 的 setData 冲突
      this.setData({ mode: 'text', conversationLog: [], conversationRound: 0 }, () => {
        this.setData({ messages: [] })
      })
    } else {
      this.stopAll()
      this.setData({ mode: 'sleep', messages: [], conversationLog: [], conversationRound: 0 })
    }
    this._updateFreeChatsDisplay()
  },

  // 更新用量显示（在 onShow 中调用）
  _updateFreeChatsDisplay() {
    this._updateUsageDisplay()
  },

  // ================================================
  // 睡眠模式 - VAD 语音活动检测
  // ================================================
  toggleSleepMode() {
    if (this.data.sleepModeActive) {
      this.exitSleepMode()
    } else {
      this.enterSleepMode()
    }
  },

  onPrivacyAgree() {
    wx.setStorageSync('privacy_agreed', true)
    this.setData({ showPrivacyModal: false })
    // 先走微信官方隐私协议，再走录音权限
    this._requirePrivacyAndAuth()
  },

  _requirePrivacyAndAuth() {
    if (!wx.getPrivacySetting) {
      // 低版本基础库兜底
      this._requestRecordAuth()
      return
    }
    wx.getPrivacySetting({
      success: (res) => {
        if (res.needAuthorization) {
          wx.requirePrivacyAuthorize({
            success: () => this._requestRecordAuth(),
            fail: () => wx.showToast({ title: '需同意微信隐私协议方可使用语音', icon: 'none' })
          })
        } else {
          this._requestRecordAuth()
        }
      },
      fail: () => this._requestRecordAuth()
    })
  },

  _requestRecordAuth() {
    wx.authorize({
      scope: 'scope.record',
      success: () => console.log('[Privacy] 录音权限已授权'),
      fail: () => wx.showToast({ title: '需要录音权限才能使用睡眠模式', icon: 'none', duration: 2000 })
    })
  },

  onPrivacyDisagree() {
    wx.setStorageSync('privacy_agreed', false)
    this.setData({ showPrivacyModal: false })
    wx.showToast({ title: '您可继续使用文字模式', icon: 'none', duration: 2000 })
  },

  enterSleepMode() {
    // 先检查自定义隐私协议
    if (!wx.getStorageSync('privacy_agreed')) {
      this.setData({ showPrivacyModal: true })
      return
    }
    // 再走微信官方隐私协议与录音授权
    this._checkPrivacyAndEnter()
  },

  _checkPrivacyAndEnter() {
    const proceed = () => {
      wx.getSetting({
        success: (res) => {
          if (!res.authSetting['scope.record']) {
            wx.authorize({
              scope: 'scope.record',
              success: () => {
                console.log('[Auth] record authorized')
                this._doEnterSleepMode()
              },
              fail: () => {
                console.log('[Auth] record denied')
                wx.showToast({ title: '需要录音权限才能使用睡眠模式', icon: 'none', duration: 2000 })
              }
            })
          } else {
            this._doEnterSleepMode()
          }
        }
      })
    }
    if (!wx.getPrivacySetting) {
      proceed()
      return
    }
    wx.getPrivacySetting({
      success: (res) => {
        if (res.needAuthorization) {
          wx.requirePrivacyAuthorize({
            success: () => proceed(),
            fail: () => wx.showToast({ title: '需同意微信隐私协议方可使用语音', icon: 'none' })
          })
        } else {
          proceed()
        }
      },
      fail: () => proceed()
    })
  },

  _doEnterSleepMode() {
    // iOS 音频自动播放解锁：利用用户点击的同步上下文先 play 一次
    try {
      innerAudioContext.stop()
      innerAudioContext.src = 'data:audio/wav;base64,UklGRigAAABXQVZFZm10IBAAAAABAAEAQB8AAEAfAAABAAgAZGF0YQQAAAAAAA=='
      innerAudioContext.play()
      innerAudioContext.stop()
    } catch (e) {}

    // 恢复音量（退出时可能被设为0）
    try { innerAudioContext.volume = 1.0 } catch (e) {}
    
    this.setData({
      sleepModeActive: true,
      statusText: '聆听中',
      statusHint: '手机放在枕边，开口说话即可',
      conversationRound: 0,
      conversationLog: [],
      companionLevel: 0,
    }, () => {
      // setData 完成后确保 VAD 启动
      this._startVADLoop()
      // 启动陪伴计时器
      this._resetCompanionTimer()
    })
  },

  exitSleepMode() {
    this._vadActive = false
    this.stopListening()
    this.stopAll()
    if (this._companionTimer) clearTimeout(this._companionTimer)
    try { innerAudioContext.volume = 0 } catch (e) {}
    this.setData({
      sleepModeActive: false, isListening: false,
      isRecording: false, audioLevel: 0,
      statusText: '准备入睡',
      statusHint: '点击下方按钮，将手机放在枕边',
      sleepDetectionQuietMs: 0,
      isSleepFadingOut: false,
      companionLevel: 0,
    })
  },

  _startVADLoop() {
    console.log('[_VAD] start, sleepModeActive:', this.data.sleepModeActive, 'mode:', this.data.mode)
    if (!this.data.sleepModeActive) return
    // 如果 TTS 还在播，延迟启动 VAD，避免把 AI 自己的话录进去
    if (this.data.isPlayingTTS) {
      console.log('[_VAD] TTS still playing, defer start')
      if (this._listenTimer) clearTimeout(this._listenTimer)
      this._listenTimer = setTimeout(() => this._startVADLoop(), 800)
      return
    }
    this._vadActive = true
    this._recordingState = 'vad'
    this.setData({ isListening: true })
    console.log('[_VAD] calling recorderManager.start()')
    recorderManager.start({
      format: 'mp3', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 48000, duration: 1200
    })
  },

  _start正式录音() {
    if (this._listenTimer) clearTimeout(this._listenTimer)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    // 用户开始说话，重置陪伴计时器
    this._resetCompanionTimer()
    this._vadActive = false
    try { recorderManager.stop() } catch (e) {}
    this.setData({ isRecording: true, isListening: false, audioLevel: 8, statusText: '正在听...', statusHint: '说完后稍等，我会回应' })

    // 建立 WebSocket ASR
    this._fallbackUploadASR = false
    const wsUrl = `${API.replace(/^http/, 'ws')}/api/v1/asr/ws`
    this._asrSocket = wx.connectSocket({ url: wsUrl })
    this._asrSocketReady = false

    this._asrSocket.onOpen(() => {
      this._asrSocketReady = true
      console.log('[ASR-WS] socket open')
    })

    this._asrSocket.onMessage((res) => {
      console.log('[ASR-WS] onMessage raw:', res.data)
      try {
        const data = JSON.parse(res.data)
        if (data.error) {
          console.error('[ASR-WS] error:', data.error)
          this._fallbackUploadASR = true
      this.setData({ _asrPending: false })
          return
        }
        if (data.slice_type === 2) {
          this.setData({ statusText: '正在听：' + data.text })
        }
        if (data.is_final || data.slice_type === 2) {
          this._asrSocket.close()
          this._asrSocket = null
          this._asrSocketReady = false
          this.setData({ _asrPending: false })
          if (data.text && data.text.trim()) {
            this._sendToAI(data.text.trim(), true)
          } else {
            this._playTTS('不好意思没听清楚，你可以慢慢再说一次吗？', true)
          }
        }
      } catch (e) {
        console.error('[ASR-WS] parse error:', e)
      }
    })

    this._asrSocket.onError((err) => {
      console.error('[ASR-WS] socket error:', err)
      this._fallbackUploadASR = true
      this.setData({ _asrPending: false })
      if (err && err.errMsg && err.errMsg.includes('url not in domain list')) {
        wx.showToast({ title: '请在开发者工具「详情」中勾选「不校验合法域名」', icon: 'none', duration: 3000 })
      }
    })

    this._asrSocket.onClose(() => {
      this._asrSocketReady = false
    })

    // 开始正式录音（PCM，用于 fallback 上传 ASR；frameSize 保证 onFrameRecorded 正常触发）
    this._recordingState = 'asr'
    recorderManager.start({
      format: 'pcm', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 64000, duration: 15000,
      frameSize: 1280
    })

    this._volumeSim = setInterval(() => {
      if (this.data.isRecording) this.setData({ audioLevel: Math.floor(Math.random() * 8) + 5 })
    }, 150)

    this._silenceTimer = setTimeout(() => {
      if (this.data.sleepModeActive && this.data.isRecording) this._stop正式录音()
    }, VAD.SPEECH_TIMEOUT)
  },

  _stop正式录音() {
    if (this._volumeSim) clearInterval(this._volumeSim)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
    recorderManager.stop()
    // onStop 统一回调会处理后续（发送 end 标记 或 fallback）
  },

  // ================================================
  // 真实 API：ASR 语音转文字（腾讯云实时识别 + 流式处理）
  // ================================================
  _sendVoiceToASR(filePath) {
    if (this.data._asrPending) {
      console.log('[_ASR] pending, skipping')
      return
    }
    this.setData({ _asrPending: true })
    // 使用腾讯云流式 ASR（更快识别）
    wx.uploadFile({
      url: `${API}/api/v1/asr/stream`,
      filePath: filePath,
      name: 'file',
      header: { 'Content-Type': 'multipart/form-data' },
      success: (res) => {
        console.log('[ASR] response, status:', res.statusCode, 'data:', res.data)
        let json = res.data
        if (typeof res.data === 'string') {
          try { json = JSON.parse(res.data) } catch(e) { json = {} }
        }
        const text = (json.text || '').trim()
        const engine = json.engine || 'unknown'
        console.log(`[ASR] engine=${engine}, text=${text}`)
        if (!text) {
          this.setData({ _asrPending: false })
          setTimeout(() => this._startVADLoop(), 800)
          return
        }
        // 回声/短词丢弃：如果识别结果太短或是常见 AI 口头禅，说明可能是回声或噪音
        if (text.length <= 2 || ['不错', '好的', '嗯', '啊', '哦', '在'].includes(text)) {
          console.log('[ASR] too short/noise, dropping:', text)
          this.setData({ _asrPending: false })
          setTimeout(() => this._startVADLoop(), 800)
          return
        }
        // 用户说完有效内容，重置陪伴计时器
        this._resetCompanionTimer()
        // 传给 AI（睡眠模式）
        this._sendToAI(text, true)
      },
      fail: (err) => {
        console.error('[ASR Error]', err)
        this.setData({ _asrPending: false })
        this._playTTS('网络有点不稳定，你可以再说一次吗？', true)
      }
    })
  },

  // ================================================
  // 真实 API：AI 对话
  // ================================================
  // ================================================
  // 用量配额管理（按分钟计费）
  // ================================================
  // 获取当前配额限制（返回秒数）
  _getUsageLimit() {
    const sub = wx.getStorageSync('subscription') || {}
    if (sub.isPremium) {
      if (sub.planType === 'core') {
        return { voice: 108000, text: 108000, period: 'month' } // 30小时/月
      }
      return { voice: 54000, text: 54000, period: 'month' } // 15小时/月
    }
    return { voice: 180, text: 600, period: 'day' } // 免费版：3分钟/天语音，10分钟/天文本
  },

  // 获取已使用时长（秒）
  _getUsedSeconds(type) {
    const limit = this._getUsageLimit()
    if (limit.period === 'month') {
      const month = new Date().toISOString().slice(0, 7)
      const stored = wx.getStorageSync('monthly_usage') || {}
      const record = stored[month] || { voice: 0, text: 0 }
      return record[type] || 0
    } else {
      const today = new Date().toISOString().split('T')[0]
      const stored = wx.getStorageSync('daily_usage') || {}
      const record = stored[today] || { voice: 0, text: 0 }
      return record[type] || 0
    }
  },

  // 记录使用时长
  _recordUsage(type, seconds) {
    const limit = this._getUsageLimit()
    if (limit.period === 'month') {
      const month = new Date().toISOString().slice(0, 7)
      const stored = wx.getStorageSync('monthly_usage') || {}
      const record = stored[month] || { voice: 0, text: 0 }
      record[type] = (record[type] || 0) + seconds
      stored[month] = record
      wx.setStorageSync('monthly_usage', stored)
    } else {
      const today = new Date().toISOString().split('T')[0]
      const stored = wx.getStorageSync('daily_usage') || {}
      const record = stored[today] || { voice: 0, text: 0 }
      record[type] = (record[type] || 0) + seconds
      stored[today] = record
      wx.setStorageSync('daily_usage', stored)
    }
    this._updateUsageDisplay()
  },

  // 更新用量显示
  _updateUsageDisplay() {
    const limit = this._getUsageLimit()
    const voiceUsed = this._getUsedSeconds('voice')
    const textUsed = this._getUsedSeconds('text')
    const voiceRem = Math.max(0, limit.voice - voiceUsed)
    const textRem = Math.max(0, limit.text - textUsed)
    const period = limit.period === 'month' ? '本月' : '今日'
    const voiceMin = Math.floor(voiceRem / 60)
    const textMin = Math.floor(textRem / 60)
    this.setData({
      usageDisplay: `${period}剩余：语音 ${voiceMin} 分钟 · 文本 ${textMin} 分钟`,
      isPremium: limit.period === 'month'
    })
  },

  async _sendToAI(text, fromSleep = true) {
    // 任何交互都重置陪伴计时器
    this._resetCompanionTimer()
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''

    // ─── 担忧关键词检测（立刻触发，不等 AI 回复）───
    const worryKeywords = ['脑子停不下来', '一直在想', '反复担心', '胡思乱想', '控制不住', '睡不着脑子里', '一直想', '反复想', '停不下来', '想太多']
    const isWorry = worryKeywords.some(k => text.includes(k))
    if (isWorry) {
      this.setData({ worryPendingText: text })
      const t = setTimeout(() => this.setData({ showWorryPrompt: false }), 8000)
      this.setData({ worryCaptureTimer: t })
      this.setData({ showWorryPrompt: true })
    }

    // ─── 对话轮次计数（仅文字模式限制，睡眠模式无限）───
    const round = (this.data.conversationRound || 0) + 1
    this.setData({ conversationRound: round })

    const log = [...this.data.conversationLog, { role: 'user', text }]
    this.setData({
      conversationLog: fromSleep ? log : this.data.conversationLog,
      isAIResponding: true,
      isLoading: !fromSleep,
      statusText: '正在思考...',
      statusHint: fromSleep ? '收到，请稍等' : ''
    })

    // 文字模式先显示用户消息
    if (!fromSleep) {
      const userMsg = { id: 'msg_' + Date.now(), role: 'user', content: text, time: this._now(), isPlayingTTS: false }
      const msgs = this.data.messages.concat(userMsg)
      this.setData({ messages: msgs, inputText: '' })
    }

    let streamingText = ''
    const flushText = () => {
      if (!fromSleep) {
        const msgs = this.data.messages.slice()
        const lastIdx = msgs.length - 1
        if (lastIdx >= 0 && msgs[lastIdx].role === 'assistant') {
          msgs[lastIdx].content = streamingText
          this.setData({ messages: msgs })
        } else {
          msgs.push({ id: 'ai_' + Date.now(), role: 'assistant', content: streamingText, time: this._now(), isPlayingTTS: false, feedback: undefined })
          this.setData({ messages: msgs })
        }
      }
      const newLog = [...this.data.conversationLog]
      const aiIdx = newLog.findIndex(m => m.role === 'assistant' && m._streaming)
      if (aiIdx >= 0) {
        newLog[aiIdx].text = streamingText
      } else {
        newLog.push({ role: 'assistant', text: streamingText, _streaming: true })
      }
      this.setData({ conversationLog: newLog })
    }

    const requestTask = wx.request({
      url: `${API}/api/v1/chat/cbt/stream`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { user_id: userId, message: text, session_id: sessionId },
      enableChunked: true,
      success: (res) => {
        const finalLog = this.data.conversationLog.map(m => {
          if (m._streaming) delete m._streaming
          return m
        })
        this.setData({
          isAIResponding: false,
          isLoading: false,
          conversationLog: finalLog,
          statusText: fromSleep ? (this.data.isPlayingTTS ? '正在播放' : '聆听中') : '',
          statusHint: fromSleep ? (this.data.isPlayingTTS ? '闭上眼睛，听我说' : '继续说吧') : ''
        })
        // 统一重置 ASR pending（无论文字/语音模式）
        this.setData({ _asrPending: false })

        if (fromSleep && this.data.sleepModeActive && !this.data.isPlayingTTS && (this.data.ttsQueue || []).length === 0) {
          const finalText = streamingText.trim()
          console.log('[SleepMode] SSE done, hasStreamTTS:', hasStreamTTS, 'finalText:', finalText || '(empty)')
          // 如果流式过程中已经下发了 tts_audio，就不再整句 fallback 合成
          if (!hasStreamTTS && finalText) {
            this._playTTS(finalText, true)
          } else if (!hasStreamTTS && !finalText) {
            setTimeout(() => this._startVADLoop(), 500)
          }
          // 如果 hasStreamTTS 为 true，且 TTS 已经播放或还在队列中，
          // onEnded 回调会自动重启 VAD，这里不需要额外处理
        }

        if (!fromSleep) {
          const finalText = streamingText.trim()
          if (!hasStreamTTS && finalText) {
            this._playTTS(finalText, false)
          }
          const closeDecision = this._shouldTriggerClosure(text, streamingText)
          if (closeDecision.trigger) {
            console.log('[Closure] trigger:', closeDecision.reason, 'delay:', closeDecision.delay)
            setTimeout(() => this.triggerClosure(), closeDecision.delay)
          }
        }
      },
      fail: (err) => {
        console.error('[Chat Stream Error]', err)
        this.setData({ isAIResponding: false, isLoading: false, _asrPending: false })
        if (fromSleep) {
          this._playTTS('刚才没听清楚，可以再说一遍吗？', true)
        } else {
          this.setData({ statusText: '聆听中', statusHint: '服务暂时不稳定，请重试' })
          if (this.data.sleepModeActive) setTimeout(() => this._startVADLoop(), 2000)
        }
      }
    })

    let sseBuffer = ''
    let hasStreamTTS = false
    requestTask.onChunkReceived((res) => {
      let chunk = ''
      try {
        if (typeof TextDecoder !== 'undefined') {
          chunk = new TextDecoder('utf-8').decode(res.data || new ArrayBuffer(0))
        } else {
          const bytes = new Uint8Array(res.data || new ArrayBuffer(0))
          let out = '', i = 0
          while (i < bytes.length) {
            const c = bytes[i++]
            if (c < 0x80) out += String.fromCharCode(c)
            else if (c < 0xC0) { }
            else if (c < 0xE0) out += String.fromCharCode(((c & 0x1F) << 6) | (bytes[i++] & 0x3F))
            else if (c < 0xF0) out += String.fromCharCode(((c & 0x0F) << 12) | ((bytes[i++] & 0x3F) << 6) | (bytes[i++] & 0x3F))
            else {
              const c2 = bytes[i++], c3 = bytes[i++], c4 = bytes[i++]
              let code = ((c & 0x07) << 18) | ((c2 & 0x3F) << 12) | ((c3 & 0x3F) << 6) | (c4 & 0x3F)
              if (code > 0xFFFF) { code -= 0x10000; out += String.fromCharCode(0xD800 + (code >> 10), 0xDC00 + (code & 0x3FF)) }
              else { out += String.fromCharCode(code) }
            }
          }
          chunk = out
        }
      } catch (e) { chunk = '' }
      sseBuffer += chunk
      const lines = sseBuffer.split('\n')
      sseBuffer = lines.pop()
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const data = JSON.parse(line.slice(6))
          if (data.event === 'chunk') {
            streamingText += data.data
            flushText()
          }
          if (data.event === 'final' && data.content) {
            streamingText = data.content
            flushText()
          }
          if (data.event === 'tts_audio' && data.audio_base64) {
            hasStreamTTS = true
            this._enqueueTTS(data.audio_base64, fromSleep)
          }
        } catch (e) {
          console.error('[SSE] parse error:', e)
        }
      }
    })
  },

  // ================================================
  // TTS 音频队列播放（句子级分段，接近流式体验）
  // ================================================
  _playTTS(text, fromSleep = false, speed = 90, volume = 1.0) {
    // 兼容旧调用：整句直接合成 fallback
    this._fallbackTTS(text, fromSleep, speed, volume)
  },

  _fallbackTTS(text, fromSleep = false, speed = 90, volume = 1.0) {
    // 任何 AI 发声都重置陪伴计时器
    this._resetCompanionTimer()
    console.log('[TTS] fallback synthesize:', text.slice(0, 60))
    const fs = wx.getFileSystemManager()
    const filePath = `${wx.env.USER_DATA_PATH}/tts_fallback_${Date.now()}.mp3`
    wx.request({
      url: `${API}/api/v1/tts/stream?text=${encodeURIComponent(text.slice(0, 500))}&voice=female_warm&speed=${speed}`,
      method: 'POST',
      responseType: 'arraybuffer',
      success: (res) => {
        if (!res.data || res.data.byteLength === 0) return
        fs.writeFile({
          filePath,
          data: res.data,
          encoding: 'binary',
          success: () => {
            innerAudioContext.stop()
            innerAudioContext.src = filePath
            try { innerAudioContext.offError && innerAudioContext.offError() } catch(e){}
            try { innerAudioContext.offEnded && innerAudioContext.offEnded() } catch(e){}
            innerAudioContext.onError(() => {
              this.setData({ isPlayingTTS: false, _asrPending: false })
              if (fromSleep && this.data.sleepModeActive) {
                setTimeout(() => this._startVADLoop(), 1800)
              }
            })
            innerAudioContext.onEnded(() => {
              this.setData({ isPlayingTTS: false, _asrPending: false })
              // 入睡淡出模式：播放完后安静退出
              if (this.data.isSleepFadingOut) {
                this.setData({ isSleepFadingOut: false, sleepDetectionQuietMs: 0, companionLevel: 0 })
                this.exitSleepMode()
                return
              }
              // AI 语音结束，重置陪伴计时器
              if (this.data.sleepModeActive) this._resetCompanionTimer()
              if (fromSleep && this.data.sleepModeActive) {
                this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
                setTimeout(() => this._startVADLoop(), 1800)
              }
            })
            innerAudioContext.volume = volume
            innerAudioContext.play()
          }
        })
      }
    })
  },

  _enqueueTTS(audioBase64, fromSleep = false) {
    const queue = this.data.ttsQueue || []
    queue.push({ audioBase64, fromSleep })
    this.setData({ ttsQueue: queue })
    if (!this.data.isPlayingTTS) {
      this._playNextTTS()
    }
  },

  _playNextTTS() {
    // TTS 队列开始播放，重置陪伴计时器
    this._resetCompanionTimer()
    const queue = this.data.ttsQueue || []
    if (queue.length === 0) {
      this.setData({ isPlayingTTS: false })
      return
    }
    const item = queue.shift()
    this.setData({ ttsQueue: queue, isPlayingTTS: true })
    if (item.fromSleep) {
      this.setData({ statusText: '正在播放', statusHint: '闭上眼睛，听我说' })
    }

    const fs = wx.getFileSystemManager()
    const filePath = `${wx.env.USER_DATA_PATH}/tts_seg_${Date.now()}.mp3`

    try {
      fs.writeFile({
        filePath,
        data: wx.base64ToArrayBuffer(item.audioBase64),
        encoding: 'binary',
        success: () => {
          // 真机兼容：使用新实例播放，避免全局单例竞态
          const ctx = wx.createInnerAudioContext({ useWebAudioImplement: false })
          ctx.obeyMuteSwitch = false
          ctx.src = filePath
          ctx.onError((err) => {
            console.error('[TTS] play error:', err)
            ctx.destroy()
            this.setData({ isPlayingTTS: false })
            this._playNextTTS()
          })
          ctx.onEnded(() => {
            ctx.destroy()
            this.setData({ isPlayingTTS: false, _asrPending: false })
            if (this.data.sleepModeActive) this._resetCompanionTimer()
            if (item.fromSleep && this.data.sleepModeActive && (this.data.ttsQueue || []).length === 0) {
              this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
              setTimeout(() => this._startVADLoop(), 1800)
            }
            this._playNextTTS()
          })
          // 真机上需要短暂延迟再播放
          setTimeout(() => {
            try { ctx.play() } catch(e) { console.error('[TTS] play fail:', e) }
          }, 50)
        },
        fail: (err) => {
          console.error('[TTS] write fail:', err)
          this._playNextTTS()
        }
      })
    } catch (e) {
      console.error('[TTS] write error:', e)
      this._playNextTTS()
    }
  },

  // ================================================
  // 夜间陪伴模式 — 主动关怀
  // ================================================
  _startCompanionTimer() {
    if (this._companionTimer) clearTimeout(this._companionTimer)
    this._companionTimer = setTimeout(() => {
      this._playCompanionVoice()
    }, this.COMPANION_SILENCE_MS)
  },

  _resetCompanionTimer() {
    if (!this.data.sleepModeActive) return
    this._startCompanionTimer()
  },

  _playCompanionVoice() {
    // 安全检查：只在睡眠模式、未录音、未播放 TTS、无队列时触发
    if (!this.data.sleepModeActive) return
    if (this.data.isRecording) { this._resetCompanionTimer(); return }
    if (this.data.isPlayingTTS) { this._resetCompanionTimer(); return }
    const queue = this.data.ttsQueue || []
    if (queue.length > 0) { this._resetCompanionTimer(); return }

    const level = Math.min(this.data.companionLevel, this.COMPANION_POOL.length - 1)
    const item = this.COMPANION_POOL[level]
    console.log('[Companion] level', level, 'text:', item.text)

    // 播放 companion 语音：慢速、低音量（耳语气）
    this._fallbackTTS(item.text, true, item.speed, 0.4)

    // 升级 companionLevel
    this.setData({ companionLevel: this.data.companionLevel + 1 })
  },

  _triggerSleepFadeOut() {
    console.log('[Sleep] fade out triggered')
    // 标记为正在淡出，禁用 companion 和 VAD
    this.setData({ isSleepFadingOut: true })
    if (this._companionTimer) clearTimeout(this._companionTimer)
    if (this._listenTimer) clearTimeout(this._listenTimer)
    // 播放极轻的"睡吧"，播放完后 onEnded 中自动 exitSleepMode
    this._fallbackTTS('睡吧', true, 70, 0.3)
  },

  _textSimilarity(a, b) {
    if (!a || !b) return 0
    const na = a.replace(/[，。！？、,.?!\s]/g, '').toLowerCase()
    const nb = b.replace(/[，。！？、,.?!\s]/g, '').toLowerCase()
    if (!na.length || !nb.length) return 0
    if (na.includes(nb) || nb.includes(na)) return 1
    const setA = new Set(na)
    let common = 0
    for (const ch of nb) {
      if (setA.has(ch)) common++
    }
    return common / Math.max(na.length, nb.length)
  },

  _startTTSProgress(durationMs) {
    let step = 0
    const total = 50
    this._ttsTimer = setInterval(() => {
      step++
      this.setData({ ttsProgress: Math.min(Math.floor((step / total) * 100), 100) })
      if (step >= total) {
        clearInterval(this._ttsTimer)
      }
    }, durationMs / total)
  },

  // ================================================
  // 停止一切
  // ================================================
  stopAll() {
    if (this._listenTimer) clearTimeout(this._listenTimer)
    if (this._ttsTimer) clearInterval(this._ttsTimer)
    if (this._volumeSim) clearInterval(this._volumeSim)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    if (this._textTtsTimer) clearInterval(this._textTtsTimer)
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)
    if (this._companionTimer) clearTimeout(this._companionTimer)
    if (this.data.isRecording || this.data.isListening) {
      try { recorderManager.stop() } catch (e) {}
    }
    try { innerAudioContext.stop() } catch (e) {}
    try { innerAudioContext.volume = 0 } catch (e) {}
  },

  stopListening() {
    this.stopAll()
    this.setData({ isListening: false, isRecording: false, audioLevel: 0 })
  },

  // ================================================
  // 关闭仪式
  // ================================================
  // 关闭仪式触发判断（多维条件）
  // ================================================
  _shouldTriggerClosure(userMessage, aiResponse) {
    const msg = (userMessage || '').trim()
    const resp = (aiResponse || '').trim()

    // 1. 显式结束信号（最高优先级）
    const explicitEndSignals = ['不用了', '不聊了', '睡了', '晚安', '先这样', '行了', '好了', '去睡了', '拜拜', '再见']
    if (explicitEndSignals.some(s => msg.includes(s))) {
      return { trigger: true, delay: 0, reason: '用户说晚安' }
    }

    // 2. 隐式结束信号（睡意出现）
    const sleepSignals = ['困了', '想睡了', '睡着了', '闭眼', '关机了', '先了', '好困', '睁不开眼']
    if (sleepSignals.some(s => msg.includes(s))) {
      return { trigger: true, delay: 1500, reason: '用户说困了' }
    }

    // 3. AI 说了关闭信号
    const closureSignals = ['深呼吸', '静下来', '放松', '把手机放下', '睡吧', '晚安', '休息', '闭上眼睛']
    const hasClosureSignal = closureSignals.some(s => resp.includes(s))
    if (hasClosureSignal) {
      return { trigger: true, delay: 2000, reason: 'AI引导关闭' }
    }

    // 4. 对话轮数过多
    if (this.data.conversationRound >= 5) {
      return { trigger: true, delay: 1000, reason: '对话轮数过多' }
    }

    // 5. 凌晨深夜加速（1-5点）
    const hour = new Date().getHours()
    if (hour >= 1 && hour <= 5 && this.data.conversationRound >= 1) {
      return { trigger: true, delay: 500, reason: '凌晨深夜模式' }
    }

    return { trigger: false }
  },

  _isLateNight() {
    const hour = new Date().getHours()
    return hour >= 1 && hour <= 5
  },

  // ================================================
  triggerClosure() {
    this.exitSleepMode()
    if (this._step2Timer) clearTimeout(this._step2Timer)
    // Read saved sleep window or use defaults
    const saved = wx.getStorageSync('bed_time_setting') || {}
    this.setData({
      showClosure: true,
      closureStep: 1,  // Step 1: Set sleep window
      conversationRound: 0,
      bedTime: saved.bedHour !== undefined
        ? `${String(saved.bedHour).padStart(2,'0')}:${String(saved.bedMin||0).padStart(2,'0')}`
        : '23:00',
      wakeTime: saved.wakeHour !== undefined
        ? `${String(saved.wakeHour).padStart(2,'0')}:${String(saved.wakeMin||0).padStart(2,'0')}`
        : '07:00',
      tibHours: '8.0',
    })
  },

  onBedTimeChange(e) {
    const time = e.detail.value  // "HH:MM"
    this.setData({ bedTime: time })
    this._updateTibHours()
  },

  onWakeTimeChange(e) {
    const time = e.detail.value
    this.setData({ wakeTime: time })
    this._updateTibHours()
  },

  _updateTibHours() {
    const [bh, bm] = this.data.bedTime.split(':').map(Number)
    const [wh, wm] = this.data.wakeTime.split(':').map(Number)
    let tib = (wh * 60 + wm) - (bh * 60 + bm)
    if (tib < 0) tib += 24 * 60  // handle midnight crossing
    const hours = (tib / 60).toFixed(1)
    this.setData({ tibHours: hours })
  },

  submitBedTime() {
    const [bh, bm] = this.data.bedTime.split(':').map(Number)
    const [wh, wm] = this.data.wakeTime.split(':').map(Number)
    const setting = { bedHour: bh, bedMin: bm, wakeHour: wh, wakeMin: wm }

    // Save to storage
    wx.setStorageSync('bed_time_setting', setting)

    // POST to sleep window API (non-blocking)
    wx.request({
      url: `${API}/api/v1/sleep/window`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { user_id: app.globalData.userId || '', bed_hour: bh, bed_min: bm, wake_hour: wh, wake_min: wm },
      fail: () => {}  // non-critical
    })

    // POST to sleep diary bedtime API - 保存今晚睡眠计划
    wx.request({
      url: `${API}/api/v1/sleep/diary/bedtime`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        user_id: app.globalData.userId || '',
        planned_bed_time: this.data.bedTime,
        planned_wake_time: this.data.wakeTime,
      },
      success: (res) => {
        console.log('[Bedtime saved]', res.data)
      },
      fail: () => {}  // non-critical
    })

    // Move to Step 2 (worry) or Step 3 (PMR breathing)
    if (this.data.showWorryPrompt || this.data.worryPendingText) {
      this.setData({ closureStep: 2 })  // Step 2: worry prompt
    } else {
      this.setData({ closureStep: 3 })  // Step 3: PMR breathing
      setTimeout(() => this.startBreathingInClosure(), 500)
      return
    }
    // Step 2 晚安页面停留 2s 后自动进入 Step 3
    if (this._step2Timer) clearTimeout(this._step2Timer)
    this._step2Timer = setTimeout(() => {
      if (this.data.closureStep === 2) {
        this.setData({ closureStep: 3 })
        setTimeout(() => this.startBreathingInClosure(), 500)
      }
    }, 2000)
  },

  startBreathingInClosure() {
    const phases = [
      { phase: 'inhale', text: '吸气', tip: '用鼻子轻轻吸气', duration: 4, color: '#F5C869' },
      { phase: 'hold',   text: '屏息', tip: '保持安静', duration: 7, color: '#6B9FD4' },
      { phase: 'exhale',  text: '呼气', tip: '用嘴缓慢呼出', duration: 8, color: '#7EC8A3' }
    ]
    // 凌晨模式：只1轮呼吸，快速进入PMR
    const maxCycles = this._isLateNight() ? 1 : 4
    let cycle = 1, phaseIdx = 0
    // 清除旧定时器
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)

    const runPhase = () => {
      if (cycle > maxCycles) {
        this.setData({ breathPhase: '', breathPhaseText: '', breathCountdown: 0, breathPhasePercent: 0 })
        setTimeout(() => { this.setData({ closureStep: 4 }); this.startPMR() }, 300)
        return
      }
      const p = phases[phaseIdx]
      let remaining = p.duration
      // 设置当前阶段状态
      this.setData({
        breathPhase: p.phase,
        breathPhaseText: p.text,
        breathTip: p.tip,
        breathCycle: cycle,
        breathCountdown: remaining,
        breathPhasePercent: 0,
        breathPhaseColor: p.color,
      })
      // 呼吸引导语音数秒：吸气/呼气时 AI 主动语音引导，屏息时静默
      if (p.phase === 'inhale' || p.phase === 'exhale') {
        this._playBreathGuide(p.text, p.duration)
      }
      // 阶段内每秒更新倒计时和进度
      this._breathCountdownTimer = setInterval(() => {
        remaining--
        if (remaining < 0) return
        const percent = Math.floor(((p.duration - remaining) / p.duration) * 100)
        this.setData({ breathCountdown: remaining, breathPhasePercent: percent })
      }, 1000)
      // 阶段结束时切换到下一阶段
      this._breathPhaseTimer = setTimeout(() => {
        clearInterval(this._breathCountdownTimer)
        this._breathCountdownTimer = null
        phaseIdx++
        if (phaseIdx >= phases.length) {
          phaseIdx = 0
          cycle++
        }
        runPhase()
      }, p.duration * 1000)
    }

    runPhase()
  },

  _playBreathGuide(phaseName, duration) {
    // 生成数秒文案，如 "吸气，一，二，三，四"
    const numbers = ['一', '二', '三', '四', '五', '六', '七', '八']
    const countText = numbers.slice(0, duration).join('，')
    const text = `${phaseName}，${countText}`
    // 慢速、低音量，不期待用户回应（fromSleep=true 但不清除 companion）
    this._fallbackTTS(text, true, 75, 0.45)
  },

  skipBreathing() {
    this._handleVoiceSkip()
  },

  skipPMR() {
    this._handleVoiceSkip()
  },

  // ==========================================
  // 步骤 3: PMR 身体扫描（AI 语音引导）
  // ==========================================

  startPMR() {
    // PMR 需 Premium
    if (!this.data.isPremium) {
      wx.showModal({
        title: '👑 升级 Premium',
        content: 'PMR 身体扫描是 Premium 功能，升级后即可使用',
        confirmText: '去升级',
        cancelText: '稍后',
        success: res => {
          if (res.confirm) wx.navigateTo({ url: '/pages/subscribe/subscribe' })
          else { this.setData({ closureStep: 2 }) }
        }
      })
      return
    }
    // MiniMax TTS 引导文本（完整版 6 分钟）
    const PMR_SCRIPT = `现在，轻轻闭上眼睛。

我们用一点时间，照顾一下自己的身体。

把注意力放到左脚趾。
感受到它们和床接触的感觉。
现在，慢慢收紧脚趾……好像在把脚趾向脚背靠拢……
保持……感受这股张力……
松开……感觉血流重新流回脚趾，温暖而放松。

把注意力移到左小腿。
收紧小腿肌肉……保持……松开。
感受放松的感觉从小腿蔓延到膝盖。

把注意力移到左大腿。
收紧大腿……保持……松开。
整条左腿都变得很沉，很温暖。

现在，同样的过程，在右腿开始。
从脚趾……小腿……大腿……
感受整条右腿也完全放松。

现在，把注意力放到腹部。
腹式呼吸时，腹部轻轻起伏。
感受这种自然的节奏。你不需要控制它，只是感受。

现在，注意力移到胸口。
感受心跳。它稳定、有力、安静地跳动。你安全地在这里。

现在，注意力移到双手。
从手指开始……收紧……保持……松开。
感受手心有一丝温暖。双手、手臂、肩膀，现在都变得很沉，所有的重量都交给床。

现在，注意力移到面部。
眉头……收紧……松开。眼皮……完全放松。下颌……轻轻张开，让它完全放松。

最后，把注意力放到整个头部。
想象有一股温暖的光，从头顶轻轻笼罩。
从头皮……额头……眼睛……下巴。你整个人都被这份温暖包裹着。

现在，你躺在这里，身体完全放松。
心里可能有一点点思绪在飘。不要抓住它们，也不要推开它们。
只是看着它们来，看着它们走。像云一样飘过天空。

准备好入睡了。晚安。`

    // 调用 MiniMax TTS 生成音频
    this.setData({ _pmrActive: true })
    this._playTTS(PMR_SCRIPT, false)

    // 身体扫描进度序列（与音频同步）
    const sequence = [
      { part: '左脚趾', tip: '收紧...保持...松开...', t: 0 },
      { part: '左小腿', tip: '感受放松蔓延到膝盖...', t: 15 },
      { part: '左大腿', tip: '整条左腿完全放松...', t: 30 },
      { part: '右腿', tip: '从脚趾到小腿，再到大腿...', t: 45 },
      { part: '腹部', tip: '腹式呼吸，自然起伏...', t: 65 },
      { part: '胸部', tip: '心跳稳定、有力、安静...', t: 80 },
      { part: '双手', tip: '收紧...保持...感受温暖...', t: 95 },
      { part: '面部', tip: '眉头、眼眶、下颌全部松开...', t: 115 },
      { part: '全身', tip: '被温暖的光包裹...', t: 135 },
      { part: '入睡', tip: '晚安...🌙', t: 160 },
    ]

    // 清除旧计时器
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)

    let seqIdx = 0
    const tick = () => {
      if (seqIdx >= sequence.length) {
        clearInterval(this.data.pmrTimer)
        return
      }
      const item = sequence[seqIdx]
      this.setData({ pmrCurrentPart: item.part, pmrTip: item.tip })
      seqIdx++
    }
    tick()
    const timer = setInterval(tick, 18000) // 每 18 秒切换一个部位
    this.setData({ pmrTimer: timer })
  },

  skipPMR() {
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)
    // 停止当前 TTS 播放
    innerAudioContext.stop()
    this.setData({ closureStep: 2 })
  },

  onPMRDone() {
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)
    this.setData({ _pmrActive: false })
    innerAudioContext.stop()
    this.setData({ closureStep: 2 })
    // 睡前留白：PMR 结束后 3 秒轻声"我还在"，再 3 秒淡出
    setTimeout(() => {
      this._fallbackTTS('我还在', false, 70, 0.35)
    }, 3000)
    this._autoCloseTimer = setTimeout(() => this._autoCloseCeremony(), 6000)
  },

  // PMR TTS 播完自动调用
  onPMRAutoDone() {
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)
    this.setData({ closureStep: 2 })
    // 睡前留白
    setTimeout(() => {
      this._fallbackTTS('我还在', false, 70, 0.35)
    }, 3000)
    this._autoCloseTimer = setTimeout(() => this._autoCloseCeremony(), 6000)
  },

  // 自动关闭仪式（屏幕渐暗）→ 问是否继续聊
  _autoCloseCeremony() {
    this.setData({ _dimming: true })
    setTimeout(() => {
      this.setData({ showClosure: false, closureStep: 1, _dimming: false })
      // PMR 结束后询问是否继续聊
      this._askContinueAfterClosure()
    }, 2000)
  },

  _askContinueAfterClosure() {
    wx.showModal({
      title: '还想说几句吗？',
      content: '关上灯，躺着聊几句，然后安心睡。',
      confirmText: '再说几句',
      cancelText: '不用了，晚安',
      success: (res) => {
        if (res.confirm) {
          // 切换到文字模式，继续聊
          this.setData({
            mode: 'text',
            sleepModeActive: false,
            statusText: '聆听中',
            statusHint: '还有什么想说？'
          })
        } else {
          // 用户说晚安，清理
          this.setData({
            messages: [],
            conversationLog: [],
            conversationRound: 0
          })
          wx.removeStorageSync('chat_history')
          wx.showToast({ title: '晚安 🌙', icon: 'none', duration: 2000 })
        }
      }
    })
  },

  // 语音跳过：当前阶段直接进下一阶段
  _handleVoiceSkip() {
    const step = this.data.closureStep
    if (step === 1) {
      // Step 1: bedtime setting - skip goes to step 2 or 3
      if (this.data.showWorryPrompt || this.data.worryPendingText) {
        this.setData({ closureStep: 2 })
        if (this._step2Timer) clearTimeout(this._step2Timer)
        this._step2Timer = setTimeout(() => {
          if (this.data.closureStep === 2) {
            this.setData({ closureStep: 3 })
            setTimeout(() => this.startBreathingInClosure(), 500)
          }
        }, 2000)
      } else {
        this.setData({ closureStep: 3 })
        setTimeout(() => this.startBreathingInClosure(), 300)
      }
    } else if (step === 3) {
      // Step 3: PMR → 直接进入入睡确认
      this.onPMRDone()
    } else if (step === 2) {
      // Step 2: 担忧/晚安 → 立即关闭
      clearTimeout(this._autoCloseTimer)
      this._autoCloseCeremony()
    }
  },

  onGoBack() {
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)
    this.setData({ showClosure: false, closureStep: 1, conversationLog: [] })
  },

  // 关闭仪式中途返回对话
  backFromClosure() {
    if (this._autoCloseTimer) clearTimeout(this._autoCloseTimer)
    if (this._step2Timer) clearTimeout(this._step2Timer)
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)
    innerAudioContext.stop()
    this.setData({
      showClosure: false,
      closureStep: 1,
      mode: 'text',
      sleepModeActive: false,
      statusText: '聆听中',
      statusHint: '还有什么想说？',
      _dimming: false
    })
  },

  onComplete() {
    wx.showModal({
      title: '今晚感觉怎么样？',
      cancelText: '一般',
      confirmText: '好多了',
      success: res => {
        const score = res.confirm ? 5 : 3
        const today = new Date().toISOString().split('T')[0]
        wx.request({
          url: `${API}/api/v1/sleep/record`,
          method: 'POST',
          data: { user_id: app.globalData.userId || '', date: today, score }
        })
        this.setData({ showClosure: false, closureStep: 1, conversationLog: [], messages: [] })
        wx.removeStorageSync('chat_history')
      }
    })
  },

  // ================================================
  // 文字模式
  // ================================================
  stopProp() {},

  onQuickChip(e) {
    const text = e.currentTarget.dataset.text
    this.onUserMessage(text)
  },

  onInputChange(e) {
    this.setData({ inputText: e.detail.value })
  },

  onSendText() {
    const text = this.data.inputText.trim()
    if (!text) return
    this.setData({ inputText: '' })
    this.onUserMessage(text)
  },

  // 检查是否还能发送消息（试用期/非付费用户每日限制3次）
  canSendMessage(type = 'text') {
    const limit = this._getUsageLimit()
    const used = this._getUsedSeconds(type)
    const remaining = Math.max(0, limit[type] - used)
    return { canSend: remaining > 0, remaining, used, limit: limit[type] }
  },

  // 记录对话使用时长（文本模式每次约30秒）
  recordChatUsage(type = 'text', seconds = 30) {
    this._recordUsage(type, seconds)
  },

  async onUserMessage(text) {
    // 检查文本时长限制
    const check = this.canSendMessage('text')
    if (!check.canSend) {
      const period = this._getUsageLimit().period === 'month' ? '本月' : '今日'
      wx.showModal({
        title: `${period}文本时长已用完`,
        content: `免费版${period}文本对话限制已用完，升级 Pro 享更多时长`,
        confirmText: '升级 Pro',
        cancelText: '明天再来',
        success: (res) => {
          if (res.confirm) {
            wx.navigateTo({ url: '/pages/subscribe/subscribe' })
          }
        }
      })
      return
    }
    
    // 记录文本使用（每次约30秒）
    this.recordChatUsage('text', 30)
    
    // 统一走 CBT 流式 SSE（与语音模式一致）
    await this._sendToAI(text, false)
    this.saveChatHistory(this.data.messages)
  },

  onVoiceStart() {
    recorderManager.start({ format: 'mp3', sampleRate: 16000, numberOfChannels: 1, encodeBitRate: 48000, duration: 60000 })
    recorderManager.onStart(() => this.setData({ isRecording: true }))
  },

  onVoiceEnd() {
    if (!this.data.isRecording) return
    recorderManager.stop()
    recorderManager.onStop(res => {
      this.setData({ isRecording: false })
      // 记录语音使用时长
      if (res.duration >= 500) {
        this._recordUsage('voice', Math.ceil(res.duration / 1000))
      }
      if (res.duration >= 500) {
        // 腾讯云流式 ASR
        wx.uploadFile({
          url: `${API}/api/v1/asr/stream`,
          filePath: res.tempFilePath,
          name: 'file',
          success: res2 => {
            const json = JSON.parse(res2.data)
            const text = (json.text || '').trim()

            // 语音跳过指令（关闭仪式中）
            if (this.data.showClosure && text) {
              const skipWords = ['跳过', '跳过这个', '下一个', '继续', '下一', '不用了', '退出']
              if (skipWords.some(w => text.includes(w))) {
                this._handleVoiceSkip()
                return
              }
            }

            this.onUserMessage(text || '脑子停不下来')
          },
          fail: () => this.onUserMessage('脑子停不下来')
        })
      }
    })
  },

  // 用户反馈闭环 👍/👎
  async submitFeedback(e) {
    const { index, rating } = e.currentTarget.dataset
    const msg = this.data.messages[index]
    if (!msg || msg.role !== 'assistant') return
    // 本地标记
    this.setData({ [`messages[${index}].feedback`]: Number(rating) })
    // 发送给后端
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''
    try {
      wx.request({
        url: `${API}/api/v1/feedback`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: {
          user_id: userId,
          session_id: sessionId,
          message_id: msg.id || '',
          rating: Number(rating),
          turn_text: index > 0 ? (this.data.messages[index - 1]?.content || '') : '',
          response_text: msg.content || '',
        }
      })
    } catch (err) {
      console.error('[Feedback] submit error:', err)
    }
    // 2秒后显示"已反馈"
    setTimeout(() => {
      this.setData({ [`messages[${index}].feedback`]: 0 })
    }, 1500)
  },

  // 文字模式 TTS（流式版 - 腾讯云 2秒极速）
  async playAITTS(index) {
    const msg = this.data.messages[index]
    if (!msg) return
    if (this.data.isPlayingTTS) {
      innerAudioContext.stop()
      this.setData({ isPlayingTTS: false, ttsProgress: 0 })
      this.data.messages.forEach((m, i) => { if (m.isPlayingTTS) this.setData({ [`messages[${i}].isPlayingTTS`]: false }) })
      return
    }
    this.setData({ isPlayingTTS: true, currentPlayingIndex: index, [`messages[${index}].isPlayingTTS`]: true, ttsProgress: 0 })
    try {
      const res = await wx.request({
        url: `${API}/api/v1/tts/stream?text=${encodeURIComponent(msg.content.slice(0, 500))}&voice=female_warm&speed=90`,
        method: 'POST',
        responseType: 'arraybuffer'
      })
      if (res.statusCode === 200 && res.data) {
        const filePath = `${wx.env.USER_DATA_PATH}/tts_text_${Date.now()}.mp3`
        wx.getFileSystemManager().writeFile({
          filePath: filePath, data: res.data, encoding: 'binary',
          success: () => {
            innerAudioContext.src = filePath
            innerAudioContext.play()
            let step = 0
            this._textTtsTimer = setInterval(() => {
              step++
              this.setData({ ttsProgress: Math.min(Math.floor((step / 40) * 100), 100) })
              if (step >= 40) {
                clearInterval(this._textTtsTimer)
                this.setData({ isPlayingTTS: false, ttsProgress: 0, [`messages[${index}].isPlayingTTS`]: false })
              }
            }, 500)
          },
          fail: () => this.setData({ isPlayingTTS: false, [`messages[${index}].isPlayingTTS`]: false })
        })
      }
    } catch (e) {
      console.error('[TTS Error]', e)
      this.setData({ isPlayingTTS: false, [`messages[${index}].isPlayingTTS`]: false })
    }
  },

  // ================================================
  // 白噪音（从后端 /stream 获取，写入本地后播放）
  // ================================================
  playSound(e) {
    const soundId = e.currentTarget.dataset.id
    if (this.data.currentSound === soundId) {
      innerAudioContext.stop()
      this.setData({ currentSound: null })
      return
    }
    wx.request({
      url: `${API}/api/v1/sounds/${soundId}/stream`,
      method: 'GET',
      responseType: 'arraybuffer',
      success: (res) => {
        if (res.statusCode === 200 && res.data) {
          const fs = wx.getFileSystemManager()
          const filePath = `${wx.env.USER_DATA_PATH}/sound_${soundId}.mp3`
          fs.writeFile({
            filePath,
            data: res.data,
            encoding: 'binary',
            success: () => {
              innerAudioContext.stop()
              // 清理 TTS 遗留的回调，避免干扰白噪声
              try { innerAudioContext.offError && innerAudioContext.offError() } catch(e){}
              try { innerAudioContext.offEnded && innerAudioContext.offEnded() } catch(e){}
              innerAudioContext.src = filePath
              innerAudioContext.loop = true
              innerAudioContext.volume = 0.6
              innerAudioContext.play()
              this.setData({ currentSound: soundId })
            },
            fail: (err) => {
              console.error('[Sound] write failed:', err)
              wx.showToast({ title: '音频加载失败', icon: 'none' })
            }
          })
        } else {
          console.error('[Sound] bad response:', res.statusCode)
          wx.showToast({ title: '音频获取失败', icon: 'none' })
        }
      },
      fail: (err) => {
        console.error('[Sound] request failed:', err)
        wx.showToast({ title: '网络错误', icon: 'none' })
      }
    })
  },

  // ================================================
  // 工具
  // ================================================
  _now() {
    return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
  },
  saveChatHistory(msgs) { wx.setStorageSync('chat_history', msgs.slice(-20)) },

  // ================================================
  // 担忧捕获（CBT 担忧写下来）
  // ================================================

  // 用户点击「说出来，我帮你记」→ 开始担忧录音
  startWorryCapture() {
    if (this.data.worryCaptureTimer) clearTimeout(this.data.worryCaptureTimer)
    this.setData({ showWorryPrompt: false, worryCaptureActive: true })

    // 启动 ASR 录音
    recorderManager.start({
      format: 'mp3',
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 48000,
      duration: 60000
    })
    recorderManager.onStart(() => this.setData({ isRecording: true, statusText: '正在听你说...', statusHint: '说出来，不清楚也没关系' }))
    recorderManager.onStop(res => {
      this.setData({ isRecording: false })
      if (res.duration >= 500) {
        wx.uploadFile({
          url: `${API}/api/v1/asr`,
          filePath: res.tempFilePath,
          name: 'file',
          success: uploadRes => {
            const json = JSON.parse(uploadRes.data)
            const worryText = json.text || this.data.worryPendingText || '未识别'
            this.saveWorry(worryText)
          },
          fail: () => {
            // ASR 失败，用已录制的 pending text
            this.saveWorry(this.data.worryPendingText || '未识别')
          }
        })
      } else {
        this.setData({ worryCaptureActive: false })
      }
    })
  },

  // 担忧保存到后端 + AI 确认
  async saveWorry(worryText) {
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''

    // 存后端
    try {
      await wx.request({
        url: `${API}/api/v1/worry`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: { user_id: userId, worry_text: worryText, session_id: sessionId }
      })
    } catch (e) {
      console.error('[SaveWorry Error]', e)
    }

    // AI 确认（通过 MiniMax TTS）
    const confirmText = `我记下了："${worryText.slice(0, 50)}"。明天17:00，我们再一起看看。现在，把这件事交给我，安心睡吧。晚安🌙`

    const newLog = [...this.data.conversationLog, { role: 'assistant', text: confirmText }]
    this.setData({
      conversationLog: newLog,
      worryCaptureActive: false,
      worryPendingText: '',
      showWorryPrompt: false,
    })
    // 播放确认 TTS
    this._playTTS(confirmText, true)

    // ─── 担忧捕获完成 → 立即进入关闭仪式 ───
    setTimeout(() => this.triggerClosure(), 3000)
  },

  // 忽略担忧提示
  dismissWorryPrompt() {
    if (this.data.worryCaptureTimer) clearTimeout(this.data.worryCaptureTimer)
    this.setData({ showWorryPrompt: false, worryCaptureActive: false })
    // 停止可能正在播放的 TTS
    innerAudioContext.stop()
    // 立即进入关闭仪式（用户说不用了 = 想要睡了）
    setTimeout(() => this.triggerClosure(), 500)
  },

  // ================================================
  // 生命周期
  // ================================================
  onLoad() {
    innerAudioContext.onEnded(() => {
      this.setData({ isPlayingTTS: false, ttsProgress: 0 })
      if (this._textTtsTimer) clearInterval(this._textTtsTimer)
      
      // 睡眠模式：TTS 播完后重新开始监听（仅当音频队列空时）
      if (this.data.sleepModeActive && !this.data._pmrActive && (this.data.ttsQueue || []).length === 0) {
        this.setData({ statusText: '聆听中', statusHint: '手机放在枕边，继续说吧' })
        setTimeout(() => this._startVADLoop(), 500)
      }
      
      // PMR 完成
      if (this.data._pmrActive) {
        this.data._pmrActive = false
        this.onPMRAutoDone()
      }
    })

    // 检查订阅状态
    const sub = wx.getStorageSync('subscription') || {}
    if (sub.isPremium && sub.expireDate) {
      this.setData({ isPremium: true })
    }

    // 首次加载历史记录（仅一次）
    this._historyLoaded = false
    this._loadChatHistory()

    // 处理「重新审视担忧」跳转
    const revisitText = wx.getStorageSync('revisit_worry_text')
    if (revisitText) {
      wx.removeStorageSync('revisit_worry_text')
      // 延迟发消息，等页面加载完成
      setTimeout(() => {
        this.onUserMessage(`重新审视：${revisitText}`)
      }, 500)
    }
    this._registerRecorderEvents()
  },


  _registerRecorderEvents() {
    // 避免重复注册
    if (this._recorderEventsRegistered) return
    this._recorderEventsRegistered = true

    recorderManager.onStop((res) => {
      const state = this._recordingState
      if (!this.data.sleepModeActive) return

      if (state === 'vad') {
        const hasSound = res.fileSize > 3500
        console.log('[_VAD] onStop, fileSize:', res.fileSize, 'hasSound:', hasSound)
        const level = hasSound ? Math.floor(Math.random() * 6) + 6 : Math.floor(Math.random() * 4)
        this.setData({ audioLevel: level })

        // 入睡检测：累加安静时间
        if (!hasSound && !this.data.isSleepFadingOut) {
          const newQuietMs = this.data.sleepDetectionQuietMs + 1200
          this.setData({ sleepDetectionQuietMs: newQuietMs })
          if (newQuietMs >= this.SLEEP_DETECTION_THRESHOLD_MS) {
            console.log('[Sleep] detected, triggering fade out')
            this._triggerSleepFadeOut()
            return
          }
        } else {
          this.setData({ sleepDetectionQuietMs: 0 })
        }

        if (hasSound && !this.data.isRecording) {
          this._vadActive = false
          this._start正式录音()
        } else if (this.data.sleepModeActive) {
          this._listenTimer = setTimeout(() => this._startVADLoop(), 50)
        }
        return
      }

      if (state === 'asr') {
        console.log('[ASR-WS] onStop state=asr, duration:', res.duration, 'fileSize:', res.fileSize)
        if (res.duration < VAD.MIN_UTTERANCE) {
          this.setData({ isRecording: false, audioLevel: 0 })
          if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null }
          this._startVADLoop()
          return
        }
        this._recordUsage('voice', Math.ceil(res.duration / 1000))
        this._recordingFilePath = res.tempFilePath
        this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
        console.log('[ASR-WS] onStop, socketReady:', this._asrSocketReady, 'fallback:', this._fallbackUploadASR)
        if (this._asrSocket && this._asrSocketReady) {
          console.log('[ASR-WS] sending end marker')
          this._asrSocket.send({ data: JSON.stringify({ type: 'end' }) })
        } else if (this._fallbackUploadASR && res.tempFilePath) {
          console.log('[ASR-WS] fallback to uploadFile')
          this._sendVoiceToASR(res.tempFilePath)
        } else {
          console.log('[ASR-WS] no action, skip')
        }
      }
    })

    recorderManager.onError((err) => {
      console.error('[Recorder Error]', err)
      if (this.data.sleepModeActive) {
        this.setData({ isRecording: false, audioLevel: 0 })
        if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null }
        this._recordingState = ''
        this._startVADLoop()
      }
    })

    recorderManager.onFrameRecorded((res) => {
      if (this._recordingState !== 'asr') return
      console.log('[ASR-FE] onFrameRecorded, frameSize:', res.frameBuffer.byteLength, 'isLastFrame:', res.isLastFrame)
      if (this._asrSocket && this._asrSocketReady) {
        this._asrSocket.send({ data: res.frameBuffer })
      }
      const volume = this._calcPCMVolume(res.frameBuffer)
      if (volume > 0.012) {
        if (this._silenceTimer) clearTimeout(this._silenceTimer)
        this._silenceTimer = setTimeout(() => {
          if (this.data.sleepModeActive && this.data.isRecording) {
            this._stop正式录音()
          }
        }, VAD.SPEECH_TIMEOUT)
      }
    })
  },

  _calcPCMVolume(arrayBuffer) {
    const dataView = new DataView(arrayBuffer)
    let sum = 0
    const len = dataView.byteLength
    if (len === 0) return 0
    for (let i = 0; i < len; i += 2) {
      sum += Math.abs(dataView.getInt16(i, true))
    }
    return (sum / (len / 2)) / 32768
  },

  onShow() {
    // 检查隐私协议
    if (!wx.getStorageSync('privacy_agreed')) {
      this.setData({ showPrivacyModal: true })
    }
    // 更新剩余对话次数显示
    this._updateFreeChatsDisplay()
    // 拉取后端真实配额
    this._fetchUsage()
    // 页面从后台返回时，若睡眠模式仍标记为开启，自动恢复 VAD 循环
    if (this.data.sleepModeActive && !this.data.isListening && !this.data.isRecording && !this.data.isPlayingTTS) {
      console.log('[onShow] 恢复睡眠模式 VAD')
      this._startVADLoop()
    }
    // 加载关系开场白（只在文字模式且消息为空时）
    if (this.data.mode === 'text' && this.data.messages.length === 0) {
      this._loadSessionSummary()
    }
  },

  _loadSessionSummary() {
    const userId = app.globalData.userId || ''
    if (!userId) return
    wx.request({
      url: `${API}/api/v1/session/summary?user_id=${encodeURIComponent(userId)}`,
      method: 'GET',
      timeout: 5000,
      success: (res) => {
        if (res.statusCode === 200 && res.data) {
          const { session_count, greeting, has_relation, memory_check } = res.data
          // 有历史 session 且当前消息列表为空时，显示关系开场白
          if (session_count > 0 && this.data.messages.length === 0) {
            const welcomeMsgs = [{
              id: 'welcome_' + Date.now(),
              role: 'assistant',
              content: greeting,
              time: this._now(),
              isPlayingTTS: false,
              showFeedback: false
            }]
            // 关系深化：≥3次会话后追加"还记得吗"
            if (has_relation && memory_check) {
              welcomeMsgs.push({
                id: 'memory_' + Date.now(),
                role: 'assistant',
                content: memory_check,
                time: this._now(),
                isPlayingTTS: false,
                showFeedback: false,
                isMemoryCheck: true
              })
            }
            this.setData({ messages: welcomeMsgs })
            console.log('[SessionSummary] count:', session_count, 'greeting:', greeting, 'memory:', memory_check)
          }
        }
      },
      fail: (err) => {
        console.log('[SessionSummary] load failed:', err)
      }
    })
  },

  async _loadChatHistory() {
    // 已加载过或已有消息时不覆盖
    if (this._historyLoaded || this.data.messages.length > 0) return
    this._historyLoaded = true
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''
    try {
      const res = await wx.request({
        url: `${API}/api/v1/chat/history?user_id=${encodeURIComponent(userId)}&session_id=${encodeURIComponent(sessionId)}`,
        method: 'GET',
        timeout: 8000
      })
      if (res.statusCode === 200 && res.data && res.data.history && res.data.history.length > 0) {
        // 再次检查，避免请求返回前用户已发送消息导致竞态覆盖
        if (this.data.messages.length > 0) return
        const history = res.data.history
        const messages = history.map((m, idx) => ({
          id: Date.now() - history.length + idx,
          role: m.role,
          content: m.content,
          time: this._now(),
          isPlayingTTS: false
        }))
        const conversationLog = history.map(m => ({
          role: m.role,
          text: m.content
        }))
        this.setData({ messages, conversationLog })
        wx.setStorageSync('chat_history', messages.slice(-20))
        return
      }
    } catch (e) {
      console.error('[LoadHistory Error]', e)
    }
    // 失败或空记录：回退本地（同样检查竞态）
    if (this.data.messages.length > 0) return
    const h = wx.getStorageSync('chat_history') || []
    if (h.length > 0) this.setData({ messages: h })
  },

  async _fetchUsage() {
    const userId = app.globalData.userId || ''
    try {
      const res = await wx.request({
        url: `${API}/api/v1/usage/${userId}`,
        method: 'GET',
        timeout: 8000
      })
      if (res.statusCode === 200 && res.data) {
        this.setData({ usageQuota: res.data })
      }
    } catch (e) {
      console.error('[FetchUsage Error]', e)
    }
  },

  resetSession() {
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''
    wx.showModal({
      title: '重置会话',
      content: '确定要清空今晚的聊天并重新开始吗？',
      confirmText: '重置',
      cancelText: '取消',
      success: (res) => {
        if (res.confirm) {
          wx.request({
            url: `${API}/api/v1/chat/cbt/reset`,
            method: 'POST',
            header: { 'Content-Type': 'application/json' },
            data: { user_id: userId, session_id: sessionId },
            success: () => {
              this.setData({ messages: [], conversationLog: [], conversationRound: 0 })
              wx.removeStorageSync('chat_history')
              wx.showToast({ title: '已重置', icon: 'success' })
            },
            fail: () => {
              wx.showToast({ title: '重置失败', icon: 'none' })
            }
          })
        }
      }
    })
  },

  onHide() { this.stopAll() },
  onUnload() {
    this.stopAll()
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)
    if (this._textTtsTimer) clearInterval(this._textTtsTimer)
    if (this._companionTimer) clearTimeout(this._companionTimer)
  }
})
