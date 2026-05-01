// pages/profile/profile.js - 个人中心
const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

Page({
  data: {
    userInfo: null,
    nickname: '',
    avatarUrl: '',
    isLoading: false,
  },

  onLoad() {
    this.loadProfile()
  },

  onShow() {
    this.loadProfile()
  },

  async loadProfile() {
    const token = app.getToken()
    if (!token) {
      this.setData({ userInfo: null })
      return
    }
    this.setData({ isLoading: true })
    try {
      const res = await wx.request({
        url: `${API}/api/v1/user/profile`,
        method: 'GET',
        header: { Authorization: `Bearer ${token}` },
        timeout: 15000,
      })
      if (res.statusCode === 200 && res.data) {
        this.setData({
          userInfo: res.data,
          nickname: res.data.nickname || '',
          avatarUrl: res.data.avatar_url || '',
        })
      } else if (res.statusCode === 401) {
        // token 过期，清除并重新登录
        wx.removeStorageSync('jwt_token')
        app.wxLogin()
      }
    } catch (e) {
      console.error('[loadProfile]', e)
    } finally {
      this.setData({ isLoading: false })
    }
  },

  onNicknameInput(e) {
    this.setData({ nickname: e.detail.value })
  },

  async saveProfile() {
    const token = app.getToken()
    if (!token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    const nickname = this.data.nickname.trim()
    if (!nickname) {
      wx.showToast({ title: '昵称不能为空', icon: 'none' })
      return
    }
    wx.showLoading({ title: '保存中' })
    try {
      const res = await wx.request({
        url: `${API}/api/v1/user/profile`,
        method: 'POST',
        header: {
          Authorization: `Bearer ${token}`,
          'Content-Type': 'application/json',
        },
        data: { nickname },
        timeout: 15000,
      })
      wx.hideLoading()
      if (res.statusCode === 200) {
        this.setData({
          userInfo: res.data,
          nickname: res.data.nickname || '',
        })
        wx.showToast({ title: '已保存', icon: 'success' })
      } else {
        wx.showToast({ title: '保存失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      console.error('[saveProfile]', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    }
  },

  logout() {
    wx.showModal({
      title: '退出登录',
      content: '确定要退出登录吗？',
      confirmText: '退出',
      success: (res) => {
        if (res.confirm) {
          wx.removeStorageSync('jwt_token')
          wx.removeStorageSync('user_id')
          this.setData({ userInfo: null, nickname: '', avatarUrl: '' })
          // 重新生成临时 ID
          app.getUserId()
          wx.showToast({ title: '已退出', icon: 'none' })
        }
      },
    })
  },

  goBack() {
    wx.navigateBack()
  },
})
