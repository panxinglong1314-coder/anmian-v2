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
  SPEECH_TIMEOUT: 1200,  // 静音 1200ms 停止录音（用户停顿即结束）
  MIN_UTTERANCE: 400,    // 最少录音 400ms
}

// ─── 录音状态机 ─────────────────────────────────────────────
// _recordingState: null | 'vad' | 'asr'
// _recordingActive: bool — 录音机硬件忙闲标志，防止并发 start()
//
// 状态转换路径（严格）：
//   null ──(start)──→ 'vad' ──(hasSound)──→ 'asr' ──(stop)──→ null
//                         ↑                          │
//                         └────(noSound, 50ms)───────┘

//
// Bug 修复对照：
//   Bug 1: _stop正式录音 未清 _recordingState   → 统一在 stop 前清状态
//   Bug 2: onStop 里 VAD 分支直接 start()           → 改为 _startVADLoop，由状态机管理
//   Bug 3: onShow 无互斥直接调 _startVADLoop()       → 加 _recordingState===null 前置检查
//   Bug 4: _start正式录音 无互斥                    → 加 _recordingState!=='vad' 前置检查
//   新增:  无超时保护 → 所有异步操作加 setTimeout 超时兜底
//

Page({
  data: {
    mode: 'sleep',
    // ✅ 预读 subscription，避免 banner 异步消失导致布局闪烁
    isPremium: (() => {
      try {
        const sub = wx.getStorageSync('subscription') || {}
        return !!(sub.isPremium && sub.expireDate && new Date(sub.expireDate) > new Date())
      } catch (e) { return false }
    })(),

    // 睡眠模式
    sleepModeActive: false,
    _asrPending: false,  // 防重复 ASR 发送
    isListening: false,
    isRecording: false,
    audioLevel: 0,

    // CBT 阶段进度
    cbtPhase: '',
    cbtPhaseLabel: '',
    cbtPhaseHint: '',
    showCbtPhase: false,
    statusText: '准备入睡',
    statusHint: '点击下方按钮，将手机放在枕边',
    conversationLog: [],
    isAIResponding: false,

    // 文字模式
    isLoading: false,
    messages: [],
    scrollToMsg: '',
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

    // 刺激控制提醒
    showStimulusCard: false,  // 是否显示刺激控制提醒卡片
    stimulusCardMessage: '',   // 卡片提示语

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

  // 刺激控制提醒常量
  STIMULUS_CONTROL_MS: 20 * 60 * 1000,  // 躺床超过20分钟未入睡触发提醒
  _stimulusControlTimer: null,
  _stimulusControlShown: false,
  _sessionStartTime: null,  // 对话开始时间（用于计时）,

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
      // ✅ 睡眠→文本：保留 conversationLog，同步转换为 messages 格式
      const msgs = this.data.conversationLog.map((m, i) => ({
        id: m.id || `hist_${i}`,
        role: m.role,
        content: m.text || m.content || '',
        time: this._now(),
        isPlayingTTS: false,
        feedback: undefined,
      }))
      this.setData({ mode: 'text', messages: msgs }, () => {
        // 进入文本模式也启动刺激控制计时器
        this._resetStimulusControlTimer()
      })
    } else {
      this.stopAll()
      // ✅ 文本→睡眠：保留 conversationLog 和 conversationRound，不清空历史
      this.setData({ mode: 'sleep' })
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
    // 【优化】用户点了"同意"→隐私同意立即写入，然后触发微信隐私协议+麦克风两步授权
    wx.setStorageSync('privacy_agreed', true)
    this.setData({ showPrivacyModal: false })
    this._requestRecordAuthWithPrivacyAgree()
  },

  // 【优化】隐私同意后请求微信隐私协议+麦克风授权
  // - getPrivacySetting 检查是否需要微信隐私弹窗
  // - 若需要：requirePrivacyAuthorize（用户看到微信隐私协议弹窗）
  // - 然后 authorize scope.record（用户看到麦克风弹窗）
  // - 麦克风授权成功 → 进入睡眠模式
  // - 麦克风拒绝 → 进入文字模式（隐私已同意，下次不再弹隐私）
  _requestRecordAuthWithPrivacyAgree() {
    const doRecordAuth = () => {
      wx.authorize({
        scope: 'scope.record',
        success: () => {
          console.log('[Privacy+Auth] 麦克风授权成功，直接进入睡眠模式')
          this._doEnterSleepMode()
        },
        fail: () => {
          console.log('[Privacy+Auth] 麦克风拒绝 → 进入文字模式')
          this.setData({ mode: 'text' }, () => {
            // 进入文本模式，启动刺激控制计时器
            this._resetStimulusControlTimer()
          })
          wx.showToast({ title: '已切换文字模式，可随时在设置中开启语音', icon: 'none', duration: 3000 })
        }
      })
    }

    if (!wx.getPrivacySetting) {
      // 低版本微信，无隐私协议API → 直接请求麦克风授权
      doRecordAuth()
      return
    }
    wx.getPrivacySetting({
      success: (res) => {
        if (res.needAuthorization) {
          // 需要微信隐私协议弹窗（用户必须点"同意"才能继续）
          wx.requirePrivacyAuthorize({
            success: () => {
              // 隐私协议同意后 → 请求麦克风授权
              doRecordAuth()
            },
            fail: () => {
              // 用户拒绝隐私协议 → 隐私未同意，回到隐私弹窗
              wx.setStorageSync('privacy_agreed', false)
              this.setData({ showPrivacyModal: true })
            }
          })
        } else {
          // 不需要微信隐私协议弹窗 → 直接请求麦克风授权
          doRecordAuth()
        }
      },
      fail: () => {
        // getPrivacySetting 失败 → 走麦克风授权尝试
        doRecordAuth()
      }
    })
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
    // 【优化】隐私未同意时：直接弹隐私卡，一次性处理隐私+麦克风
    if (!wx.getStorageSync('privacy_agreed')) {
      this.setData({ showPrivacyModal: true })
      return
    }
    // 隐私已同意 → 直接进入睡眠模式（record 权限在同意时已一起处理）
    this._doEnterSleepMode()
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
      // 启动刺激控制计时器
      this._resetStimulusControlTimer()
    })
  },

  exitSleepMode() {
    this._vadActive = false
    this.stopListening()
    this.stopAll()
    if (this._companionTimer) clearTimeout(this._companionTimer)
    if (this._stimulusControlTimer) clearTimeout(this._stimulusControlTimer)
    try { innerAudioContext.volume = 0 } catch (e) {}
    this.setData({
      sleepModeActive: false, isListening: false,
      isRecording: false, audioLevel: 0,
      statusText: '准备入睡',
      statusHint: '点击下方按钮，将手机放在枕边',
      sleepDetectionQuietMs: 0,
      isSleepFadingOut: false,
      companionLevel: 0,
      showStimulusCard: false,
      showCbtPhase: false,
    })
  },

  _startVADLoop() {
    console.log('[_VAD] start, sleepModeActive:', this.data.sleepModeActive, 'mode:', this.data.mode, 'state=', this._recordingState, 'locked=', this._recorderLocked)
    if (!this.data.sleepModeActive) return
    // ✅【关键互斥】如果状态机已经在 vad 或 asr，说明上一轮还没结束，绝对不能再 start()
    // 这是防止 "audio is recording, don't start record again" 错误的根本保护
    if (this._recordingState === 'vad' || this._recordingState === 'asr') {
      console.warn('[_VAD] state machine busy (' + this._recordingState + '), skip duplicate start')
      return
    }
    // ✅ 如果录音机正在停止，直接返回，等 onStop 后再启动
    if (this._recorderStopping) {
      console.warn('[_VAD] recorder is stopping, defer start')
      return
    }
    // ✅ TTS 播放时注册回调，等 TTS 真正结束后再启动（避免轮询 retry 污染 warmup）
    if (this._ttsStreamPlaying || this._ttsPlaying || this.data.isPlayingTTS) {
      console.log('[_VAD] TTS playing, register onTTSEnd callback')
      this._onTTSEnd(() => {
        this._vadRestartPending = false  // ✅ 清锁
        console.log('[_VAD] TTS ended callback fired, starting VAD')
        this._doStartVAD()
      })
      return
    }
    // ✅ 单例锁：防止多个 VAD 循环并发
    if (this._vadLoopActive) {
      console.warn('[_VAD] loop already active, skip')
      return
    }
    this._vadLoopActive = true
    this._vadRetryCount = 0
    this._vadRestartPending = false  // ✅ 清锁
    this._doStartVAD()
  },

  _restartVAD(reason) {
    if (this._vadRestartPending) {
      console.warn('[VAD] restart already pending, skip (' + reason + ')')
      return
    }
    this._vadRestartPending = true
    console.log('[VAD] restart scheduled:', reason)
    this._startVADLoop()
  },

  _onTTSEnd(cb) {
    if (!this._ttsEndCallbacks) this._ttsEndCallbacks = []
    this._ttsEndCallbacks.push(cb)
  },

  _fireTTSEndCallbacks() {
    const cbs = (this._ttsEndCallbacks || []).splice(0)
    cbs.forEach(cb => {
      try { cb() } catch (e) { console.error('[TTS] end callback error:', e) }
    })
  },

  // ✅ TTS 回声检测：ASR 识别到 TTS 内容时判定为回声
  _isTTSEcho(asrText) {
    if (!asrText || !this._lastTTSText) return false
    const clean = (s) => s.replace(/[，。？！,\.\?!\s]/g, '')
    const a = clean(asrText)
    const t = clean(this._lastTTSText)
    if (!a || !t) return false
    // 如果 ASR 文本被 TTS 文本包含，或重合度 > 50%，判定为回声
    if (t.includes(a)) return true
    // 简单的最长公共子串近似：看短文本有多少字符在长文本中
    let common = 0
    const short = a.length < t.length ? a : t
    const long = a.length < t.length ? t : a
    for (let i = 0; i < short.length; i++) {
      if (long.indexOf(short[i]) !== -1) common++
    }
    return common / short.length > 0.5
  },

  _doStartVAD() {
    const VAD_MAX_RETRIES = 6
    // ✅ 如果录音机正在停止，延迟重试，避免与 stop() 竞态
    if (this._recorderStopping) {
      console.log('[_VAD] recorder stopping, defer start')
      if (this._listenTimer) clearTimeout(this._listenTimer)
      this._listenTimer = setTimeout(() => this._doStartVAD(), 600)
      return
    }
    // ✅ 二次保险：TTS 还在播则注册回调并返回（等 onEnded 再启动）
    if (this._ttsStreamPlaying || this._ttsPlaying || this.data.isPlayingTTS) {
      console.log('[_VAD] TTS still playing, register onTTSEnd callback')
      this._vadLoopActive = false
      this._onTTSEnd(() => {
        this._vadRestartPending = false  // ✅ 清锁
        console.log('[_VAD] TTS ended callback fired (from _doStartVAD), starting VAD')
        this._doStartVAD()
      })
      return
    }
    // ✅ 用底层锁判断录音机是否真正空闲（onStart/onStop/onError 驱动）
    if (this._recorderLocked) {
      this._vadRetryCount++
      if (this._vadRetryCount >= VAD_MAX_RETRIES) {
        console.error('[_VAD] max retries reached, force reset recorder')
        this._forceResetRecorder()
        return
      }
      console.warn('[_VAD] recorder locked, retry ' + this._vadRetryCount + '/' + VAD_MAX_RETRIES)
      if (this._listenTimer) clearTimeout(this._listenTimer)
      this._listenTimer = setTimeout(() => this._doStartVAD(), 500)
      return
    }
    // 真正启动 VAD
    this._recorderLocked = true
    this._recordingActive = true
    this._vadActive = true
    this._recordingState = 'vad'
    this._recorderStopping = false  // 安全起见重置
    this.setData({ isListening: true })
    console.log('[_VAD] calling recorderManager.start()')
    recorderManager.start({
      format: 'mp3', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 48000, duration: 1200
    })
  },

  _forceResetRecorder() {
    console.warn('[Recorder] force reset, stopping all')
    if (this._listenTimer) clearTimeout(this._listenTimer)  // ✅ 取消旧重试定时器
    this._vadLoopActive = false
    this._recorderLocked = false
    this._recorderStopping = false  // ✅ 重置停止标志
    this._vadRetryCount = 0
    try { recorderManager.stop() } catch (e) {}
    // 等待 1s 让系统彻底释放麦克风，然后重启 VAD
    setTimeout(() => {
      console.log('[Recorder] reset done, restart VAD')
      if (this.data.sleepModeActive) this._restartVAD('force reset')
    }, 1000)
  },

  _start正式录音() {
    if (this._formalRecordingStarting) {
      console.warn('[_正式录音] already starting, skip')
      return
    }
    if (this._recordingState === 'asr') {
      console.log('[_正式录音] 已在录音，跳过')
      return
    }
    this._formalRecordingStarting = true
    if (this._listenTimer) clearTimeout(this._listenTimer)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    if (this._asrFinalSilenceTimer) { clearTimeout(this._asrFinalSilenceTimer); this._asrFinalSilenceTimer = null }
    // 用户开始说话，重置陪伴计时器 + 打断 TTS
    this._resetCompanionTimer()
    this._clearTTSQueue()
    this._vadActive = false
    // Bug 4 保护：必须在 vad 状态才能切换到 asr
    if (this._recordingState !== 'vad') {
      console.warn('[_正式录音] 当前状态', this._recordingState, '，无法启动正式录音')
      return
    }
    try { recorderManager.stop() } catch (e) {}
    this.setData({ isRecording: true, isListening: false, audioLevel: 8, statusText: '正在听...', statusHint: '说完后稍等，我会回应' })
    // ✅ 丢弃前 N 帧 warmup：VAD 停止后麦克风残留气流/环境音，前 8 帧（≈320ms）是噪音
    this._warmupFrames = 0
    this._warmupRMSList = []   // 收集所有 warmup 帧的 RMS
    this._noiseBaseline = 0    // 背景噪音 RMS 基线
    this._voiceDetected = false  // 是否已检测到真实人声

    // 建立后端 WebSocket 中转（后端→腾讯云 ASR v2）
    this._fallbackUploadASR = false
    this._wsEverOpened = false      // ✅ WS 是否曾经成功建立
    this._aiRequestSent = false     // ✅ AI 是否已经发送过（防止重复请求）
    this._pendingRestartVAD = false // ✅ Fix 1: 重置 pending 标记
    this._wsReceivedDone = false    // ✅ Fix 2: 重置 done 标记
    const wsUrl = `${API.replace(/^http/, 'ws')}/api/v1/asr/ws`
    this._asrSocket = wx.connectSocket({ url: wsUrl })
    this._asrSocketReady = false

    this._asrSocket.onOpen(() => {
      this._wsEverOpened = true
      this._asrSocketReady = true
      console.log('[ASR-WS] socket open, isRecording now:', this.data.isRecording, '_pendingRecordingFile:', this._pendingRecordingFile)
      // ✅ WebSocket 就绪后，刷出积压的音频帧
      if (this._frameBuffer && this._frameBuffer.length > 0) {
        console.log('[ASR-WS] flushing buffered frames:', this._frameBuffer.length)
        this._frameBuffer.forEach(buf => {
          if (this._asrSocket) this._asrSocket.send({ data: buf })
        })
        this._frameBuffer = []
      }
    })

    this._asrSocket.onMessage((res) => {
      console.log('[ASR-WS] onMessage raw:', res.data)
      try {
        const data = JSON.parse(res.data)
        if (data.error) {
          console.error('[ASR-WS] server error:', data.error)
          this._fallbackUploadASR = true
          this.setData({ _asrPending: false })
          return
        }
        if (data.done) {
          console.log('[ASR-WS] done signal received')
          this._wsReceivedDone = true  // ✅ Fix 2: 标记 WS 已结束，停止帧缓冲
          // ✅ 不立即关闭 WS，等 onStop 发完 end marker 后再关
          return
        }
        const text = data.text || ''
        const slice_type = data.slice_type != null ? data.slice_type : 0
        const is_final = data.is_final != null ? data.is_final : false
        console.log('[ASR-WS] result: text="%s" slice=%s is_final=%s', text, slice_type, is_final)

        // 实时展示中间结果（边说边看到文字）
        if (slice_type === 1 && text) {
          if (this.data.isRecording) {
            this.setData({ statusText: '正在识别...', statusHint: text })
          }
          // ✅ 收到中间结果说明用户还在说，重置 final 后的延迟停止定时器
          if (this._asrFinalSilenceTimer) {
            clearTimeout(this._asrFinalSilenceTimer)
            this._asrFinalSilenceTimer = null
          }
        }

        if (is_final || slice_type === 2) {
          // ✅ 空结果过滤：空文本时不触发 AI，直接重启 VAD
          if (!text || text.trim() === '') {
            console.warn('[ASR-WS] empty result, restart VAD')
            if (this._recordingState === 'asr') {
              this._pendingRestartVAD = true  // ✅ Fix 1: 标记 onStop 后重启
              this._stop正式录音()
            }
            return
          }
          // ✅ 噪音词过滤：纯语气词/幻听不触发 AI
          const NOISE_WORDS = new Set(['嗯', '嗯。', '啊', '啊。', '呃', '呃。', '哦', '哦。', '嗯嗯', '嗯嗯。', '唉', '唉。', '哎', '哎。', '哈', '哈。'])
          const cleanText = text.replace(/[。！？.!?\s]/g, '')
          if (cleanText.length <= 1 || NOISE_WORDS.has(text.trim())) {
            console.warn('[ASR-WS] noise word filtered:', text)
            if (this._recordingState === 'asr') {
              this._pendingRestartVAD = true  // ✅ Fix 1: 标记 onStop 后重启
              this._stop正式录音()
            }
            return
          }
          // ✅ 去重保护：避免重复触发 AI
          if (text === this._lastASRFinalText) {
            console.warn('[ASR-WS] duplicate final result, ignored:', text)
            if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null }
            this._asrSocketReady = false
            this.setData({ _asrPending: false })
            return
          }
          this._lastASRFinalText = text
          // ✅ 防止重复请求：如果 AI 已经发送过，跳过
          if (this._aiRequestSent) {
            console.warn('[ASR-WS] AI already sent, skip duplicate')
            return
          }
          // ✅ TTS 回声过滤：ASR 识别到 TTS 内容时跳过
          const asrText = text.trim()
          if (this._isTTSEcho(asrText)) {
            console.warn('[ASR-WS] TTS echo detected, skip:', asrText)
            return
          }
          this._aiRequestSent = true
          // ✅ 收到 final 后延迟 500ms 停止录音（配合服务端 VAD needvad=1）
          if (this._asrFinalSilenceTimer) clearTimeout(this._asrFinalSilenceTimer)
          this._asrFinalSilenceTimer = setTimeout(() => {
            console.log('[ASR-WS] silence after final, stopping recording')
            if (this.data.isRecording) {
              this._stop正式录音()
            }
          }, 500)
          // 立即触发 AI（不等录音停止）
          this.setData({ _asrPending: false })
          this._sendToAI(asrText, true)
        }
      } catch (e) {
        console.error('[ASR-WS] parse error:', e)
      }
    })

    this._asrSocket.onError((err) => {
      console.error('[ASR-WS] socket error:', JSON.stringify(err), 'errMsg:', err && err.errMsg)
      this._fallbackUploadASR = true
      this.setData({ _asrPending: false })
      if (err && err.errMsg && err.errMsg.includes('url not in domain list')) {
        wx.showToast({ title: '请在开发者工具「详情」中勾选「不校验合法域名」', icon: 'none', duration: 3000 })
      }
    })

    this._asrSocket.onClose(() => {
      this._asrSocketReady = false
      this._asrSocket = null
    })

    // 开始正式录音（PCM 流式，用于实时 ASR）
    this._frameBuffer = []  // ✅ 帧缓冲队列（WebSocket 未就绪时积压）
    this._recordingState = 'asr'
    this._enableFrameRecord = true  // onFrameRecorded 启用，实时推送音频帧
    // 清除 VAD 残留的 silenceTimer，防止 ASR 开始后误触发停止
    if (this._silenceTimer) { clearTimeout(this._silenceTimer); this._silenceTimer = null }
    if (this._volumeSim) clearInterval(this._volumeSim)
    // Bug 修复：先设状态再 start()，防止 onStop 先触发导致状态错误
    this._recorderStopping = false  // ✅ 安全重置，确保 start() 不被拦截
    recorderManager.start({
      format: 'pcm', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 48000,
      duration: 60000,
      enableFrameRecord: true,  // ✅ 启用实时帧回调
      frameSize: 1              // ✅ 每帧约 40ms，触发 onFrameRecorded
    })
    console.log('[_正式录音] start() called, duration=15000ms state=', this._recordingState)
    // ✅ 清防重入标志（onStart 可能在 start() 后立即触发）
    this._formalRecordingStarting = false
    this._forceStopTimer = setTimeout(() => {
      console.log('[_正式录音] 12s FORCE STOP, state=', this._recordingState, 'isRecording=', this.data.isRecording, 'pending=', !!this._pendingRecordingFile)
      if (this._recordingState === 'asr') {
        this._recorderStopping = true  // ✅ 标记录音机正在停止
        try {
          recorderManager.stop()
          console.log('[_正式录音] stop() called successfully')
        } catch(e) {
          console.error('[_正式录音] stop() failed:', e)
          this._recorderStopping = false  // 失败时重置
        }
      } else if (this._pendingRecordingFile) {
        // state is null but we have pending file - process it now
        console.log('[_正式录音] FORCE STOP processing pending file')
        const pf = this._pendingRecordingFile
        this._pendingRecordingFile = null
        const fs = wx.getFileSystemManager()
        fs.readFile({
          filePath: pf,
          success: (r) => {
            const d = r.data
            console.log('[ASR-WS] FORCE pending PCM:', d.byteLength || d.length, 'bytes')
            if (!this._asrSocket || !this._asrSocketReady) { this._sendVoiceToASR(pf); return }
            this._asrSocket.send({ data: d, success: () => {}, fail: (e) => { this._asrSocket.close(); this._asrSocket = null; this._asrSocketReady = false; this._sendVoiceToASR(pf) } })
          },
          fail: () => { this._sendVoiceToASR(pf) }
        })
      }
    }, 12000)

    this._volumeSim = setInterval(() => {
      if (this.data.isRecording) this.setData({ audioLevel: Math.floor(Math.random() * 8) + 5 })
    }, 150)

    this._silenceTimer = setTimeout(() => {
      if (this.data.sleepModeActive && this.data.isRecording) this._stop正式录音()
    }, VAD.SPEECH_TIMEOUT)
  },

  _stop正式录音() {
    // Bug 修复：不要在这里清 _recordingState，让 onStop 读取后自行处理
    if (this._recordingState !== 'asr' && this._recordingState !== 'vad') {
      console.warn('[_ASR] 当前状态', this._recordingState, '，无需停止')
      return
    }
    if (this._recorderStopping) {
      console.warn('[_ASR] recorder already stopping, skip')
      return
    }
    if (this._volumeSim) clearInterval(this._volumeSim)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    if (this._asrFinalSilenceTimer) { clearTimeout(this._asrFinalSilenceTimer); this._asrFinalSilenceTimer = null }
    this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
    // ❌ 不在这里清 state，onStop 需要根据 state 判断处理逻辑
    this._recorderStopping = true  // ✅ 标记录音机正在停止
    recorderManager.stop()
  },

  // ================================================
  // 真实 API：ASR 语音转文字（腾讯云实时识别 + 流式处理）
  // ================================================
  _sendVoiceToASR(filePath) {
    // ✅ 流式已发过 AI → 降级结果丢弃
    if (this._aiRequestSent) {
      console.warn('[ASR-Fallback] AI already sent, skip:', filePath)
      this.setData({ _asrPending: false })
      setTimeout(() => this._startVADLoop(), 500)
      return
    }
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
      this._scrollToBottom()
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
        this._scrollToBottom()
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

    console.log('[_sendToAI] sending SSE request, text=', text.slice(0, 30), 'sleepMode=', fromSleep)
    let hasStreamTTS = false
    const requestTask = app.authRequest({
      url: `${API}/api/v1/chat/cbt/stream`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { user_id: userId, message: text, session_id: sessionId, skip_tts: !fromSleep },
      enableChunked: true,
      success: (res) => {
        console.log('[_sendToAI] SSE success, status=', res.statusCode, 'hasData=', !!res.data)
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

        // ✅ 修复：使用同步变量 _ttsStreamPlaying/_ttsPlaying 判断，避免 setData 异步延迟导致误判
        const isTTSPlaying = this._ttsStreamPlaying || this._ttsPlaying || this.data.isPlayingTTS
        if (fromSleep && this.data.sleepModeActive && !isTTSPlaying && (this.data.ttsQueue || []).length === 0) {
          const finalText = streamingText.trim()
          console.log('[SleepMode] SSE done, hasStreamTTS:', hasStreamTTS, 'finalText:', finalText || '(empty)')
          // 如果流式过程中已经下发 tts_chunk，就不再整句 fallback 合成
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
          // ✅ 文本模式下不自动播放 TTS（保留手动点击"听"按钮）
          // if (!hasStreamTTS && finalText) { this._playTTS(finalText, false) }
          const closeDecision = this._shouldTriggerClosure(text, streamingText)
          if (closeDecision.trigger) {
            console.log('[Closure] trigger:', closeDecision.reason, 'delay:', closeDecision.delay)
            setTimeout(() => this.triggerClosure(), closeDecision.delay)
          }
        }
      },
      fail: (err) => {
        console.error('[_sendToAI] SSE request FAILED:', err)
        this.setData({ isAIResponding: false, isLoading: false, _asrPending: false })
        // ✅ 只在完全没有收到 TTS 时才 fallback（ERR_INCOMPLETE_CHUNKED_ENCODING 等网络错误不代表 TTS 没收到）
        if (fromSleep && !hasStreamTTS) {
          // _playTTS 内部的 onEnded/onError 会负责重启 VAD，这里不再 setTimeout 重复触发
          this._playTTS('刚才没听清楚，可以再说一遍吗？', true)
        } else if (fromSleep && this.data.sleepModeActive) {
          // 已经有 TTS 在流式播放，不调 fallback，由 TTS onEnded 重启 VAD；
          // 但如果 TTS 也异常结束没回调，加一道 5 秒兜底
          setTimeout(() => {
            if (this.data.sleepModeActive && this._recordingState === null && !this.data.isPlayingTTS) {
              console.log('[_sendToAI fail] 5s safety net, restart VAD')
              this._startVADLoop()
            }
          }, 5000)
        }
      },
      complete: () => {
        // ✅ 不在这里触发 VAD（可能早于 success 处理完最后 chunks）；
        // success / fail 里已处理 VAD 重启，onEnded 回调也会触发
      }
    })

    let sseBuffer = ''
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
          if (data.event === 'error') {
            console.error('[SSE] error event:', data.message)
            this.setData({ isAIResponding: false, isLoading: false })
            return
          }
          if (data.event === 'chunk') {
            streamingText += data.data
            flushText()
            console.log('[SSE] chunk event, text len=', streamingText.length)
          }
          if (data.event === 'final' && data.content) {
            streamingText = data.content
            flushText()
          }
          // CBT 阶段状态（用于进度条 UI）
          if (data.event === 'cbt_state') {
            const phase = data.data
            const label = phase.phase_label || ''
            const hint = phase.phase_hint || ''
            if (label && phase.phase !== 'normal_chat' && phase.phase !== 'safety') {
              this.setData({
                cbtPhase: phase.phase,
                cbtPhaseLabel: label,
                cbtPhaseHint: hint,
                showCbtPhase: true,
              })
              console.log("[CBT-UI] phase=", phase.phase, "label=", label, "hint=", hint)
            } else {
              this.setData({ showCbtPhase: false })
            }
          }
          // 兼容新版按句合成（tts_sentence：完整 MP3）
          if (data.event === 'tts_sentence') {
            console.log('[SSE] tts_sentence event: index=', data.index, 'text=', data.text ? data.text.slice(0, 20) : '', 'audioLen=', data.audio_base64 ? data.audio_base64.length : 0)
            // ✅ 记录最近一次 TTS 文本，用于 ASR 回声过滤
            if (data.text && data.text.trim()) {
              this._lastTTSText = data.text.trim()
            }
            if (data.audio_base64 && !data.done) {
              hasStreamTTS = true
              this._ttsStreamDone = true  // ✅ 标记 TTS 已下发，播完后重启 VAD
              // ✅ 文本模式下不自动播放 TTS，睡眠模式下才自动播放
              if (fromSleep) {
                this._enqueueStreamTTS(data.audio_base64)
              }
              this._ttsChunks.push(data.audio_base64)
            }
          }
          // 兼容旧版流式分片（tts_chunk）
          if (data.event === 'tts_chunk') {
            console.log('[SSE] tts_chunk event: index=', data.index, 'done=', data.done, 'audioLen=', data.audio_base64 ? data.audio_base64.length : 0, 'hasError=', !!data.error)
            if (data.audio_base64 && !data.done) {
              hasStreamTTS = true
              // ✅ 流式播放：收到 chunk 立即入队播放，不等全部收完
              let chunkStr = data.audio_base64
              if (typeof chunkStr !== 'string') {
                // 假设是 ArrayBuffer，转为 base64
                try {
                  const bytes = new Uint8Array(chunkStr)
                  let b64 = ''
                  for (let i = 0; i < bytes.length; i += 3) {
                    const b0 = bytes[i], b1 = bytes[i + 1] || 0, b2 = bytes[i + 2] || 0
                    b64 += String.fromCharCode(b0 >> 2)
                    b64 += String.fromCharCode(((b0 & 3) << 4) | (b1 >> 4))
                    b64 += String.fromCharCode(((b1 & 15) << 2) | (b2 >> 6))
                    b64 += String.fromCharCode(b2 & 63)
                  }
                  const padding = bytes.length % 3
                  if (padding === 1) b64 = b64.slice(0, -2) + '=='
                  else if (padding === 2) b64 = b64.slice(0, -1) + '='
                  chunkStr = b64
                } catch (e) {
                  console.error('[TTS] ArrayBuffer→base64 failed:', e)
                  return
                }
              }
              // ✅ 睡眠模式下才自动流式播放，文本模式保留音频供手动点击
              if (fromSleep) {
                this._enqueueStreamTTS(chunkStr)
              }
              // 同时保留到 _ttsChunks（fallback 用）
              this._ttsChunks.push(chunkStr)
            }
            if (data.done && !data.error) {
              console.log('[SSE] tts_chunk done, stream queue:', this._ttsStreamQueue.length, 'playing:', this._ttsStreamPlaying)
              this._ttsStreamDone = true
              // 如果流式队列已空且没在播放，恢复状态
              if (!this._ttsStreamPlaying && this._ttsStreamQueue.length === 0) {
                this._ttsPlaying = false
                this.setData({ isPlayingTTS: false, _asrPending: false })
                if (this.data.sleepModeActive) this._resetCompanionTimer()
                if (this.data.sleepModeActive && !this.data._pmrActive) {
                  this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
                  setTimeout(() => this._startVADLoop(), 500)
                }
              }
              // fallback：如果流式播放失败（没收到任何 chunk），用合并播放
              if (this._ttsChunks.length > 0 && !hasStreamTTS) {
                this._playMergedTTS()
              }
            }
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
    app.authRequest({
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
            innerAudioContext.onError((err) => {
              console.error('[TTS] fallback audio error:', err && err.errMsg)
              this.setData({ isPlayingTTS: false, _asrPending: false })
              if (err && err.errMsg && err.errMsg.includes('access denied')) {
                // 系统打断，清理状态并重启 VAD
                if (this.data.sleepModeActive) {
                  this._clearTTSQueue()
                  setTimeout(() => this._restartVAD('fallback audio access denied'), 500)
                }
                return
              }
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

  // ================================================
// 刺激控制提醒（Stimulus Control）— CBT-I 核心行为干预
// 原理：躺床超过20分钟睡不着 → 起床做无聊的事 → 等困了再回床
// 目的：重新建立"床 = 睡觉"的信号，打破失眠-焦虑循环
// ================================================

  // 启动刺激控制计时器（进入睡眠模式或文本模式聊天时调用）
  // 固定 20 分钟，不在互动时重置
  _resetStimulusControlTimer() {
    // 清除旧计时器
    if (this._stimulusControlTimer) {
      clearTimeout(this._stimulusControlTimer)
      this._stimulusControlTimer = null
    }
    // 重置显示标志（每次可再次触发）
    this._stimulusControlShown = false
    // 记录会话开始时间
    this._sessionStartTime = Date.now()

    // 睡眠模式 或 文本模式 都启动计时器
    const isActive = this.data.sleepModeActive || this.data.mode === 'text'
    if (!isActive) return

    console.log('[StimulusControl] Timer started, will fire in', this.STIMULUS_CONTROL_MS / 1000 / 60, 'minutes')
    this._stimulusControlTimer = setTimeout(() => {
      this._showStimulusReminder()
    }, this.STIMULUS_CONTROL_MS)
  },

  // 显示刺激控制提醒卡片（计时器触发时调用）
  _showStimulusReminder() {
    const isActive = this.data.sleepModeActive || this.data.mode === 'text'
    if (!isActive) return  // 睡眠模式或文本模式才显示
    if (this._stimulusControlShown) return  // 防止重复弹出
    this._stimulusControlShown = true

    console.log('[StimulusControl] Firing - showing card')
    this.setData({
      showStimulusCard: true,
      stimulusCardMessage: '躺在床上超过 20 分钟还没睡着？起身去别的房间，做点无聊的事，等困了再回来。'
    })
  },

  // 用户点"知道了"关闭卡片
  dismissStimulusCard() {
    this.setData({ showStimulusCard: false })
    // 关闭卡片后重新启动计时器（新一轮 20 分钟）
    this._resetStimulusControlTimer()
  },

// ================================================
// 夜间陪伴模式 - 主动关怀
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
    if (this._asrFinalSilenceTimer) { clearTimeout(this._asrFinalSilenceTimer); this._asrFinalSilenceTimer = null }
    if (this._textTtsTimer) clearInterval(this._textTtsTimer)
    if (this._breathCountdownTimer) clearInterval(this._breathCountdownTimer)
    if (this._breathPhaseTimer) clearTimeout(this._breathPhaseTimer)
    if (this._companionTimer) clearTimeout(this._companionTimer)
    if (this.data.isRecording || this.data.isListening) {
      try { recorderManager.stop() } catch (e) {}
    }
    try { innerAudioContext.stop() } catch (e) {}
    try { innerAudioContext.volume = 0 } catch (e) {}
    this._clearTTSQueue()
    // 强制重置录音状态机（stopAll 用于页面退出/隐藏）
    this._recordingActive = false
    this._recordingState = null
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

    // 4. 对话轮数过多（文本模式适当放宽，避免过早关闭）
    const roundThreshold = this.data.mode === 'text' ? 12 : 8
    if (this.data.conversationRound >= roundThreshold) {
      return { trigger: true, delay: 1000, reason: '对话轮数过多' }
    }

    // 5. 凌晨深夜加速（1-5点）——仅睡眠模式生效，文本模式不触发
    const hour = new Date().getHours()
    if (this.data.mode === 'sleep' && hour >= 1 && hour <= 5 && this.data.conversationRound >= 3) {
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
    app.authRequest({
      url: `${API}/api/v1/sleep/window`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: { user_id: app.globalData.userId || '', bed_hour: bh, bed_min: bm, wake_hour: wh, wake_min: wm },
      fail: () => {}  // non-critical
    })

    // POST to sleep diary bedtime API - 保存今晚睡眠计划
    app.authRequest({
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
          }, () => {
            this._resetStimulusControlTimer()
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
        app.authRequest({
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
      app.authRequest({
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
      const res = await app.authRequest({
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
    app.authRequest({
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

  _scrollToBottom() {
    // 先清空再设置，确保 scroll-into-view 每次都能触发
    this.setData({ scrollToMsg: '' }, () => {
      wx.nextTick(() => {
        this.setData({ scrollToMsg: 'msg-bottom' })
      })
    })
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
      await app.authRequest({
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
  // ================================================
  // TTS 持久播放器 — 单例 onEnded 驱动队列
  // ================================================
  _initTTSPlayer() {
    this._ttsChunks = []       // 保留：收集所有 chunk（用于 fallback 合并播放）
    this._ttsStreamQueue = []  // ✅ 新增：流式播放队列（文件路径数组）
    this._ttsStreamPlaying = false
    this._ttsStreamDone = false
    this._ttsPlaying = false
    this._currentTTSCtx = null
    console.log('[TTS] player initialized (streaming mode)')
  },

  // ✅ 流式 TTS：收到 chunk 立即入队播放，不等全部收完
  _enqueueStreamTTS(audioBase64) {
    if (!audioBase64) return
    const clean = typeof audioBase64 === 'string' ? audioBase64.replace(/[\s\r\n]/g, '') : ''
    if (!clean) return

    try {
      const buf = wx.base64ToArrayBuffer(clean)
      const fs = wx.getFileSystemManager()
      const filePath = `${wx.env.USER_DATA_PATH}/tts_stream_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.mp3`
      fs.writeFile({
        filePath,
        data: buf,
        encoding: 'binary',
        success: () => {
          this._ttsStreamQueue.push(filePath)
          console.log('[TTS] stream chunk queued:', filePath, 'size:', buf.byteLength, 'queue:', this._ttsStreamQueue.length)
          // 如果当前没在播放，立即开始
          if (!this._ttsStreamPlaying) {
            this._playNextStreamTTS()
          }
        },
        fail: (err) => {
          console.error('[TTS] stream write fail:', err)
        }
      })
    } catch (e) {
      console.error('[TTS] stream decode fail:', e)
    }
  },

  // ✅ 播放下一个流式 chunk
  _playNextStreamTTS() {
    if (this._ttsStreamQueue.length === 0) {
      this._ttsStreamPlaying = false
      // 如果全部播放完毕且 done=true，恢复状态
      if (this._ttsStreamDone) {
        this._ttsPlaying = false
        this.setData({ isPlayingTTS: false, _asrPending: false })
        if (this.data.sleepModeActive) this._resetCompanionTimer()
        if (this.data.sleepModeActive && !this.data._pmrActive) {
          this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
          // ✅ 清锁 + 触发 TTS 结束回调，让 onTTSEnd 启动 VAD
          this._vadRestartPending = false
          this._fireTTSEndCallbacks()
        }
      }
      return
    }

    const filePath = this._ttsStreamQueue.shift()
    this._ttsStreamPlaying = true
    this._ttsPlaying = true
    this.setData({ isPlayingTTS: true, statusText: '正在播放', statusHint: '闭上眼睛，听我说' })
    this._resetCompanionTimer()

    // 停止前一个播放器
    // 尝试复用 InnerAudioContext，减少真机 access denied 问题
    let ctx = this._currentTTSCtx
    const needNewCtx = !ctx || !ctx.src
    if (needNewCtx) {
      if (ctx) {
        try { ctx.destroy() } catch (e) {}
      }
      ctx = wx.createInnerAudioContext({ useWebAudioImplement: false, privateUseSpeaker: true })
      ctx.obeyMuteSwitch = false
      this._currentTTSCtx = ctx
      
      // 只在创建新实例时绑定事件（避免重复绑定）
      ctx.onEnded(() => {
        // 不销毁，复用实例
        this._currentTTSCtx = ctx
        // ✅ 触发 TTS 结束回调（事件驱动 defer）
        this._fireTTSEndCallbacks()
        // 继续播放下一个
        this._playNextStreamTTS()
      })
      
      ctx.onError((err) => {
        if (err.errCode !== 0 && err.errCode !== 10001) {
          console.error('[TTS] stream play error:', err)
        }
        // access denied 时销毁并创建新实例，清理状态并重启 VAD
        if (err.errMsg && err.errMsg.includes('access denied')) {
          console.warn('[TTS] access denied, cleanup and restart VAD')
          try { ctx.destroy() } catch (e) {}
          this._currentTTSCtx = null
          this._ttsPlaying = false
          this._ttsStreamPlaying = false
          this.setData({ isPlayingTTS: false, _asrPending: false })
          if (this.data.sleepModeActive) {
            this._clearTTSQueue()
            this._fireTTSEndCallbacks()
            setTimeout(() => this._restartVAD('audio access denied'), 500)
          }
          return
        }
        // 出错也继续播放下一个
        setTimeout(() => this._playNextStreamTTS(), 100)
      })
    } else {
      // 复用实例：先停止当前播放
      try { ctx.stop() } catch (e) {}
    }
    
    ctx.src = filePath

    setTimeout(() => {
      try {
        ctx.play()
        console.log('[TTS] stream playing:', filePath, 'reused:', !needNewCtx)
      } catch (e) {
        console.error('[TTS] stream play fail:', e)
        // play 失败可能是 access denied，销毁后重试
        try { ctx.destroy() } catch (e2) {}
        this._currentTTSCtx = null
        setTimeout(() => this._playNextStreamTTS(), 100)
      }
    }, 30)
  },

  // ✅ 合并所有 chunk，一次性播放（fallback，解决 errCode:55 unknown format）
  _playMergedTTS() {
    const chunks = this._ttsChunks
    this._ttsChunks = []
    if (chunks.length === 0) {
      console.warn('[TTS] no chunks to play')
      return
    }

    console.log('[TTS] merging', chunks.length, 'chunks via wx.base64ToArrayBuffer')

    let totalLen = 0
    const buffers = []
    for (const b64 of chunks) {
      const clean = typeof b64 === 'string' ? b64.replace(/[\s\r\n]/g, '') : ''
      try {
        const buf = wx.base64ToArrayBuffer(clean)
        buffers.push(buf)
        totalLen += buf.byteLength
      } catch (e) {
        console.error('[TTS] decode chunk failed:', e)
        return
      }
    }
    console.log('[TTS] merged binary size:', totalLen, 'bytes')

    const merged = new Uint8Array(totalLen)
    let offset = 0
    for (const buf of buffers) {
      merged.set(new Uint8Array(buf), offset)
      offset += buf.byteLength
    }

    this._resetCompanionTimer()
    this._ttsPlaying = true
    this.setData({ isPlayingTTS: true, statusText: '正在播放', statusHint: '闭上眼睛，听我说' })

    const prevCtx = this._currentTTSCtx
    if (prevCtx) {
      try { prevCtx.stop() } catch (e) {}
      try { prevCtx.destroy() } catch (e) {}
    }

    const ctx = wx.createInnerAudioContext({ useWebAudioImplement: false, privateUseSpeaker: true })
    ctx.obeyMuteSwitch = false
    this._currentTTSCtx = ctx

    ctx.onEnded(() => {
      ctx.destroy()
      this._ttsPlaying = false
      this.setData({ isPlayingTTS: false, _asrPending: false, ttsProgress: 0 })
      // ✅ 触发 TTS 结束回调（事件驱动 defer）
      this._fireTTSEndCallbacks()
      if (this.data.sleepModeActive) this._resetCompanionTimer()
      if (this.data.sleepModeActive && !this.data._pmrActive) {
        this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
        setTimeout(() => {
          this._vadRestartPending = false  // ✅ 清锁后再重启
          this._restartVAD('merged tts ended')
        }, 500)
      }
    })
    ctx.onError((err) => {
      if (err.errCode !== 0 && err.errCode !== 10001) {
        console.error('[TTS] play error:', err)
      }
      // access denied 时清理状态并重启 VAD
      if (err.errMsg && err.errMsg.includes('access denied')) {
        console.warn('[TTS] merged access denied, cleanup and restart VAD')
        ctx.destroy()
        this._currentTTSCtx = null
        this._ttsPlaying = false
        this.setData({ isPlayingTTS: false, _asrPending: false })
        if (this.data.sleepModeActive) {
          setTimeout(() => this._restartVAD('merged audio access denied'), 500)
        }
        return
      }
      ctx.destroy()
      this._ttsPlaying = false
      this.setData({ isPlayingTTS: false })
    })

    const fs = wx.getFileSystemManager()
    const filePath = `${wx.env.USER_DATA_PATH}/tts_merged_${Date.now()}.mp3`
    fs.writeFile({
      filePath,
      data: merged.buffer,
      encoding: 'binary',
      success: () => {
        console.log('[TTS] file written:', filePath)
        ctx.src = filePath
        setTimeout(() => {
          try {
            ctx.play()
            console.log('[TTS] play started')
          } catch (e) { console.error('[TTS] play fail:', e) }
        }, 80)
      },
      fail: (err) => {
        console.error('[TTS] write fail:', err)
        ctx.destroy()
        this._ttsPlaying = false
        this.setData({ isPlayingTTS: false })
      }
    })
  },

  // ✅ 清空队列（对话被打断时调用）
  _clearTTSQueue() {
    this._ttsChunks = []
    this._ttsStreamQueue = []
    this._ttsStreamPlaying = false
    this._ttsStreamDone = false
    this._ttsPlaying = false
    const prev = this._currentTTSCtx
    if (prev) {
      try { prev.stop() } catch (e) {}
      try { prev.destroy() } catch (e) {}
      this._currentTTSCtx = null
    }
    console.log('[TTS] queue cleared')
  },

  // ================================================
  // 原有全局 innerAudioContext 的 onEnded（保留用于非队列场景）
  // ================================================
  onLoad() {
    // ✅ 初始化录音状态机变量，避免 undefined !== null 陷阱
    this._recordingState = null
    this._recordingActive = false
    this._recorderLocked = false   // ✅ onStart/onStop 驱动的底层录音机锁
    this._recorderStopping = false // ✅ 标记录音机正在停止（防止 stop/start 竞态）
    this._vadRetryCount = 0        // ✅ VAD 重试计数器
    this._vadLoopActive = false    // ✅ 防止多个 VAD 循环并发
    this._vadRestartPending = false // ✅ VAD 重启防重入锁
    this._ttsEndCallbacks = []      // ✅ TTS 结束回调队列（事件驱动 defer）
    this._formalRecordingStarting = false // ✅ 正式录音启动防重入
    // ✅ 初始化 TTS 持久播放器
    this._initTTSPlayer()

    innerAudioContext.onEnded(() => {
      this.setData({ isPlayingTTS: false, ttsProgress: 0 })
      if (this._textTtsTimer) clearInterval(this._textTtsTimer)
      // ✅ 触发 TTS 结束回调（事件驱动 defer）
      this._fireTTSEndCallbacks()
      
      // 睡眠模式：TTS 播完后重新开始监听（仅当音频队列空时）
      if (this.data.sleepModeActive && !this.data._pmrActive && (this.data.ttsQueue || []).length === 0) {
        this.setData({ statusText: '聆听中', statusHint: '手机放在枕边，继续说吧' })
        setTimeout(() => {
          if (!this._recorderStopping) this._restartVAD('tts ended')
        }, 500)
      }
      
      // PMR 完成
      if (this.data._pmrActive) {
        this.data._pmrActive = false
        this.onPMRAutoDone()
      }
    })

    // 检查订阅状态（data 初始化时已预读，这里仅做过期校验）
    const sub = wx.getStorageSync('subscription') || {}
    if (sub.isPremium && sub.expireDate) {
      const expired = new Date(sub.expireDate) <= new Date()
      if (expired && this.data.isPremium) {
        this.setData({ isPremium: false })
      }
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

    // 确保 onStart/onStop 回调存在
    console.log('[Recorder] registering callbacks, current state:', this._recordingState)
    recorderManager.onStart(() => {
      this._vadRetryCount = 0
      this._vadRestartPending = false  // ✅ VAD 重启成功，清除防重入锁
      console.log('[Recorder] onStart confirmed')
    })
    recorderManager.onStop((res) => {
      // 使用 this._recordingState 而非闭包捕获的 state，避免 stop 前被清空导致误判
      const state = this._recordingState
      console.log('[Recorder] onStop FIRED, state=', state, 'fileSize=', res.fileSize, 'duration=', res.duration)
      this._recordingActive = false
      this._recorderLocked = false  // ✅ 释放底层录音机锁
      this._recorderStopping = false  // ✅ 录音机已完全停止
      this._vadLoopActive = false     // ✅ 释放 VAD 单例锁
      // ✅ 清除 FORCE STOP 定时器，避免游离定时器干扰
      if (this._forceStopTimer) { clearTimeout(this._forceStopTimer); this._forceStopTimer = null }

      if (state === 'vad') {
        const hasSound = res.fileSize > 5000  // ✅ 提高阈值，减少环境噪音误触发（原为 3500）
        console.log('[_VAD] onStop, fileSize:', res.fileSize, 'hasSound:', hasSound)
        const level = hasSound ? Math.floor(Math.random() * 6) + 6 : Math.floor(Math.random() * 4)
        this.setData({ audioLevel: level })

        if (!hasSound && this.data.sleepModeActive && !this.data.isSleepFadingOut) {
          // 入睡检测：累加安静时间
          const newQuietMs = this.data.sleepDetectionQuietMs + 1200
          this.setData({ sleepDetectionQuietMs: newQuietMs })
          if (newQuietMs >= this.SLEEP_DETECTION_THRESHOLD_MS) {
            console.log('[Sleep] detected, triggering fade out')
            this._triggerSleepFadeOut()
            return
          }
        } else if (hasSound) {
          this.setData({ sleepDetectionQuietMs: 0 })
        }

        // Bug 2 修复：VAD 分支不直接调用 start()，统一经由 _startVADLoop()
        if (hasSound && !this.data.isRecording) {
          this._vadActive = false
          // ✅ 延迟 300ms 再开始正式录音，让 VAD 尾音和环境噪音消散（原为 600ms，减少延迟）
          setTimeout(() => {
            if (!this.data.isRecording && !this._recorderStopping) {
              console.log('[_VAD] delay 300ms, starting formal recording')
              this._start正式录音()
            }
          }, 300)
        } else if (this.data.sleepModeActive) {
          this._listenTimer = setTimeout(() => {
            if (!this._recorderStopping) this._restartVAD('vad no sound')
          }, 100)
        }
        return
      }

      // 检查是否有_pending的PCM文件（VAD模式切换时遗留的）
      if (this._pendingRecordingFile && !state) {
        console.log('[ASR-WS] processing pending PCM file from VAD transition, path:', this._pendingRecordingFile, 'size:', res.fileSize)
        const pendingFile = this._pendingRecordingFile
        this._pendingRecordingFile = null
        const fs = wx.getFileSystemManager()
        fs.readFile({
          filePath: pendingFile,
          success: (readRes) => {
            const data = readRes.data
            const size = data.byteLength || data.length || 0
            console.log('[ASR-WS] pending PCM read SUCCESS:', size, 'bytes')
            if (!this._asrSocket || !this._asrSocketReady) {
              this._sendVoiceToASR(pendingFile)
              return
            }
            this._asrSocket.send({
              data: data,
              success: () => { console.log('[ASR-WS] pending send success') },
              fail: (err) => {
                console.error('[ASR-WS] pending send FAIL:', err)
                this._asrSocket.close(); this._asrSocket = null; this._asrSocketReady = false
                this._sendVoiceToASR(pendingFile)
              }
            })
            setTimeout(() => {
              if (this._asrSocket) {
                this._asrSocket.send({ data: JSON.stringify({ type: 'end' }) })
              }
            }, 100)
            setTimeout(() => {
              if (this._asrSocket) {
                this._asrSocket.close(); this._asrSocket = null; this._asrSocketReady = false
                this._sendVoiceToASR(pendingFile)
              }
            }, 12000)
          },
          fail: () => { this._sendVoiceToASR(pendingFile) }
        })
        return
      }

      if (state === 'asr') {
        console.log('[ASR-WS] ==== onStop ASR branch ENTERED, duration:', res.duration, 'fileSize=', res.fileSize, 'tempPath=', res.tempFilePath)
        // ✅ 第二层：有效帧过滤（少于 800ms 有效语音不发送，跳过噪音误识别）
        const effectiveFrames = this._voiceFrameCount || 0
        const effectiveDuration = effectiveFrames * 40  // 每帧约 40ms
        console.log('[ASR-WS] effective voice frames:', effectiveFrames, '~', effectiveDuration, 'ms')
        if (effectiveDuration < 800) {
          console.warn('[ASR-WS] 有效语音太短 (<800ms)，跳过识别，关闭 socket')
          if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null; this._asrSocketReady = false }
          this._voiceFrameCount = 0
          // ✅ 清除 FORCE STOP 定时器，避免游离定时器干扰
          if (this._forceStopTimer) { clearTimeout(this._forceStopTimer); this._forceStopTimer = null }
          this.setData({ isRecording: false, audioLevel: 0, statusText: '聆听中', statusHint: '继续说吧' })
          this._recordingState = null  // ✅ 重置状态，避免 Fix 3 兜底保护阻塞
          if (this.data.sleepModeActive) {
            setTimeout(() => {
              if (!this._recorderStopping && !this._recorderLocked) {
                this._restartVAD('short voice')
              } else {
                console.warn('[ASR-WS] recorder still busy, skip VAD restart')
              }
            }, 500)
          }
          return
        }
        this._voiceFrameCount = 0  // 重置计数
        // ✅ 清除 FORCE STOP 定时器，避免游离定时器干扰
        if (this._forceStopTimer) { clearTimeout(this._forceStopTimer); this._forceStopTimer = null }
        // 记录用量
        if (res.duration > 0) {
          this._recordUsage('voice', Math.ceil(res.duration / 1000))
        }
        this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
        this._recordingActive = false  // ✅ 允许 VAD 重新接管
        // ✅ 关键判断：WS 曾经建立过 → 正常流式流程，不走降级
        if (this._wsEverOpened) {
          console.log('[ASR-WS] WS was open, sending end marker only')
          if (this._asrSocket && this._asrSocket.readyState === 1) {
            this._asrSocket.send({ data: JSON.stringify({ type: 'end' }) })
            // 发完再关闭
            setTimeout(() => {
              if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null }
              this._asrSocketReady = false
            }, 200)
          } else {
            console.log('[ASR-WS] WS already closed, skip end marker')
          }
        } else {
          // WS 从未建立 → 才走降级上传
          console.warn('[ASR] WS never opened, fallback upload')
          if (res.tempFilePath) this._sendVoiceToASR(res.tempFilePath)
          else this._startVADLoop()
        }
        // ✅ 处理完 ASR 后重置 state（设为 null 让 VAD onStop 的 state===null 判断成立）
        this._recordingState = null
        // ✅ Fix 1: 有 pending VAD 重启标记时，直接重启 VAD
        if (this._pendingRestartVAD) {
          this._pendingRestartVAD = false
          console.log('[ASR-WS] onStop → restart VAD (pending)')
          setTimeout(() => {
            if (!this._recorderStopping) this._restartVAD('pending')
          }, 300)
          return
        }
        // ✅ 正常 ASR 结束后也重启 VAD（避免循环断掉）
        if (this.data.sleepModeActive) {
          console.log('[ASR-WS] onStop → restart VAD (normal end)')
          setTimeout(() => {
            if (!this._recorderStopping && !this._recorderLocked) {
              this._restartVAD('normal end')
            } else {
              console.warn('[ASR-WS] recorder still busy, skip VAD restart')
            }
          }, 500)
          return
        }
      }
    })

    recorderManager.onError((err) => {
      console.error('[Recorder Error]', err)
      this._recordingActive = false
      this._recorderLocked = false
      this._recorderStopping = false
      this._vadLoopActive = false
      this._recordingState = null

      const errMsg = (err && err.errMsg) || ''

      // ✅【并发 start 误报】"audio is recording, don't start record again"
      // 这是并发调用 recorderManager.start() 的副作用，录音机硬件本身正常。
      // 不要退出睡眠模式，只清状态、延迟重启 VAD 让状态机自愈。
      if (errMsg.includes('audio is recording') || errMsg.includes("don't start record again")) {
        console.warn('[Recorder] 并发 start 误报，已自动恢复（不退出睡眠模式）')
        if (this.data.sleepModeActive) {
          // 等录音机真正空闲（系统侧）再重启 VAD
          if (this._listenTimer) clearTimeout(this._listenTimer)
          this._listenTimer = setTimeout(() => {
            if (this.data.sleepModeActive && !this._recorderLocked && !this._recorderStopping) {
              this._restartVAD('recover from concurrent-start')
            }
          }, 1200)
        }
        return
      }

      const isNotFound = errMsg.includes('NotFoundError')
      if (isNotFound) {
        // 模拟器无麦克风 → 退出睡眠模式，切文字模式
        console.warn('[Recorder] 模拟器无麦克风，自动切换为文字模式')
        wx.showToast({ title: '模拟器无麦克风，已切换为文字模式', icon: 'none', duration: 3000 })
        this.exitSleepMode()
        this.setData({ mode: 'text', sleepModeActive: false, isRecording: false, audioLevel: 0 }, () => {
          this._resetStimulusControlTimer()
        })
        return
      }

      // ✅【临时性失败】operateRecorder:fail（无具体原因）也可能是系统瞬时占用，先尝试自愈
      const isTransient = errMsg.includes('operateRecorder:fail') && !errMsg.includes('auth') && !errMsg.includes('permission') && !errMsg.includes('Permission')
      if (isTransient && this.data.sleepModeActive) {
        this._recorderTransientCount = (this._recorderTransientCount || 0) + 1
        if (this._recorderTransientCount <= 3) {
          console.warn('[Recorder] 临时失败，自愈重试 ' + this._recorderTransientCount + '/3')
          if (this._listenTimer) clearTimeout(this._listenTimer)
          this._listenTimer = setTimeout(() => {
            if (this.data.sleepModeActive) this._restartVAD('recover from transient error')
          }, 1500)
          return
        }
        // 连续 3 次失败才放弃
        console.error('[Recorder] 连续 3 次临时失败，退出睡眠模式')
        this._recorderTransientCount = 0
      }

      // 真正的硬故障（权限拒绝等）：退出睡眠模式，切文字模式
      if (this.data.sleepModeActive) {
        console.warn('[Recorder] 录音硬故障，退出睡眠模式:', errMsg)
        this.exitSleepMode()
        this.setData({ mode: 'text', sleepModeActive: false, isRecording: false, audioLevel: 0 }, () => {
          this._resetStimulusControlTimer()
        })
        if (this._asrSocket) { this._asrSocket.close(); this._asrSocket = null }
      }
    })

    recorderManager.onFrameRecorded((res) => {
      if (!this._enableFrameRecord) { console.log('[onFrameRecorded] ignored, frameRecord disabled'); return }
      // ✅ Fix 2: WS 已关闭（收到 done 信号），丢弃帧
      if (this._wsReceivedDone) {
        console.log('[onFrameRecorded] WS done, discard frame')
        return
      }
      const { frameBuffer, isLastFrame } = res
      if (!frameBuffer || frameBuffer.byteLength === 0) return
      console.log('[onFrameRecorded] fired, hasBuffer=', !!frameBuffer, 'bufferLen=', frameBuffer.byteLength, 'isLastFrame=', isLastFrame)

      // ✅ 第一层：RMS 能量过滤（过滤噪音/底噪帧）
      const rms = this._calcRMS(frameBuffer)
      const VOICE_RMS_THRESHOLD = 0.018  // 低于此值不发送（噪音静音过滤）
      if (rms < VOICE_RMS_THRESHOLD) {
        // 静音帧：不发送，但继续检测静音超时
        if (this._silenceTimer) clearTimeout(this._silenceTimer)
        this._silenceTimer = setTimeout(() => {
          if (this.data.sleepModeActive && this.data.isRecording) {
            console.log('[onFrameRecorded] silence timeout, stopping recording')
            this._stop正式录音()
          }
        }, VAD.SPEECH_TIMEOUT)
        return
      }

      // ✅ 有声帧：计入有效帧计数
      this._voiceFrameCount = (this._voiceFrameCount || 0) + 1

      // ✅ 丢弃前 8 帧 warmup（≈320ms）：采集背景噪音基线
      const WARMUP_FRAMES = 8
      const VOICE_MULTIPLIER = 1.5  // 人声阈值 = baseline × 1.5（平衡误触发和漏检）
      if (this._warmupFrames < WARMUP_FRAMES) {
        this._warmupFrames++
        this._warmupRMSList.push(rms)
        if (this._warmupFrames === WARMUP_FRAMES) {
          // warmup 结束：用【最小值】而不是最大值作为 baseline
          // 最小值更能代表真实背景噪音，排除用户提前说话的帧
          this._noiseBaseline = Math.min(...this._warmupRMSList)
          this._noiseBaseline = Math.max(this._noiseBaseline, 30)  // 下限保护
          // ✅ 污染检测：baseline 异常高或呈现衰减形态（TTS 尾音特征），丢弃重新采集
          const baselineMin = this._noiseBaseline
          const baselineMax = Math.max(...this._warmupRMSList)
          const AMBIENT_NOISE_MAX = 600
          const TTS_DECAY_RATIO = 3.5
          // ✅ 改为 AND：必须同时满足"绝对值高"且"有衰减特征"才判定为污染
          const isPolluted = baselineMin > AMBIENT_NOISE_MAX && (baselineMax / baselineMin) > TTS_DECAY_RATIO
          if (isPolluted) {
            console.warn('[onFrameRecorded] warmup polluted (min=' + baselineMin.toFixed(0) + ' max=' + baselineMax.toFixed(0) + ' ratio=' + (baselineMax / baselineMin).toFixed(1) + '), resetting')
            this._warmupFrames = 0
            this._warmupRMSList = []
            this._noiseBaseline = 0
            return
          }
          console.log('[onFrameRecorded] warmup done, baseline(min):', this._noiseBaseline.toFixed(2), 'samples:', this._warmupRMSList.map(v => v.toFixed(0)).join(','))
        } else {
          console.log('[onFrameRecorded] warmup skip frame', this._warmupFrames, 'rms:', rms.toFixed(2))
        }
        return
      }
      // ✅ warmup 结束后，检测人声激活
      const voiceThreshold = (this._noiseBaseline || 0) * VOICE_MULTIPLIER
      if (!this._voiceDetected) {
        if (rms >= voiceThreshold) {
          // 确认是人声，开始发送
          this._voiceDetected = true
          console.log('[onFrameRecorded] VOICE DETECTED rms:', rms.toFixed(2), 'threshold:', voiceThreshold.toFixed(2))
        } else {
          // 还没检测到人声，丢弃
          console.log('[onFrameRecorded] waiting for voice rms:', rms.toFixed(2), 'need:', voiceThreshold.toFixed(2))
          return
        }
      }

      // ✅ 帧缓冲：攒够 6400 字节（约 200ms @ 16kHz）再发送，减少 WebSocket 消息频率
      this._audioFrameChunks = this._audioFrameChunks || []
      this._audioFrameChunks.push(frameBuffer)
      const chunkTotal = this._audioFrameChunks.reduce((sum, b) => sum + b.byteLength, 0)
      const FRAME_THRESHOLD = 6400  // 200ms

      if (chunkTotal >= FRAME_THRESHOLD || isLastFrame) {
        // 合并帧
        const merged = new Uint8Array(chunkTotal)
        let offset = 0
        for (const chunk of this._audioFrameChunks) {
          merged.set(new Uint8Array(chunk), offset)
          offset += chunk.byteLength
        }
        this._audioFrameChunks = []

        if (this._asrSocketReady && this._asrSocket) {
          this._asrSocket.send({ data: merged.buffer })
        } else {
          this._frameBuffer = this._frameBuffer || []
          this._frameBuffer.push(merged.buffer)
          console.log('[onFrameRecorded] buffered merged frame, queue size:', this._frameBuffer.length)
        }
      }

      // ✅ 最后一帧：发送结束信号
      if (isLastFrame) {
        console.log('[Recorder] 最后一帧，发送 end 信号')
        if (this._asrSocketReady && this._asrSocket) {
          this._asrSocket.send({ data: JSON.stringify({ type: 'end' }) })
        } else {
          this._frameBuffer = this._frameBuffer || []
          this._frameBuffer.push(JSON.stringify({ type: 'end' }))
        }
      }

      // 清除静音计时器（有声期间不触发停止）
      if (this._silenceTimer) clearTimeout(this._silenceTimer)
    })
  },

  _calcRMS(arrayBuffer) {
    // 计算 PCM 帧的 RMS（均方根）能量，用于过滤噪音帧
    const dataView = new DataView(arrayBuffer)
    let sum = 0
    const len = dataView.byteLength
    if (len === 0) return 0
    for (let i = 0; i < len; i += 2) {
      const sample = dataView.getInt16(i, true)
      sum += sample * sample
    }
    return Math.sqrt(sum / (len / 2))
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
    // Bug 3 修复：只在 null 状态时启动 VAD，避免 onShow 重复触发
    // ✅ 使用同步变量判断 TTS 是否正在播放，避免 setData 异步延迟导致误判
    const isTTSPlaying = this._ttsStreamPlaying || this._ttsPlaying || this.data.isPlayingTTS
    if (this.data.sleepModeActive && this._recordingState === null && !this.data.isListening && !this.data.isRecording && !isTTSPlaying) {
      console.log('[onShow] 恢复睡眠模式 VAD')
      this._startVADLoop()
    } else if (isTTSPlaying) {
      console.log('[onShow] AI replying/TTS playing, skip VAD restart')
    }
    // 加载关系开场白（只在文字模式且消息为空时）
    if (this.data.mode === 'text' && this.data.messages.length === 0) {
      this._loadSessionSummary()
    }
  },

  _loadSessionSummary() {
    const userId = app.globalData.userId || ''
    if (!userId) return
    app.authRequest({
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
    // 【修复】等待登录完成 + 等待 userId 不再是临时 ID
    // wxLogin 可能已经在 onLaunch 时完成（1秒内），需要检测是否真的完成了
    const waitForLogin = () => new Promise((resolve) => {
      const userId = app.globalData.userId || ''
      const isTempId = userId.startsWith('user_') && !userId.startsWith('wx_')
      if (!isTempId && userId) {
        resolve()
        return
      }
      // 等 wxLogin 完成（最长等 8 秒）
      let waited = 0
      const interval = setInterval(() => {
        waited += 100
        const uid = app.globalData.userId || ''
        const isTemp = uid.startsWith('user_') && !uid.startsWith('wx_')
        if (!isTemp && uid) {
          clearInterval(interval)
          resolve()
        } else if (waited > 8000) {
          clearInterval(interval)
          console.warn('[_loadChatHistory] 登录超时，使用当前 userId')
          resolve()
        }
      }, 100)
    })
    await waitForLogin()
    // 已加载过或已有消息时不覆盖
    if (this._historyLoaded || this.data.messages.length > 0) return
    this._historyLoaded = true
    const userId = app.globalData.userId || ''
    const sessionId = app.globalData.sessionId || ''
    try {
      const res = await app.authRequest({
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
    // 【修复】等待 wxLogin 完成 + userId 不是临时 ID
    const waitForLogin = () => new Promise((resolve) => {
      const userId = app.globalData.userId || ''
      const isTempId = userId.startsWith('user_') && !userId.startsWith('wx_')
      if (!isTempId && userId) { resolve(); return }
      let waited = 0
      const interval = setInterval(() => {
        waited += 100
        const uid = app.globalData.userId || ''
        const isTemp = uid.startsWith('user_') && !uid.startsWith('wx_')
        if (!isTemp && uid) { clearInterval(interval); resolve() }
        else if (waited > 8000) { clearInterval(interval); resolve() }
      }, 100)
    })
    await waitForLogin()
    const userId = app.globalData.userId || ''
    try {
      const res = await app.authRequest({
        url: `${API}/api/v1/usage`,
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
          app.authRequest({
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
