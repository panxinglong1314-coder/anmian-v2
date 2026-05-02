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

// VAD 参数
const VAD = {
  SILENCE_THRESHOLD: 0.05,
  SPEECH_TIMEOUT: 600,   // 静音 600ms 停止录音
  MIN_UTTERANCE: 300,    // 最少录音 300ms
}

Page({
  data: {
    mode: 'sleep',
    isPremium: false,

    // 睡眠模式
    sleepModeActive: false,
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
    freeChatsLeft: 3,  // 今日剩余对话次数

    // 关闭仪式
    showClosure: false,
    conversationRound: 0,   // 对话轮次计数，达到3轮自动触发关闭仪式
    closureStep: 1,
    breathPhase: 'inhale',
    breathPhaseText: '吸气 4秒',
    breathTip: '用鼻子轻轻吸气...',
    breathCycle: 1,
    breathProgress: 0,
    breathTimer: null,
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

    // 内部
    _listenTimer: null,
    _volumeSim: null,
    _silenceTimer: null,
    _ttsTimer: null,
    _textTtsTimer: null,
    _recordingFilePath: null,
  },

  // ================================================
  // 模式切换
  // ================================================
  goToSubscribe() {
    wx.navigateTo({ url: '/pages/subscribe/subscribe' })
  },

  toggleMode() {
    if (this.data.mode === 'sleep') {
      this.stopAll()
      this.setData({ mode: 'text' })
    } else {
      this.stopAll()
      this.setData({ mode: 'sleep' })
    }
    // 切换模式时更新剩余次数显示
    this._updateFreeChatsDisplay()
  },

  // 更新今日剩余对话次数显示
  _updateFreeChatsDisplay() {
    const limit = this._checkDailyChatLimit()
    this.setData({ 
      freeChatsLeft: limit.remaining,
      isPremium: limit.limit === Infinity
    })
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

  enterSleepMode() {
    this.setData({
      sleepModeActive: true,
      statusText: '聆听中',
      statusHint: '手机放在枕边，开口说话即可',
      conversationRound: 0,
      conversationLog: []
    })
    
    // 激活音频上下文（真机需要）
    innerAudioContext.src = ''
    innerAudioContext.volume = 1.0
    
    this._startVADLoop()
  },

  exitSleepMode() {
    this.stopListening()
    this.stopAll()
    this.setData({
      sleepModeActive: false, isListening: false,
      isRecording: false, audioLevel: 0,
      statusText: '准备入睡',
      statusHint: '点击下方按钮，将手机放在枕边'
    })
  },

  _startVADLoop() {
    if (!this.data.sleepModeActive) return
    this.setData({ isListening: true })

    recorderManager.start({
      format: 'mp3', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 24000, duration: 200
    })

    recorderManager.onStop(res => {
      if (!this._vadActive || !this.data.sleepModeActive) return
      // 用文件大小估算是否有声音
      const hasSound = res.fileSize > 2000
      const level = hasSound ? Math.floor(Math.random() * 4) + 4 : Math.floor(Math.random() * 2)
      this.setData({ audioLevel: level })
      if (hasSound && !this.data.isRecording) {
        this._vadActive = false  // 防止重复触发
        this._start正式录音()
      } else if (this.data.sleepModeActive) {
        this._listenTimer = setTimeout(() => this._startVADLoop(), 50)
      }
    })

    recorderManager.onError(() => {
      if (this.data.sleepModeActive) this._listenTimer = setTimeout(() => this._startVADLoop(), 200)
    })
  },

  _start正式录音() {
    // 停止 VAD，标记为正在录音，防止 VAD onStop 再次触发
    if (this._listenTimer) clearTimeout(this._listenTimer)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    this._vadActive = false
    try { recorderManager.stop() } catch (e) {}
    this.setData({ isRecording: true, isListening: false, audioLevel: 5, statusText: '正在听...', statusHint: '说完后稍等，我会回应' })

    // 开始正式录音（MP3，Whisper 直接支持）
    recorderManager.start({
      format: 'mp3', sampleRate: 16000,
      numberOfChannels: 1, encodeBitRate: 48000, duration: 60000
    })
    recorderManager.onStop((res) => {
      if (!this.data.sleepModeActive) return
      if (res.duration < VAD.MIN_UTTERANCE) {
        this.setData({ isRecording: false, audioLevel: 0 })
        this._startVADLoop()
        return
      }
      this._recordingFilePath = res.tempFilePath
      this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
      this._sendVoiceToASR(res.tempFilePath)
    })
    recorderManager.onError((err) => {
      console.error('[Recorder Error]', err)
      if (this.data.sleepModeActive) {
        this.setData({ isRecording: false, audioLevel: 0 })
        this._startVADLoop()
      }
    })

    this._volumeSim = setInterval(() => {
      if (this.data.isRecording) this.setData({ audioLevel: Math.floor(Math.random() * 5) + 3 })
    }, 150)

    this._silenceTimer = setTimeout(() => {
      if (this.data.sleepModeActive && this.data.isRecording) this._stop正式录音()
    }, VAD.SPEECH_TIMEOUT)
  },

  _stop正式录音() {
    if (this._volumeSim) clearInterval(this._volumeSim)
    if (this._silenceTimer) clearTimeout(this._silenceTimer)
    const filePath = this._recordingFilePath
    this.setData({ isRecording: false, audioLevel: 0, statusText: '正在理解...' })
    recorderManager.stop()
    if (filePath) {
      this._sendVoiceToASR(filePath)
    } else {
      this._playTTS('不好意思没听清楚，你可以慢慢再说一次吗？', true)
    }
  },

  // ================================================
  // 真实 API：ASR 语音转文字（上传后端）
  // ================================================
  async _sendVoiceToASR(filePath) {
    try {
      const res = await wx.uploadFile({
        url: `${API}/api/v1/asr`,
        filePath: filePath,
        name: 'file',
        header: { 'Content-Type': 'multipart/form-data' }
      })
      const json = JSON.parse(res.data)
      const text = (json.text || '').trim()
      if (!text) {
        this._playTTS('不好意思没听清楚，你可以慢慢再说一次吗？', true)
        return
      }
      this._sendToAI(text)
    } catch (e) {
      console.error('[ASR Error]', e)
      this._playTTS('网络有点不稳定，你可以再说一次吗？', true)
    }
  },

  // ================================================
  // 真实 API：AI 对话
  // ================================================
  // ================================================
  // 每日免费对话次数限制
  // ================================================
  _checkDailyChatLimit() {
    const today = new Date().toISOString().split('T')[0]
    const stored = wx.getStorageSync('daily_chat_count') || {}
    const record = stored[today]

    // Premium 用户：无限次
    const sub = wx.getStorageSync('subscription') || {}
    if (sub.isPremium) return { allowed: true, count: 0, limit: Infinity, remaining: Infinity }

    // 首周试用/非付费用户：每天限制3次
    const count = record ? record.count : 0
    const remaining = Math.max(0, 3 - count)
    return { allowed: remaining > 0, count, limit: 3, remaining }
  },

  _incrementDailyChatCount() {
    const today = new Date().toISOString().split('T')[0]
    const stored = wx.getStorageSync('daily_chat_count') || {}
    const record = stored[today] || { count: 0, date: today }
    record.count += 1
    stored[today] = record
    wx.setStorageSync('daily_chat_count', stored)
  },

  async _sendToAI(text, fromSleep = true) {
    const userId = app.globalData.userId
    const sessionId = app.globalData.sessionId

    // ─── 每日免费次数限制（文字模式生效，睡眠模式不限制）───
    if (!fromSleep) {
      const limit = this._checkDailyChatLimit()
      if (!limit.allowed) {
        wx.showModal({
          title: '今日次数已用完',
          content: `首周试用/免费版每日限制3次对话，升级 Premium 享无限对话`,
          confirmText: '升级 Premium',
          cancelText: '明天再来',
          success: res => {
            if (res.confirm) wx.navigateTo({ url: '/pages/subscribe/subscribe' })
          }
        })
        this.setData({ isAIResponding: false })
        return
      }
      // 文字模式计入次数
      this._incrementDailyChatCount()
      this._updateFreeChatsDisplay()
    }

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
      statusText: '正在思考...',
      statusHint: fromSleep ? '收到，请稍等' : ''
    })

    try {
      const res = await wx.request({
        url: `${API}/api/v1/chat`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: { user_id: userId, message: text, session_id: sessionId }
      })

      if (res.statusCode === 200 && res.data.response) {
        const data = res.data
        const responseText = data.response
        const anxietyLevel = data.anxiety?.level || 'normal'

        const newLog = [...this.data.conversationLog, { role: 'user', text }, { role: 'assistant', text: responseText }]
        this.setData({
          conversationLog: newLog,
          isAIResponding: false,
          statusText: '正在播放',
          statusHint: '闭上眼睛，听我说',
          anxiety: { level: anxietyLevel }
        })

        // 播放 TTS
        this._playTTS(responseText, true)

        // ─── 仅文字模式检测关闭仪式，睡眠模式不自动关闭 ───
        if (!fromSleep) {
          const shouldClose = anxietyLevel === 'severe' ||
            responseText.includes('深呼吸') ||
            responseText.includes('静下来') ||
            this.data.conversationRound >= 3
          if (shouldClose) {
            setTimeout(() => this.triggerClosure(), 2500)
          }
        }
      }
    } catch (e) {
      console.error('[Chat Error]', e)
      this.setData({ isAIResponding: false })
      if (fromSleep) {
        // 睡眠模式出错 → TTS 引导用户重试，不中断流程
        this._playTTS('刚才没听清楚，可以再说一遍吗？', true)
      } else {
        this.setData({ statusText: '聆听中', statusHint: '服务暂时不稳定，请重试' })
        if (this.data.sleepModeActive) setTimeout(() => this._startVADLoop(), 2000)
      }
    }
  },

  // ================================================
  // 真实 API：TTS 文字转语音
  // ================================================
  async _playTTS(text, fromSleep = false) {
    if (fromSleep) {
      this.setData({ isPlayingTTS: true, statusText: '正在播放', statusHint: '闭上眼睛，听我说' })
    } else {
      this.setData({ isPlayingTTS: true })
    }

    try {
      const fs = wx.getFileSystemManager()
      const filePath = `${wx.env.USER_DATA_PATH}/tts_${Date.now()}.mp3`

      const res = await wx.request({
        url: `${API}/api/v1/tts?text=${encodeURIComponent(text.slice(0, 500))}&voice=female_warm&speed=0.9`,
        method: 'GET',
        responseType: 'arraybuffer'
      })

      if (res.statusCode === 200 && res.data) {
        fs.writeFile({
          filePath: filePath,
          data: res.data,
          encoding: 'binary',
          success: () => {
            innerAudioContext.stop()
            innerAudioContext.src = ''
            setTimeout(() => {
              innerAudioContext.src = filePath
              innerAudioContext.onError(() => {
                this.setData({ isPlayingTTS: false })
                if (fromSleep && this.data.sleepModeActive) {
                  this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
                  setTimeout(() => this._startVADLoop(), 1000)
                }
              })
              innerAudioContext.onEnded(() => {
                this.setData({ isPlayingTTS: false })
                if (fromSleep && this.data.sleepModeActive) {
                  this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
                  setTimeout(() => this._startVADLoop(), 500)
                }
              })
              innerAudioContext.play()
            }, 100)
          },
          fail: () => {
            this.setData({ isPlayingTTS: false })
            if (fromSleep && this.data.sleepModeActive) {
              this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
              setTimeout(() => this._startVADLoop(), 1000)
            }
          }
        })
      } else {
        // 非 200 → TTS 失败，不递归，直接恢复聆听
        this.setData({ isPlayingTTS: false })
        if (fromSleep && this.data.sleepModeActive) {
          this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
          setTimeout(() => this._startVADLoop(), 1000)
        }
      }
    } catch (e) {
      console.error('[TTS Error]', e)
      this.setData({ isPlayingTTS: false })
      if (fromSleep && this.data.sleepModeActive) {
        this.setData({ statusText: '聆听中', statusHint: '继续说吧' })
        setTimeout(() => this._startVADLoop(), 1000)
      }
    }
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
    try { recorderManager.stop() } catch (e) {}
    try { innerAudioContext.stop() } catch (e) {}
  },

  stopListening() {
    this.stopAll()
    this.setData({ isListening: false, isRecording: false, audioLevel: 0 })
  },

  // ================================================
  // 关闭仪式
  // ================================================
  triggerClosure() {
    this.exitSleepMode()
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
      data: { user_id: app.globalData.userId, bed_hour: bh, bed_min: bm, wake_hour: wh, wake_min: wm },
      fail: () => {}  // non-critical
    })

    // POST to sleep diary bedtime API - 保存今晚睡眠计划
    wx.request({
      url: `${API}/api/v1/sleep/diary/bedtime`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        user_id: app.globalData.userId,
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
    }
  },

  startBreathingInClosure() {
    const phases = [
      { phase: 'inhale', text: '吸气 4秒', tip: '用鼻子轻轻吸气...', duration: 4 },
      { phase: 'hold',   text: '屏息 7秒', tip: '屏住呼吸，保持安静...', duration: 7 },
      { phase: 'exhale',  text: '呼气 8秒', tip: '用嘴缓慢呼出...', duration: 8 }
    ]
    let pIdx = 0, cycle = 1, elapsed = 0, total = 76
    const tick = () => {
      elapsed++
      const p = phases[pIdx]
      const progress = Math.min(Math.floor((elapsed / total) * 100), 100)
      this.setData({ breathPhase: p.phase, breathPhaseText: p.text, breathTip: p.tip, breathCycle: cycle, breathProgress: progress })
      if (elapsed % p.duration === 0) {
        pIdx = (pIdx + 1) % phases.length
        if (pIdx === 0) cycle++
        if (cycle > 4 || elapsed >= total) {
          clearInterval(this.data.breathTimer)
          this.setData({ closureStep: 4 })
          setTimeout(() => this.startPMR(), 300)
          return
        }
      }
    }
    const timer = setInterval(tick, 1000)
    this.setData({ breathTimer: timer })
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
    // 自动关闭倒计时
    this._autoCloseTimer = setTimeout(() => this._autoCloseCeremony(), 4000)
  },

  // PMR TTS 播完自动调用
  onPMRAutoDone() {
    if (this.data.pmrTimer) clearInterval(this.data.pmrTimer)
    this.setData({ closureStep: 2 })
    this._autoCloseTimer = setTimeout(() => this._autoCloseCeremony(), 4000)
  },

  // 自动关闭仪式（屏幕渐暗）
  _autoCloseCeremony() {
    this.setData({ _dimming: true })
    setTimeout(() => {
      this.setData({ showClosure: false, closureStep: 1, _dimming: false })
    }, 2000)
  },

  // 语音跳过：当前阶段直接进下一阶段
  _handleVoiceSkip() {
    const step = this.data.closureStep
    if (step === 1) {
      // Step 1: bedtime setting - skip goes to step 2 or 3
      if (this.data.showWorryPrompt || this.data.worryPendingText) {
        this.setData({ closureStep: 2 })
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
    if (this.data.breathTimer) clearInterval(this.data.breathTimer)
    this.setData({ showClosure: false, closureStep: 1, conversationLog: [] })
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
          data: { user_id: app.globalData.userId, date: today, score }
        })
        this.setData({ showClosure: false, closureStep: 1, conversationLog: [], messages: [] })
        wx.removeStorageSync('chat_history')
      }
    })
  },

  // ================================================
  // 文字模式
  // ================================================
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
  canSendMessage() {
    const sub = wx.getStorageSync('subscription') || {}
    // 付费用户无限
    if (sub.isPremium) return { canSend: true, remaining: Infinity }
    
    // 检查今日已用次数
    const today = new Date().toISOString().split('T')[0]
    const stored = wx.getStorageSync('daily_chat_count') || {}
    const record = stored[today]
    const used = record ? record.count : 0
    const remaining = Math.max(0, 3 - used)
    
    return { canSend: remaining > 0, remaining, used }
  },

  // 记录对话次数
  recordChatUsage() {
    const today = new Date().toISOString().split('T')[0]
    const stored = wx.getStorageSync('daily_chat_count') || {}
    const record = stored[today] || { count: 0, date: today }
    record.count += 1
    stored[today] = record
    wx.setStorageSync('daily_chat_count', stored)
    return record.count
  },

  async onUserMessage(text) {
    // 检查次数限制
    const check = this.canSendMessage()
    if (!check.canSend) {
      wx.showModal({
        title: '今日次数已用完',
        content: '首周试用/免费版每日限制3次对话，升级 Premium 享无限对话',
        confirmText: '升级 Premium',
        cancelText: '明天再来',
        success: (res) => {
          if (res.confirm) {
            wx.navigateTo({ url: '/pages/subscribe/subscribe' })
          }
        }
      })
      return
    }
    
    // 记录次数
    this.recordChatUsage()
    
    const msgs = [...this.data.messages, { id: Date.now(), role: 'user', content: text, time: this._now(), isPlayingTTS: false }]
    this.setData({ messages: msgs, isLoading: true })

    try {
      const res = await wx.request({
        url: `${API}/api/v1/chat`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: { user_id: app.globalData.userId, message: text, session_id: app.globalData.sessionId }
      })
      if (res.statusCode === 200 && res.data.response) {
        const responseText = res.data.response
        const aiMsg = { id: Date.now() + 1, role: 'assistant', content: responseText, time: this._now(), isPlayingTTS: false }
        const msgs2 = [...this.data.messages, aiMsg]
        this.setData({ messages: msgs2, isLoading: false })
        this.saveChatHistory(msgs2)
        // 自动播放 TTS
        setTimeout(() => this.playAITTS(msgs2.length - 1), 300)
        // 触发关闭仪式
        if (responseText.includes('深呼吸') || responseText.includes('静下来')) {
          setTimeout(() => this.triggerClosure(), 2000)
        }
      }
    } catch (e) {
      console.error('[Chat Error]', e)
      this.setData({ isLoading: false })
    }
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
      if (res.duration >= 500) {
        // 真实 ASR
        wx.uploadFile({
          url: `${API}/api/v1/asr`,
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

  // 文字模式 TTS
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
        url: `${API}/api/v1/tts?text=${encodeURIComponent(msg.content.slice(0, 500))}&voice=female_warm&speed=0.9`,
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
  // 白噪音
  // ================================================
  async playSound(e) {
    const soundId = e.currentTarget.dataset.id
    if (this.data.currentSound === soundId) {
      innerAudioContext.stop()
      this.setData({ currentSound: null })
      return
    }
    try {
      const res = await wx.request({ url: `${API}/api/v1/sounds/${soundId}/url` })
      if (res.statusCode === 200 && res.data.url) {
        innerAudioContext.stop()
        innerAudioContext.src = res.data.url
        innerAudioContext.loop = true
        innerAudioContext.volume = 0.6
        innerAudioContext.play()
        this.setData({ currentSound: soundId })
      }
    } catch (e) {
      console.error('[Sound Error]', e)
    }
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
    const userId = app.globalData.userId
    const sessionId = app.globalData.sessionId

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
      
      // 睡眠模式：TTS 播完后重新开始监听
      if (this.data.sleepModeActive && !this.data._pmrActive) {
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

    // 处理「重新审视担忧」跳转
    const revisitText = wx.getStorageSync('revisit_worry_text')
    if (revisitText) {
      wx.removeStorageSync('revisit_worry_text')
      // 延迟发消息，等页面加载完成
      setTimeout(() => {
        this.onUserMessage(`重新审视：${revisitText}`)
      }, 500)
    }
  },
  onShow() {
    const h = wx.getStorageSync('chat_history') || []
    if (h.length > 0) this.setData({ messages: h })
    // 更新剩余对话次数显示
    this._updateFreeChatsDisplay()
  },
  onHide() { this.stopAll() },
  onUnload() {
    this.stopAll()
    if (this.data.breathTimer) clearInterval(this.data.breathTimer)
    if (this._textTtsTimer) clearInterval(this._textTtsTimer)
  }
})
