// pages/feedback/feedback.js
const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

Page({
  data: {
    feedbackText: '',
    submitted: false,
  },

  onInput(e) {
    this.setData({ feedbackText: e.detail.value })
  },

  async submitFeedback() {
    const text = this.data.feedbackText.trim()
    if (!text) {
      wx.showToast({ title: '请输入反馈内容', icon: 'none' })
      return
    }
    const token = app.getToken()
    wx.showLoading({ title: '提交中...' })
    try {
      const res = await wx.request({
        url: `${API}/api/v1/feedback`,
        method: 'POST',
        header: {
          Authorization: `Bearer ${token || ''}`,
          'Content-Type': 'application/json',
        },
        data: { content: text },
        timeout: 15000,
      })
      wx.hideLoading()
      if (res.statusCode === 200 || res.statusCode === 201) {
        this.setData({ submitted: true, feedbackText: '' })
        wx.showToast({ title: '提交成功', icon: 'success' })
      } else {
        wx.showToast({ title: '提交失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      console.error('[submitFeedback]', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    }
  },
})