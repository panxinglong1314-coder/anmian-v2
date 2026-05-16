// pages/worries/worries.js
const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

function _apiReq(url, data, extra = {}) {
  return new Promise((resolve) => {
    wx.request({ url, data, timeout: 10000, ...extra,
      success: (res) => resolve(res),
      fail: () => resolve({ statusCode: 0, data: null }),
    })
  })
}

Page({
  data: {
    worryList: [],
    filteredList: [],
    filter: 'all',
    isLoading: true,
    reviewableCount: 0,    // 适合今天回看（≥3 天未放下）
  },

  onLoad() {
    this.loadWorries()
  },

  _typeMeta(type) {
    // 用更柔和的标签 + emoji 替换原"倾诉型/行动型/反刍型"
    const map = {
      vent:     { emoji: '💭', label: '想倾诉' },
      action:   { emoji: '🎯', label: '想行动' },
      ruminate: { emoji: '🌀', label: '想不通' },
    }
    return map[type] || { emoji: '📝', label: '心事' }
  },

  _timeLabel(recordedAt, daysAgo) {
    if (!recordedAt) return ''
    if (daysAgo === 0) {
      // 今天，显示时间
      return new Date(recordedAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
    }
    if (daysAgo === 1) return '昨天'
    if (daysAgo < 7) return `${daysAgo} 天前`
    if (daysAgo < 30) return `${Math.floor(daysAgo / 7)} 周前`
    return new Date(recordedAt).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' })
  },

  async loadWorries() {
    const userId = app.globalData.userId
    this.setData({ isLoading: true })
    const res = await _apiReq(`${API}/api/v1/worries/${userId}?limit=50`)
    if (res.statusCode === 200 && res.data) {
      const now = new Date()
      now.setHours(0, 0, 0, 0)
      const list = (res.data.records || []).map(r => {
        let daysAgo = 0
        if (r.recorded_at) {
          const d = new Date(r.recorded_at)
          d.setHours(0, 0, 0, 0)
          daysAgo = Math.round((now - d) / 86400000)
        }
        const meta = this._typeMeta(r.type)
        return {
          ...r,
          daysAgo,
          typeEmoji: meta.emoji,
          typeLabel: meta.label,
          timeLabel: this._timeLabel(r.recorded_at, daysAgo),
          dateStr: r.recorded_at ? new Date(r.recorded_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric' }) : '',
          expanded: false,
        }
      })
      const reviewableCount = list.filter(w => w.daysAgo >= 3 && !w.reviewed).length
      this.setData({ worryList: list, filteredList: list, reviewableCount, isLoading: false })
    } else {
      this.setData({ isLoading: false })
    }
  },

  setFilter(e) {
    const filter = e.currentTarget.dataset.filter
    const list = this.data.worryList
    const filtered = filter === 'all' ? list : list.filter(w => w.type === filter)
    this.setData({ filter, filteredList: filtered })
  },

  toggleExpand(e) {
    const idx = e.currentTarget.dataset.index
    const list = [...this.data.filteredList]
    list[idx].expanded = !list[idx].expanded
    this.setData({ filteredList: list })
  },

  async markRead(e) {
    const id = e.currentTarget.dataset.id
    const userId = app.globalData.userId
    const res = await _apiReq(`${API}/api/v1/worry/${id}/review?user_id=${userId}`, {}, { method: 'POST' })
    if (res.statusCode === 200) {
      this.loadWorries()
    }
  },

  async markAllRead() {
    const userId = app.globalData.userId
    const res = await _apiReq(`${API}/api/v1/worries/${userId}/review-all`, {}, { method: 'POST' })
    if (res.statusCode === 200) {
      this.loadWorries()
    }
  },

  revisit(e) {
    const text = e.currentTarget.dataset.text
    wx.setStorageSync('revisit_worry_text', text)
    wx.switchTab({ url: '/pages/chat/chat' })
  },
})
