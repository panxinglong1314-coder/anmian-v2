// pages/profile/profile.js - 个人中心
const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

Page({
  data: {
    userInfo: null,
    nickname: '',
    avatarUrl: '',
    isLoading: false,
    nicknameDirty: false,   // 用户改过昵称后才显示"保存"按钮
    // 紧急联系人
    emergencyExpanded: false,
    emergencyContact: { name: '', phone: '', relation: '', consent: false },
    relationOptions: ['家人', '朋友', '医生', '其他'],
  },

  onLoad() {
    this.loadProfile()
    this.loadEmergencyContact()
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
    const v = e.detail.value
    const original = (this.data.userInfo && this.data.userInfo.nickname) || ''
    this.setData({
      nickname: v,
      nicknameDirty: v.trim() !== original.trim() && v.trim().length > 0,
    })
  },

  onNicknameBlur(e) {
    // 失焦时若已修改且非空，自动保存（更现代的交互）
    if (this.data.nicknameDirty && e.detail.value.trim()) {
      this.saveProfile()
    }
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
          nicknameDirty: false,
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

  // ========== 头像选择（wx.chooseAvatar） ==========
  onChooseAvatar(e) {
    const avatarUrl = e.detail.avatarUrl
    if (!avatarUrl) return
    // 立即本地显示（让用户感知到点击有反馈）
    this.setData({ avatarUrl })
    this.uploadAvatar(avatarUrl)
  },

  async uploadAvatar(tempFilePath) {
    const token = app.getToken()
    if (!token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    wx.showLoading({ title: '上传头像' })
    wx.uploadFile({
      url: `${API}/api/v1/user/avatar`,
      filePath: tempFilePath,
      name: 'file',
      header: { Authorization: `Bearer ${token}` },
      success: (res) => {
        wx.hideLoading()
        try {
          const data = JSON.parse(res.data)
          if (res.statusCode === 200 && data.avatar_url) {
            this.setData({ avatarUrl: data.avatar_url })
            wx.showToast({ title: '头像已更新', icon: 'success' })
          } else {
            wx.showToast({ title: data.detail || '上传失败', icon: 'none' })
          }
        } catch (e) {
          wx.showToast({ title: '响应解析失败', icon: 'none' })
        }
      },
      fail: (err) => {
        wx.hideLoading()
        console.error('[uploadAvatar]', err)
        wx.showToast({ title: '上传失败', icon: 'none' })
      },
    })
  },

  // ========== 紧急联系人 ==========
  async loadEmergencyContact() {
    const token = app.getToken()
    if (!token) return
    try {
      const res = await wx.request({
        url: `${API}/api/v1/user/emergency_contact`,
        method: 'GET',
        header: { Authorization: `Bearer ${token}` },
      })
      if (res.statusCode === 200 && res.data) {
        this.setData({ emergencyContact: res.data })
      }
    } catch (e) { console.warn('[loadEmergencyContact]', e) }
  },

  toggleEmergency() {
    this.setData({ emergencyExpanded: !this.data.emergencyExpanded })
  },

  onEmergencyNameInput(e) {
    this.setData({ 'emergencyContact.name': e.detail.value })
  },

  onEmergencyPhoneInput(e) {
    this.setData({ 'emergencyContact.phone': e.detail.value })
  },

  onSelectRelation(e) {
    this.setData({ 'emergencyContact.relation': e.currentTarget.dataset.relation })
  },

  toggleConsent() {
    this.setData({ 'emergencyContact.consent': !this.data.emergencyContact.consent })
  },

  async saveEmergencyContact() {
    const ec = this.data.emergencyContact
    if (!ec.phone) {
      wx.showToast({ title: '请填写手机号', icon: 'none' })
      return
    }
    if (!ec.consent) {
      wx.showToast({ title: '请勾选同意条款', icon: 'none' })
      return
    }
    const token = app.getToken()
    if (!token) {
      wx.showToast({ title: '请先登录', icon: 'none' })
      return
    }
    wx.showLoading({ title: '保存中' })
    try {
      const res = await wx.request({
        url: `${API}/api/v1/user/emergency_contact`,
        method: 'POST',
        header: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
        data: ec,
      })
      wx.hideLoading()
      if (res.statusCode === 200) {
        this.setData({ emergencyContact: res.data })
        wx.showToast({ title: '已保存', icon: 'success' })
      } else {
        wx.showToast({ title: (res.data && res.data.detail) || '保存失败', icon: 'none' })
      }
    } catch (e) {
      wx.hideLoading()
      console.error('[saveEmergencyContact]', e)
      wx.showToast({ title: '网络错误', icon: 'none' })
    }
  },

  clearEmergencyContact() {
    wx.showModal({
      title: '清除紧急联系人',
      content: '清除后，AI 在检测到严重危机时将无法联系 TA。确定吗？',
      confirmText: '清除',
      confirmColor: '#E8846B',
      success: async (res) => {
        if (!res.confirm) return
        const token = app.getToken()
        try {
          await wx.request({
            url: `${API}/api/v1/user/emergency_contact`,
            method: 'POST',
            header: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
            data: { name: '', phone: '', relation: '', consent: false },
          })
          this.setData({ emergencyContact: { name: '', phone: '', relation: '', consent: false } })
          wx.showToast({ title: '已清除', icon: 'none' })
        } catch (e) {
          wx.showToast({ title: '清除失败', icon: 'none' })
        }
      },
    })
  },

  // ========== 关于·占位入口 ==========
  openPrivacy() {
    wx.showModal({
      title: '隐私政策',
      content: '完整版本请访问 https://sleepai.chat/privacy\n\n核心承诺：\n· 你的对话内容仅用于陪伴你，不会卖给第三方\n· 紧急联系人仅在 AI 检测严重危机时联系\n· 你可随时清除全部数据',
      showCancel: false,
      confirmText: '我知道了',
    })
  },
  openTerms() {
    wx.showModal({
      title: '用户协议',
      content: '知眠是 CBT-I 数字辅助工具，不替代精神科医生。\n如果你有自伤/自杀念头，请立即拨打：\n· 全国心理援助热线 400-161-9995\n· 北京心理危机研究 010-82951332',
      showCancel: false,
      confirmText: '我知道了',
    })
  },
  openAbout() {
    wx.showModal({
      title: '关于知眠 v2.0',
      content: '基于 CBT-I（认知行为失眠疗法）的 AI 助眠陪伴\n\nAASM 2025 / European Insomnia Guideline 2023 临床方案',
      showCancel: false,
      confirmText: '好的',
    })
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
