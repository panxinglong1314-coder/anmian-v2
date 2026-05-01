// pages/morning/morning.js
// Tab 3: 早晨回访 - 1分钟睡眠日记对话

const app = getApp()
const recorderManager = wx.getRecorderManager()
const innerAudioContext = wx.createInnerAudioContext()

const API = app.globalData.apiBaseUrl

// TTS 参数
const TTS_VOICE = 'female_warm'
const TTS_SPEED = '0.9'

Page({
  data: {
    // 页面状态: checking | not-time | questionnaire | completed | report
    phase: 'checking',

    // 日期
    todayDate: '',
    greetingText: '',

    // 睡眠报告（最终展示）
    sleepReport: null,
    sePercent: 0,
    tstHours: 0,
    solMinutes: 0,
    sleepQualityLabel: '',
    sleepQualityEmoji: '',

    // 问卷进度
    currentQuestionIndex: -1,  // -1 = intro, 0-3 = questions
    questions: [
      {
        id: 'bed_time',
        text: '昨晚大约几点睡着的？',
        voiceText: '昨晚大约几点睡着的？',
        options: [
          { label: '22:00前', value: 'before_22', desc: '22:00前' },
          { label: '22-23点', value: '22_23', desc: '22~23点' },
          { label: '23-24点', value: '23_24', desc: '23~24点' },
          { label: '凌晨1点后', value: 'after_1am', desc: '凌晨1点后' },
        ]
      },
      {
        id: 'wake_count',
        text: '夜里有没有醒？醒了几次？',
        voiceText: '夜里有没有醒？醒了几次？',
        options: [
          { label: '没醒', value: 0, desc: '一觉到天亮' },
          { label: '1次', value: 1, desc: '醒来1次' },
          { label: '2次', value: 2, desc: '醒来2次' },
          { label: '3次以上', value: 3, desc: '醒来3次以上' },
        ]
      },
      {
        id: 'wake_time',
        text: '今早几点起的？',
        voiceText: '今早几点起的？',
        options: [
          { label: '5-6点', value: '5_6', desc: '5~6点' },
          { label: '6-7点', value: '6_7', desc: '6~7点' },
          { label: '7-8点', value: '7_8', desc: '7~8点' },
          { label: '8点后', value: 'after_8', desc: '8点后' },
        ]
      },
      {
        id: 'sleep_quality',
        text: '今早整体感觉怎么样？',
        voiceText: '今早整体感觉怎么样？',
        options: [
          { label: '😫很差', value: 1, desc: '很差', emoji: '😫' },
          { label: '😐一般', value: 2, desc: '一般', emoji: '😐' },
          { label: '😊不错', value: 3, desc: '不错', emoji: '😊' },
          { label: '🤩很好', value: 4, desc: '很好', emoji: '🤩' },
        ]
      }
    ],

    // 用户答案
    answers: {
      bed_time: null,
      wake_count: null,
      wake_time: null,
      sleep_quality: null,
    },

    // AI 语音气泡
    aiBubble: null,
    isSpeaking: false,
    ttsProgress: 0,

    // 状态文本
    statusText: '正在检查...',

    // 内部
    _ttsTimer: null,
    _introSpoken: false,
  },

  // ================================================
  // 生命周期
  // ================================================
  onLoad() {
    this._initDate()
    this._checkMorningStatus()
  },

  onShow() {},

  onUnload() {
    this._clearAll()
    try { innerAudioContext.stop() } catch (e) {}
  },

  // ================================================
  // 日期初始化
  // ================================================
  _initDate() {
    const now = new Date()
    const dateStr = `${now.getMonth() + 1}月${now.getDate()}日`
    const weekday = ['周日', '周一', '周二', '周三', '周四', '周五', '周六'][now.getDay()]
    this.setData({
      todayDate: `${dateStr} ${weekday}`,
      greetingText: `早安 🌅`
    })
  },

  // ================================================
  // 检查早晨回访状态
  // ================================================
  _checkMorningStatus() {
    const now = new Date()
    const hour = now.getHours()

    // 检查是否在 7-12 点
    if (hour < 7 || hour >= 12) {
      this.setData({ phase: 'not-time', statusText: '现在不是回访时间，晚些再来' })
      return
    }

    // 检查今天是否已完成
    const userId = app.globalData.userId
    if (!userId) {
      this.setData({ phase: 'not-time', statusText: '用户未登录' })
      return
    }

    wx.request({
      url: `${API}/api/v1/morning/check`,
      method: 'GET',
      data: { user_id: userId },
      success: res => {
        if (res.statusCode === 200 && res.data && res.data.completed) {
          // 今日已完成
          this.setData({
            phase: 'completed',
            sleepReport: res.data.report || null,
            statusText: '今日已完成 ✅'
          })
        } else {
          // 还未完成，开始问卷
          this._startQuestionnaire()
        }
      },
      fail: () => {
        // 网络失败，也开始问卷（离线模式）
        this._startQuestionnaire()
      }
    })
  },

  // ================================================
  // 开始问卷流程
  // ================================================
  _startQuestionnaire() {
    this.setData({ phase: 'questionnaire', currentQuestionIndex: -1 })
    // 延迟播放开场白
    setTimeout(() => this._playIntro(), 600)
  },

  // ================================================
  // 播放开场白
  // ================================================
  _playIntro() {
    const introText = '昨晚睡得怎么样？来回顾一下吧'
    this.setData({ aiBubble: introText, isSpeaking: true })
    this._speakText(introText, () => {
      // 开场白说完后，开始第一个问题
      setTimeout(() => {
        this.setData({ currentQuestionIndex: 0, isSpeaking: false, aiBubble: null })
        setTimeout(() => this._speakCurrentQuestion(), 400)
      }, 300)
    })
  },

  // ================================================
  // 播放当前问题语音
  // ================================================
  _speakCurrentQuestion() {
    const q = this.data.questions[this.data.currentQuestionIndex]
    if (!q) return
    this.setData({ aiBubble: q.text, isSpeaking: true })
    this._speakText(q.voiceText, () => {
      this.setData({ isSpeaking: false })
    })
  },

  // ================================================
  // 选择选项
  // ================================================
  onOptionSelect(e) {
    if (this.data.isSpeaking) return

    const { questionId, value } = e.currentTarget.dataset
    const answers = { ...this.data.answers }
    answers[questionId] = value

    this.setData({ answers })

    // 立即进入下一题
    const nextIndex = this.data.currentQuestionIndex + 1
    if (nextIndex < this.data.questions.length) {
      this.setData({ currentQuestionIndex: nextIndex, aiBubble: null })
      setTimeout(() => this._speakCurrentQuestion(), 400)
    } else {
      // 所有问题回答完毕 → 计算并提交
      setTimeout(() => this._calculateAndSubmit(), 500)
    }
  },

  // ================================================
  // 计算睡眠数据并提交
  // ================================================
  _calculateAndSubmit() {
    this.setData({ aiBubble: null, isSpeaking: true })
    const answers = this.data.answers

    // 读取用户卧床窗口设置
    const bedSettings = wx.getStorageSync('bed_time_setting') || {}
    const {
      bedHour = 22, bedMin = 0,
      wakeHour = 7, wakeMin = 0
    } = bedSettings

    // 计算卧床总时长（分钟）
    let bedWindowMinutes = (wakeHour * 60 + wakeMin) - (bedHour * 60 + bedMin)
    if (bedWindowMinutes < 0) bedWindowMinutes += 24 * 60  // 跨天
    const bedWindowHours = bedWindowMinutes / 60

    // 估算入睡用时（SOL）- 根据入睡时间选项估算
    let sleepOnsetMinutes = 15  // 默认15分钟
    if (answers.bed_time === 'before_22') sleepOnsetMinutes = 10
    else if (answers.bed_time === '22_23') sleepOnsetMinutes = 15
    else if (answers.bed_time === '23_24') sleepOnsetMinutes = 20
    else if (answers.bed_time === 'after_1am') sleepOnsetMinutes = 30

    // 估算夜间醒来总时长（每次醒来约10分钟）
    const wakeMinutes = (answers.wake_count || 0) * 10

    // 实际睡眠时长 TST
    const tstMinutes = bedWindowMinutes - sleepOnsetMinutes - wakeMinutes
    const tstHours = Math.max(0, tstMinutes / 60)

    // 睡眠效率 SE
    const sePercent = bedWindowMinutes > 0 ? Math.round((tstMinutes / bedWindowMinutes) * 100) : 0

    // 睡眠质量等级
    const qualityMap = { 1: '很差', 2: '一般', 3: '不错', 4: '很好' }
    const emojiMap = { 1: '😫', 2: '😐', 3: '😊', 4: '🤩' }
    const sleepQualityLabel = qualityMap[answers.sleep_quality] || '一般'
    const sleepQualityEmoji = emojiMap[answers.sleep_quality] || '😐'

    // 计算睡眠评分（综合 SE + 主观质量）
    let sleepScore = Math.round((sePercent * 0.6) + (answers.sleep_quality * 10 * 0.4))
    sleepScore = Math.min(100, Math.max(0, sleepScore))

    // 映射睡眠窗口
    let sleepWindowStart = `${bedHour.toString().padStart(2, '0')}:${bedMin.toString().padStart(2, '0')}`
    let sleepWindowEnd = `${wakeHour.toString().padStart(2, '0')}:${wakeMin.toString().padStart(2, '0')}`

    this.setData({
      sePercent,
      tstHours: Math.round(tstHours * 10) / 10,
      solMinutes: sleepOnsetMinutes,
      sleepQualityLabel,
      sleepQualityEmoji,
      sleepReport: {
        se: sePercent,
        tst: tstHours,
        sol: sleepOnsetMinutes,
        score: sleepScore,
        quality: sleepQualityLabel,
        qualityEmoji: sleepQualityEmoji,
        bedTime: sleepWindowStart,
        wakeTime: sleepWindowEnd,
        wakeCount: answers.wake_count,
        answers
      }
    })

    // 上报后端
    const userId = app.globalData.userId
    wx.request({
      url: `${API}/api/v1/morning/submit`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        user_id: userId,
        bed_time_estimate: answers.bed_time,
        wake_count: answers.wake_count,
        wake_time_estimate: answers.wake_time,
        sleep_quality: answers.sleep_quality,
        sleep_window_start: sleepWindowStart,
        sleep_window_end: sleepWindowEnd
      },
      success: () => {},
      fail: () => {}
    })

    // 播放完成语音
    const completeText = '回顾完成，来看今天的睡眠报告吧'
    this._speakText(completeText, () => {
      setTimeout(() => {
        this.setData({ phase: 'report', isSpeaking: false })
      }, 500)
    })
  },

  // ================================================
  // 查看我的记录
  // ================================================
  onGoToRecord() {
    wx.switchTab({ url: '/pages/record/record' })
  },

  // ================================================
  // TTS 播放
  // ================================================
  _speakText(text, onEnd) {
    if (this._ttsTimer) clearInterval(this._ttsTimer)

    wx.request({
      url: `${API}/api/v1/tts?text=${encodeURIComponent(text.slice(0, 500))}&voice=${TTS_VOICE}&speed=${TTS_SPEED}`,
      method: 'POST',
      responseType: 'arraybuffer',
      header: { 'Content-Type': 'application/x-www-form-urlencoded' },
      success: res => {
        if (res.statusCode === 200 && res.data) {
          const filePath = `${wx.env.USER_DATA_PATH}/morning_tts_${Date.now()}.mp3`
          wx.getFileSystemManager().writeFile({
            filePath: filePath,
            data: res.data,
            encoding: 'binary',
            success: () => {
              innerAudioContext.src = filePath
              innerAudioContext.play()
              let step = 0
              const total = 40
              this._ttsTimer = setInterval(() => {
                step++
                this.setData({ ttsProgress: Math.min(Math.floor((step / total) * 100), 100) })
                if (step >= total) {
                  clearInterval(this._ttsTimer)
                  this.setData({ ttsProgress: 0 })
                  if (onEnd) onEnd()
                }
              }, 500)
              innerAudioContext.onEnded(() => {
                clearInterval(this._ttsTimer)
                this.setData({ ttsProgress: 0 })
                if (onEnd) onEnd()
              })
            },
            fail: () => { if (onEnd) onEnd() }
          })
        } else {
          if (onEnd) onEnd()
        }
      },
      fail: () => { if (onEnd) onEnd() }
    })
  },

  // ================================================
  // 工具
  // ================================================
  _clearAll() {
    if (this._ttsTimer) clearInterval(this._ttsTimer)
    try { recorderManager.stop() } catch (e) {}
    try { innerAudioContext.stop() } catch (e) {}
  },

  // 计算圆环进度百分比 → CSS conic-gradient 角度
  _seRotation(se) {
    return Math.round((se / 100) * 360)
  }
})
