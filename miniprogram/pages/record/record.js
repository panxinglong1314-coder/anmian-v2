// pages/record/record.js - v2: 睡眠追踪 + 月度报告 + 分享

const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

// 封装 wx.request，30秒硬兜底防止开发者工具网络层异常
function _apiReq(url, data, extra = {}) {
  return new Promise((resolve) => {
    let resolved = false
    const doResolve = (res) => {
      if (!resolved) { resolved = true; resolve(res) }
    }
    const timer = setTimeout(() => {
      console.warn('[API timeout]', url)
      doResolve({ statusCode: 0, data: null, _timeout: true })
    }, 30000)
    app.authRequest({
      url,
      data,
      timeout: 30000,
      ...extra,
      success: (res) => { clearTimeout(timer); doResolve(res) },
      fail: (err) => { clearTimeout(timer); console.warn('[API fail]', url, err); doResolve({ statusCode: 0, data: null }) },
    })
  })
}

Page({
  data: {
    isLoading: false,  // 页面加载状态

    // 统计数据
    stats: { streak: 7, total: 21 },

    // Morning Check-in
    showMorningCheckPrompt: false,
    showMorningCheck: false,
    morningStep: 0,  // 0=not started, 1-4=questions, 5=done
    morningAnswers: {
      bedTimeEstimate: '',
      wakeCount: 0,
      wakeTimeEstimate: '',
      sleepQuality: 0,
    },
    morningQuestions: [
      { q: '昨晚大约几点睡着的？', options: ['22:00前', '22-23点', '23-24点', '凌晨1点后'], key: 'bedTimeEstimate' },
      { q: '夜里有没有醒？醒了几次？', options: ['没醒', '1次', '2次', '3次以上'], key: 'wakeCount', values: [0,1,2,3] },
      { q: '今早几点起的？', options: ['5-6点', '6-7点', '7-8点', '8点后'], key: 'wakeTimeEstimate' },
      { q: '今早整体感觉？', options: ['😫很差', '😐一般', '😊不错', '🤩很好'], key: 'sleepQuality', values: [1,2,3,4] },
    ],
    morningSE: null,
    morningTST: null,
    morningReportDone: false,

    // 睡眠追踪
    todayDate: '',
    showSleepRating: false,  // 早上弹出评分
    sleepRating: 0,
    sleepLabels: ['很差', '较差', '一般', '较好', '很好'],
    sleepScore: '--',
    sleepScoreColor: '#8BA3B9',
    sleepData: { bedTime: '--:--', wakeTime: '--:--', duration: '--' },
    weeklySleep: [
      { day: '一', hours: 6.5, quality: 'fair' },
      { day: '二', hours: 7.2, quality: 'good' },
      { day: '三', hours: 5.8, quality: 'poor' },
      { day: '四', hours: 7.0, quality: 'good' },
      { day: '五', hours: 6.2, quality: 'fair' },
      { day: '六', hours: 8.0, quality: 'good' },
      { day: '日', hours: 8.5, quality: 'good' },
    ],

    // 睡眠效率仪表盘
    showSleepDashboard: false,
    sheetMode: 'view',  // 'view' | 'record'
    todayDiaryWritten: false,  // 今日是否已填写睡眠日记
    // 睡眠日记记录表单
    diaryBedTime: '23:00',
    diaryWakeTime: '07:00',
    diarySleepLatency: 15,
    diaryWakeCount: 0,
    diaryQuality: 3,
    diaryNote: '',
    wakeCountOptions: [
      { label: '没醒', value: 0 },
      { label: '1次', value: 1 },
      { label: '2次', value: 2 },
      { label: '3次+', value: 3 },
    ],
    qualityOptions: [
      { label: '很差', emoji: '😫', value: 1 },
      { label: '较差', emoji: '😟', value: 2 },
      { label: '一般', emoji: '😐', value: 3 },
      { label: '较好', emoji: '😊', value: 4 },
      { label: '很好', emoji: '🤩', value: 5 },
    ],
    sleepDashboard: {
      hasData: false,
      stats: null,
      trend: [],
      recommendation: null,
      trendDirection: '',
      trendEmoji: '',
      srt: null,
      srtPhaseColor: '#8BA3B9',
    },

    // 焦虑趋势
    weekly: [
      { day: '一', score: 3, level: 'mild' },
      { day: '二', score: 5, level: 'moderate' },
      { day: '三', score: 2, level: 'mild' },
      { day: '四', score: 6, level: 'moderate' },
      { day: '五', score: 4, level: 'mild' },
      { day: '六', score: 1, level: 'normal' },
      { day: '日', score: 1, level: 'normal' },
    ],
    insight: '整体呈下降趋势，周末明显好转 🌙',

    // 担忧箱
    worryBoxExpanded: false,
    worryList: [],
    unreviewedCount: 0,

    // 用户信息
    userInfo: null,

    // 睡眠限制
    sleepRestriction: null,
    restrictionPhaseClass: '',
    planStats: null,

    // 月度报告
    reportMonth: '',
    showReport: false,
    reportData: {
      totalDays: 12,
      totalChats: 18,
      avgAnxiety: '2.3',
      topConcern: '工作',
      trend: '↓ 改善中',
      concerns: [
        { name: '工作', count: 8, percent: 80 },
        { name: '人际', count: 5, percent: 50 },
        { name: '未来', count: 3, percent: 30 },
        { name: '健康', count: 2, percent: 20 },
      ],
      thisWeekTrend: 'down',
      thisWeekScore: '2.1',
      lastWeekScore: '3.4',
      aiSummary: '这个月你记录了12天，有18次对话。工作是你主要的焦虑来源，但相比上周，焦虑水平整体下降了37%。好消息是周末的焦虑明显低于工作日——说明休息对你的效果很明显。继续坚持睡前对话，它正在帮你建立更好的睡眠习惯。🌙',
    },
  },

  onLoad() {
    this.initDate()
    this.loadUserInfo()
    this.loadData()
    this.checkSleepRating()
    this.initShare()
    this.checkMorningStatus()
  },

  onShow() {
    this.loadData(true)
    this.loadUserInfo()
  },

  // 加载用户信息
  async loadUserInfo() {
    const token = app.getToken()
    if (!token) return
    try {
      const res = await app.authRequest({
        url: `${API}/api/v1/user/profile`,
        method: 'GET',
        header: { Authorization: `Bearer ${token}` },
        timeout: 15000,
      })
      if (res.statusCode === 200 && res.data) {
        this.setData({ userInfo: res.data })
      }
    } catch (e) {
      console.error('[loadUserInfo]', e)
    }
  },

  // 跳转到个人中心
  goToProfile() {
    wx.navigateTo({ url: '/pages/profile/profile' })
  },

  initDate() {
    const now = new Date()
    const today = `${now.getMonth() + 1}月${now.getDate()}日`
    const reportMonth = `${now.getMonth() + 1}月`
    const weekdays = ['日','一','二','三','四','五','六']
    const weekday = weekdays[now.getDay()]
    this.setData({
      todayDate: `今天 ${today} 周${weekday}`,
      reportMonth,
    })
  },

  async loadData(silent = false) {
    const userId = app.globalData.userId
    console.log('[Record] loadData start, userId=', userId)
    if (!silent) this.setData({ isLoading: true })
    try {
      const [recordsRes, memoryRes, worriesRes, dashboardRes, restrictionRes] = await Promise.all([
        _apiReq(`${API}/api/v1/sleep/records/${userId}?limit=7`),
        _apiReq(`${API}/api/v1/memory/${userId}`),
        _apiReq(`${API}/api/v1/worries/${userId}?limit=20`),
        _apiReq(`${API}/api/v1/sleep/dashboard?user_id=${userId}&days=7`),
        _apiReq(`${API}/api/v1/sleep/restriction?user_id=${userId}`),
      ])

      console.log('[Record] recordsRes', recordsRes.statusCode, recordsRes.data?.stats)
      if (recordsRes.statusCode === 200 && recordsRes.data) {
        const d = recordsRes.data
        const records = d.records || []
        const weekly = records.length
        const streak = d.stats?.streak_days || 0
        const totalMinutes = d.stats?.total_minutes || 0
        const totalRecords = d.stats?.total_records || 0
        const latestScore = d.stats?.latest_score || 0
        // 平均每天睡眠时长（小时），保留1位小数
        const hoursPerDay = totalRecords > 0 ? Math.round(totalMinutes / totalRecords / 60 * 10) / 10 : 0
        let sleepScoreColor = '#8BA3B9'
        if (latestScore >= 80) sleepScoreColor = '#7EC8A3'
        else if (latestScore >= 60) sleepScoreColor = '#F5C869'
        else if (latestScore > 0) sleepScoreColor = '#E8846B'
        this.setData({
          'stats.total': hoursPerDay,
          'stats.streak': streak,
          // 空状态也显示 0/7，不打断用户预期
          planStats: { weekly, target: 7, streak },
          // 检查今日是否已记录睡眠（records 按日期倒序，第一条是今天则已记录）
          todayDiaryWritten: records.length > 0 && this._isToday(records[0].recorded_at),
          // 最新综合睡眠评分(0-100)
          sleepScore: latestScore > 0 ? latestScore : '--',
          sleepScoreColor,
          sleepRating: latestScore > 0 ? Math.min(5, Math.max(1, Math.ceil(latestScore / 20))) : 0,
        })
        console.log('[Record] planStats set', { weekly, target: 7, streak })
      }
      console.log('[Record] worriesRes', worriesRes.statusCode, worriesRes.data?.unreviewed_count)
      if (worriesRes.statusCode === 200 && worriesRes.data) {
        const worries = (worriesRes.data.records || []).map(r => ({
          ...r,
          dateStr: r.recorded_at ? new Date(r.recorded_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '',
          expanded: false,
        }))
        this.setData({
          worryList: worries,
          unreviewedCount: worriesRes.data.unreviewed_count || 0,
        })
        console.log('[Record] unreviewedCount set', worriesRes.data.unreviewed_count || 0)
      }
      console.log('[Record] dashboardRes', dashboardRes.statusCode, dashboardRes.data?.has_data)
      if (dashboardRes.statusCode === 200 && dashboardRes.data) {
        this.updateSleepDashboard(dashboardRes.data)
      }
      console.log('[Record] restrictionRes', restrictionRes.statusCode, restrictionRes.data?.phase)
      if (restrictionRes.statusCode === 200 && restrictionRes.data && restrictionRes.data.phase) {
        const phase = restrictionRes.data.phase
        const phaseClass = phase === 'learning' ? 'phase-learning'
          : phase === 'stable' ? 'phase-stable'
          : phase === 'optimizing' ? 'phase-optimizing'
          : phase === 'restricting' ? 'phase-restricting'
          : ''
        this.setData({ sleepRestriction: restrictionRes.data, restrictionPhaseClass: phaseClass })
      }
    } catch (e) {
      console.error('[Record loadData]', e)
    } finally {
      this.setData({ isLoading: false })
    }
    console.log('[Record] loadData end, stats=', this.data.stats, 'planStats=', this.data.planStats, 'unreviewed=', this.data.unreviewedCount, 'restriction=', !!this.data.sleepRestriction)
    // 生成焦虑趋势分析
    this._generateInsight()
  },

  // 动态生成焦虑趋势分析建议
  _generateInsight() {
    const weekly = this.data.weekly
    if (!weekly || weekly.length === 0) return

    const scores = weekly.map(d => d.score || 0)
    const avg = scores.reduce((a, b) => a + b, 0) / scores.length
    const max = Math.max(...scores)
    const maxDay = weekly.find(d => d.score === max)?.day || ''

    // 计算趋势（前3天 vs 后3天）
    const firstHalf = scores.slice(0, Math.floor(scores.length / 2))
    const secondHalf = scores.slice(Math.floor(scores.length / 2))
    const firstAvg = firstHalf.reduce((a, b) => a + b, 0) / firstHalf.length
    const secondAvg = secondHalf.reduce((a, b) => a + b, 0) / secondHalf.length
    const trend = secondAvg < firstAvg ? '下降' : secondAvg > firstAvg ? '上升' : '持平'

    // 周末 vs 工作日（假设最后2天是周末）
    const weekend = scores.slice(-2)
    const workday = scores.slice(0, -2)
    const weekendAvg = weekend.reduce((a, b) => a + b, 0) / weekend.length
    const workdayAvg = workday.reduce((a, b) => a + b, 0) / workday.length

    let insight = ''
    if (avg < 2) {
      insight = '这周焦虑水平很低，做得很好 🌿 继续保持'
    } else if (avg < 3.5) {
      if (trend === '下降') {
        insight = `整体在好转，继续加油${maxDay ? `，注意周${maxDay}` : ''} 🌱`
      } else if (weekendAvg < workdayAvg - 1) {
        insight = '周末焦虑明显低于工作日——休息对你很有效 💤'
      } else {
        insight = `整体平稳${maxDay ? `，周${maxDay}稍高` : ''}，睡前对话继续 🌙`
      }
    } else if (avg < 5) {
      if (trend === '下降') {
        insight = `焦虑在逐步缓解${maxDay ? `，重点关注周${maxDay}` : ''}，坚持就是胜利 💪`
      } else if (workdayAvg - weekendAvg > 1.5) {
        insight = '工作日焦虑明显更高——试试白天安排更多休息间隙 🌤️'
      } else {
        insight = `最近焦虑较明显${maxDay ? `，周${maxDay}最重` : ''}，睡前对话能帮你缓解 🫂`
      }
    } else {
      insight = '这周焦虑水平较高，建议每天预留睡前时间，睡前对话值得坚持 🫶'
    }

    this.setData({ insight })
  },

  // 更新睡眠效率仪表盘
  updateSleepDashboard(data) {
    if (!data.has_data) {
      this.setData({
        'sleepDashboard.hasData': false,
        'sleepDashboard.stats': null
      })
      return
    }

    // 更新睡眠追踪数据
    const trend = data.trend || []
    const weeklySleep = trend.slice(0, 7).map((r, idx) => {
      const days = ['日', '一', '二', '三', '四', '五', '六']
      const date = new Date(r.date)
      const dayName = days[date.getDay()]
      let quality = 'fair'
      if (r.se >= 85) quality = 'good'
      else if (r.se < 70) quality = 'poor'
      return {
        day: dayName,
        hours: r.tst_hours || 0,
        quality: quality,
        se: r.se,
        date: r.date
      }
    }).reverse()

    // 更新最新睡眠数据
    const latest = trend[0] || {}
    this.setData({
    // SRT数据处理
    let srtPhaseColor = "#8BA3B9"
    if (data.srt) {
      const phase = data.srt.phase
      if (phase === "restricting") srtPhaseColor = "#E8846B"
      else if (phase === "stabilizing") srtPhaseColor = "#7EC8A3"
      else if (phase === "optimizing") srtPhaseColor = "#F5C869"
      else if (phase === "maintenance") srtPhaseColor = "#6B9FD4"
    }
      'sleepDashboard.hasData': true,
      'sleepDashboard.stats': data.stats,
      'sleepDashboard.trend': trend,
      'sleepDashboard.recommendation': data.recommendation,
      'sleepDashboard.trendDirection': data.trend_direction,
      'sleepDashboard.trendEmoji': data.trend_emoji,
      'sleepDashboard.srt': data.srt || null,
      'sleepDashboard.srtPhaseColor': srtPhaseColor,
      'weeklySleep': weeklySleep.length > 0 ? weeklySleep : this.data.weeklySleep,
      'sleepData': {
        bedTime: latest.actual_bed || latest.planned_bed || '--:--',
        wakeTime: latest.planned_bed ? this.calculateWakeTime(latest.planned_bed, data.stats?.avg_tst_hours) : '--:--',
        duration: `${data.stats?.avg_tst_hours || '--'}小时`
      }
    })
  },

  // 计算起床时间
  calculateWakeTime(bedTime, hours) {
    if (!bedTime || !hours) return '--:--'
    const [h, m] = bedTime.split(':').map(Number)
    const totalMinutes = h * 60 + m + hours * 60
    const wakeH = Math.floor(totalMinutes / 60) % 24
    const wakeM = Math.floor(totalMinutes % 60)
    return `${String(wakeH).padStart(2, '0')}:${String(wakeM).padStart(2, '0')}`
  },

  // 显示睡眠效率仪表盘（默认查看模式）
  showSleepDashboardPanel() {
    this.setData({ sheetMode: 'view', showSleepDashboard: true })
  },

  // 从晨起提示直接打开记录模式
  openSleepRecordSheet() {
    this.setData({ sheetMode: 'record', showSleepDashboard: true })
  },

  // 隐藏睡眠效率仪表盘
  
  // 应用SRT推荐睡眠窗口
  applySrtRecommendation() {
    const srt = this.data.sleepDashboard.srt
    if (!srt || !srt.adjustment_needed) {
      wx.showToast({ title: '无需调整', icon: 'none' })
      return
    }
    wx.showLoading({ title: '应用中...' })
    const app = getApp()
    wx.request({
      url: app.globalData.baseUrl + '/api/v1/srt/apply',
      method: 'POST',
      header: { Authorization: 'Bearer ' + app.globalData.token },
      success: (res) => {
        wx.hideLoading()
        if (res.data.status === 'ok') {
          wx.showToast({ title: '已更新睡眠窗口', icon: 'success' })
          this.hideSleepDashboard()
          this.onShow()
        } else {
          wx.showToast({ title: res.data.message || '更新失败', icon: 'none' })
        }
      },
      fail: () => {
        wx.hideLoading()
        wx.showToast({ title: '网络错误', icon: 'none' })
      }
    })
  },


hideSleepDashboard() {
    this.setData({ showSleepDashboard: false })
  },

  // 判断某 ISO 时间戳是否是今天
  _isToday(isoString) {
    if (!isoString) return false
    const d = new Date(isoString)
    const now = new Date()
    return d.getFullYear() === now.getFullYear()
      && d.getMonth() === now.getMonth()
      && d.getDate() === now.getDate()
  },

  // 切换到记录模式（在查看模式弹窗内点击"记录今早睡眠"）
  switchToRecordMode() {
    this.setData({ sheetMode: 'record' })
  },

  // 滚动到焦虑趋势区块
  scrollToAnxiety() {
    wx.createSelectorQuery().select('#anxiety-section').boundingClientRect(rect => {
      if (rect) {
        wx.pageScrollTo({ scrollTop: rect.top - 20, duration: 300 })
      }
    }).exec()
  },

  // ========== 睡眠评分 ==========
  checkSleepRating() {
    // 读取上次评分时间，如果今天还没评就弹出
    const lastRating = wx.getStorageSync('last_sleep_rating_date')
    const today = new Date().toISOString().split('T')[0]
    const lastRatingTime = wx.getStorageSync('last_sleep_rating_time')
    const nowHour = new Date().getHours()

    // 只在早上（6-12点）弹出
    if (nowHour >= 6 && nowHour <= 12 && lastRatingTime !== today) {
      this.setData({ showSleepRating: true })
    }

    // 睡眠分：优先使用 this.data 中已加载的值，无数据时回退到本地缓存
    let sleepScore = this.data.sleepScore
    if (!sleepScore || sleepScore === '--') {
      sleepScore = wx.getStorageSync('last_sleep_score') || 0
    }
    if (sleepScore > 0) {
      let sleepScoreColor = '#8BA3B9'
      if (sleepScore >= 80) sleepScoreColor = '#7EC8A3'
      else if (sleepScore >= 60) sleepScoreColor = '#F5C869'
      else sleepScoreColor = '#E8846B'
      this.setData({
        sleepScore,
        sleepScoreColor,
        sleepRating: Math.min(5, Math.max(1, Math.ceil(sleepScore / 20))),
      })
    }
  },

  rateSleep(e) {
    const score = e.currentTarget.dataset.score
    const today = new Date().toISOString().split('T')[0]
    wx.setStorageSync('last_sleep_rating_date', today)
    wx.setStorageSync('last_sleep_rating_time', today)
    wx.setStorageSync('last_sleep_score', score)

    const colors = ['#E8846B','#E8846B','#F5C869','#7EC8A3','#7EC8A3']
    this.setData({
      sleepRating: score,
      sleepScore: score,
      sleepScoreColor: colors[score - 1],
      showSleepRating: false,
    })

    // 上报给后端
    app.authRequest({
      url: `${API}/api/v1/sleep/record`,
      method: 'POST',
      data: { user_id: app.globalData.userId, date: today, score },
    })
  },

  // ========== 担忧箱（CBT 担忧时间箱）==========

  goToWorryBox() {
    wx.navigateTo({ url: '/pages/worries/worries' })
  },

  toggleWorryBox() {
    this.setData({ worryBoxExpanded: !this.data.worryBoxExpanded })
  },

  toggleWorryItem(e) {
    const idx = e.currentTarget.dataset.index
    const list = [...this.data.worryList]
    list[idx] = { ...list[idx], expanded: !list[idx].expanded }
    this.setData({ worryList: list })
  },

  async markWorryReviewed(e) {
    const worryId = e.currentTarget.dataset.worryId
    const idx = e.currentTarget.dataset.index
    try {
      await app.authRequest({
        url: `${API}/api/v1/worry/${worryId}`,
        method: 'PATCH',
        data: { reviewed: true },
      })
      const list = [...this.data.worryList]
      list[idx] = { ...list[idx], reviewed: true, expanded: false }
      const unreviewedCount = Math.max(0, this.data.unreviewedCount - 1)
      this.setData({ worryList: list, unreviewedCount })
      wx.showToast({ title: '已处理 ✓', icon: 'none', duration: 1500 })
    } catch (e) {
      console.error('[markWorryReviewed]', e)
    }
  },

  revisitWorry(e) {
    // 跳转到聊天页面重新审视这条担忧
    const worryText = e.currentTarget.dataset.worry
    wx.setStorageSync('revisit_worry_text', worryText)
    wx.switchTab({ url: '/pages/chat/chat' })
  },

  // ========== 月度报告 ==========
  showMonthlyReport() {
    this.setData({ showReport: true })
    this.generateReportData()
  },

  hideReport() {
    this.setData({ showReport: false })
  },

  stopProp() {},

  async generateReportData() {
    // 从后端拉本月的汇总数据
    const userId = app.globalData.userId
    try {
      const res = await app.authRequest({
        url: `${API}/api/v1/sleep/records/${userId}?limit=30`,
      })
      if (res.statusCode === 200 && res.data.records) {
        const records = res.data.records
        const totalDays = records.length
        const avgScore = records.length
          ? (records.reduce((s, r) => s + r.score, 0) / records.length).toFixed(1)
          : '--'

        // 从 memory 拿焦虑关键词
        const memRes = await app.authRequest({ url: `${API}/api/v1/memory/${userId}` })
        const mem = memRes.data?.memory || {}
        const concerns = Object.entries(mem.triggers || {})
          .sort((a,b) => b[1]-a[1])
          .slice(0,4)
          .map(([name, count]) => ({
            name,
            count,
            percent: Math.round((count / Math.max(...Object.values(mem.triggers || {}))) * 100)
          }))

        const topConcern = concerns[0]?.name || '待积累'
        const aiSummary = `这个月你记录了${totalDays}天。${topConcern}是你主要的焦虑来源。` +
          `平均焦虑水平为${avgScore}（满分5）。` +
          `继续保持睡前对话，它正在帮你建立更好的睡眠习惯。🌙`

        this.setData({
          'reportData.totalDays': totalDays,
          'reportData.totalChats': totalDays,
          'reportData.avgAnxiety': avgScore,
          'reportData.topConcern': topConcern,
          'reportData.concerns': concerns,
          'reportData.aiSummary': aiSummary,
        })
      }
    } catch (e) {
      console.error('[generateReportData]', e)
    }
  },

  // ========== 分享 ==========
  initShare() {
    // 启用分享
    wx.showShareMenu({ withShareTicket: true })
  },

  onShareAppMessage() {
    const { reportData, reportMonth } = this.data
    return {
      title: `🌙 ${reportMonth}焦虑报告出炉了`,
      desc: `本月记录${reportData.totalDays}天，主要焦虑源：${reportData.topConcern}。` +
            `快来看看我的月度心理健康报告！`,
      path: '/pages/record/record',
      imageUrl: '', // 可选：生成海报图
    }
  },

  onShareTimeline() {
    // 分享到朋友圈
    const { reportData, reportMonth } = this.data
    return {
      title: `🌙 ${reportMonth}焦虑报告 | ${reportData.topConcern}为主要焦虑源`,
      query: `from=timeline&user_id=${app.globalData.userId}`,
    }
  },

  async onShare() {
    // 主动分享面板
    wx.showShareMenu({ withShareTicket: true })
    wx.showModal({
      title: '分享到',
      confirmText: '分享周报',
      cancelText: '取消',
      success: () => {
        // 触发小程序内分享
      }
    })
  },

  // ========== Morning Check-in ==========
  async checkMorningStatus() {
    const now = new Date()
    const hour = now.getHours()
    if (hour < 7 || hour > 12) return  // not morning hours
    console.log('[Morning] hour=', hour, 'check status')

    try {
      const res = await app.authRequest({
        url: `${API}/api/v1/morning/check?user_id=${app.globalData.userId}`,
      })
      if (res.statusCode === 200 && !res.data.completed) {
        this.setData({ showMorningCheckPrompt: true })
      }
    } catch(e) {}
  },

  openMorningCheck() {
    this.setData({ showMorningCheck: true, morningStep: 1 })
  },

  onMorningAnswer(e) {
    const { answer, index } = e.currentTarget.dataset
    const step = this.data.morningStep
    const question = this.data.morningQuestions[step - 1]
    const key = question.key
    let value = answer
    if (question.values) {
      value = question.values[index]
    }
    this.setData({
      [`morningAnswers.${key}`]: value,
    })

    if (step < 4) {
      this.setData({ morningStep: step + 1 })
    } else {
      this.calculateMorningSE()
      this.submitMorningCheck()
    }
  },

  calculateMorningSE() {
    const { bedTimeEstimate, wakeCount, wakeTimeEstimate } = this.data.morningAnswers
    // Map estimates to hours
    const bedMap = { '22:00前': 21.5, '22-23点': 22.5, '23-24点': 23.5, '凌晨1点后': 1.5 }
    const wakeMap = { '5-6点': 5.5, '6-7点': 6.5, '7-8点': 7.5, '8点后': 8.5 }

    const bedHour = bedMap[bedTimeEstimate] || 23
    let wakeHour = wakeMap[wakeTimeEstimate] || 7
    if (wakeHour < bedHour) wakeHour += 24  // handle overnight

    const TIB = 9  // assumed time in bed = 9 hours
    const wakeFactor = Math.max(0, 3 - wakeCount) / 3  // reduce for awakenings
    const TST = Math.min((wakeHour - bedHour) * wakeFactor, TIB)
    const SE = Math.round((TST / TIB) * 100)

    this.setData({
      morningSE: SE,
      morningTST: TST.toFixed(1) + 'h',
      morningStep: 5,
    })
  },

  async submitMorningCheck() {
    const ans = this.data.morningAnswers
    const bedSetting = wx.getStorageSync('bed_time_setting') || {}

    // 映射前端文字回答 → 后端格式
    const bedMap = { '22:00前': '21:30', '22-23点': '22:30', '23-24点': '23:30', '凌晨1点后': '01:30' }
    const wakeMap = { '5-6点': '05:30', '6-7点': '06:30', '7-8点': '07:30', '8点后': '08:30' }

    const bed_time_estimate = bedMap[ans.bedTimeEstimate] || '23:00'
    const wake_time_estimate = wakeMap[ans.wakeTimeEstimate] || '07:00'
    const wake_count = typeof ans.wakeCount === 'number' ? ans.wakeCount : 0
    const sleep_quality = typeof ans.sleepQuality === 'number' ? ans.sleepQuality : 3

    // 从 storage 读睡眠窗口（由 chat 的 submitBedTime 写入）
    const sw = wx.getStorageSync('bed_time_setting') || {}
    const sleep_window_start = `${String(sw.bedHour !== undefined ? sw.bedHour : 23).padStart(2,'0')}:${String(sw.bedMin || 0).padStart(2,'0')}`
    const sleep_window_end   = `${String(sw.wakeHour !== undefined ? sw.wakeHour : 7).padStart(2,'0')}:${String(sw.wakeMin || 0).padStart(2,'0')}`

    try {
      await app.authRequest({
        url: `${API}/api/v1/morning/submit`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: {
          user_id: app.globalData.userId,
          bed_time_estimate,
          wake_count,
          wake_time_estimate,
          sleep_quality,
          sleep_window_start,
          sleep_window_end,
        },
      })
    } catch(e) {
      console.error('[submitMorningCheck]', e)
    }
  },

  closeMorningCheck() {
    this.setData({
      showMorningCheck: false,
      showMorningCheckPrompt: false,
      morningStep: 0,
      morningAnswers: { bedTimeEstimate: '', wakeCount: 0, wakeTimeEstimate: '', sleepQuality: 0 },
      morningSE: null,
      morningTST: null,
      morningReportDone: true,
    })
  },

  preventTouchMove() {},

  async shareReport() {
    // 生成报告图片并分享
    wx.showShareMenu({ withShareTicket: true })
    wx.showToast({ title: '轻触右上角分享', icon: 'none', duration: 2000 })
  },

  goToTrain() {
    wx.navigateTo({ url: '/pages/train/train' })
  },

  async applySleepRestriction() {
    const r = this.data.sleepRestriction
    if (!r || !r.adjustment_needed) return
    try {
      const res = await app.authRequest({
        url: `${API}/api/v1/sleep/restriction/apply`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: {
          user_id: app.globalData.userId,
          recommended_bed_time: r.recommended_bed_time,
          recommended_wake_time: r.recommended_wake_time,
        },
      })
      if (res.statusCode === 200) {
        wx.showToast({ title: '已更新睡眠窗口', icon: 'success' })
        // 刷新数据
        this.loadData()
      } else {
        wx.showToast({ title: '更新失败', icon: 'none' })
      }
    } catch (e) {
      console.error('[applySleepRestriction]', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    }
  },

  // ========== 睡眠日记表单 ==========
  onDiaryBedTimeChange(e) {
    this.setData({ diaryBedTime: e.detail.value })
  },
  onDiaryWakeTimeChange(e) {
    this.setData({ diaryWakeTime: e.detail.value })
  },
  onDiarySleepLatencyChange(e) {
    this.setData({ diarySleepLatency: e.detail.value })
  },
  onDiaryWakeCountChange(e) {
    this.setData({ diaryWakeCount: e.currentTarget.dataset.value })
  },
  onDiaryQualityChange(e) {
    this.setData({ diaryQuality: e.currentTarget.dataset.value })
  },
  onDiaryNoteChange(e) {
    this.setData({ diaryNote: e.detail.value })
  },

  async submitDiary() {
    const { diaryBedTime, diaryWakeTime, diarySleepLatency, diaryWakeCount, diaryQuality, diaryNote } = this.data
    const userId = app.globalData.userId
    if (!userId) return
    wx.showLoading({ title: '保存中...', mask: true })
    try {
      const res = await app.authRequestAsync({
        url: `${API}/api/v1/sleep/diary`,
        method: 'POST',
        header: { 'Content-Type': 'application/json' },
        data: {
          user_id: userId,
          bed_time: diaryBedTime,
          wake_time: diaryWakeTime,
          sleep_latency_minutes: diarySleepLatency,
          wake_count: diaryWakeCount,
          quality: diaryQuality,
          note: diaryNote,
        },
      })
      wx.hideLoading()
      if (res.statusCode === 200 || res.statusCode === 201) {
        wx.showToast({ title: '已保存', icon: 'success' })
        this.setData({ showSleepDashboard: false, todayDiaryWritten: true })
        this.loadData()
      } else {
        wx.showToast({ title: '保存失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      console.error('[submitDiary]', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    }
  },
})
