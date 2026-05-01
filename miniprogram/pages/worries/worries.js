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
  },

  onLoad() {
    this.loadWorries()
  },

  async loadWorries() {
    const userId = app.globalData.userId
    this.setData({ isLoading: true })
    const res = await _apiReq(`${API}/api/v1/worries/${userId}?limit=50`)
    if (res.statusCode === 200 && res.data) {
      const list = (res.data.records || []).map(r => ({
        ...r,
        dateStr: r.recorded_at ? new Date(r.recorded_at).toLocaleDateString('zh-CN', { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '',
        expanded: false,
      }))
      this.setData({ worryList: list, filteredList: list, isLoading: false })
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
