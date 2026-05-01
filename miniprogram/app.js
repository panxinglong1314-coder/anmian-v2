// app.js - 微信小程序入口
// 睡前大脑关机助手

App({
  globalData: {
    // API 配置（生产环境）
    apiBaseUrl: 'https://sleepai.chat',

    // 会话信息
    userId: null,
    sessionId: null,

    // 焦虑状态
    currentAnxiety: {
      level: 'normal',
      recommendedAction: 'CONTINUE'
    },

    // 呼吸引导状态
    breathing: {
      isPlaying: false,
      currentCycle: 0,
      currentPhase: 'inhale' // inhale / hold / exhale
    }
  },

  onLaunch() {
    // 0. 检查隐私政策同意状态
    const privacyAgreed = wx.getStorageSync('privacy_agreed')
    this.globalData.needShowPrivacy = !privacyAgreed

    // 1. 获取用户唯一标识（优先本地，后续 wxLogin 可能更新）
    this.getUserId()

    // 2. 微信登录（异步，静默）
    this.wxLogin()

    // 3. 初始化会话
    this.initSession()

    // 4. 检查网络状态
    wx.onNetworkStatusChange(res => {
      if (!res.isConnected) {
        wx.showToast({
          title: '网络已断开',
          icon: 'error',
          duration: 2000
        })
      }
    })
  },

  // 同意隐私政策
  agreePrivacy() {
    wx.setStorageSync('privacy_agreed', true)
    wx.setStorageSync('privacy_agreed_time', Date.now())
    this.globalData.needShowPrivacy = false
  },

  // 拒绝隐私政策
  disagreePrivacy() {
    wx.setStorageSync('privacy_agreed', false)
    this.globalData.needShowPrivacy = true
  },

  // 微信登录：获取 code 并换取后端 JWT token
  wxLogin() {
    const prevUserId = wx.getStorageSync('user_id') || null
    const isTempId = prevUserId && prevUserId.startsWith('user_')

    wx.login({
      success: (res) => {
        if (!res.code) {
          console.warn('[wxLogin] 未获取到 code')
          return
        }
        wx.request({
          url: `${this.globalData.apiBaseUrl}/api/v1/auth/wx_login`,
          method: 'POST',
          data: {
            code: res.code,
            temp_id: isTempId ? prevUserId : undefined
          },
          timeout: 15000,
          success: (r) => {
            if (r.statusCode === 200 && r.data && r.data.token) {
              wx.setStorageSync('jwt_token', r.data.token)
              wx.setStorageSync('user_id', r.data.user_id)
              this.globalData.userId = r.data.user_id
              console.log('[wxLogin] 登录成功', r.data.user_id, '新用户:', r.data.is_new_user, '迁移:', isTempId ? prevUserId : '无')
            } else {
              console.warn('[wxLogin] 登录失败', r.statusCode, r.data)
            }
          },
          fail: (err) => {
            console.warn('[wxLogin] 请求失败', err)
          }
        })
      },
      fail: (err) => {
        console.warn('[wxLogin] wx.login 失败', err)
      }
    })
  },

  // 获取 JWT token
  getToken() {
    return wx.getStorageSync('jwt_token') || null
  },

  // 获取用户唯一标识（使用微信 UnionID 或 OpenID）
  getUserId() {
    const userId = wx.getStorageSync('user_id')
    if (userId) {
      this.globalData.userId = userId
    } else {
      const tempId = 'user_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9)
      wx.setStorageSync('user_id', tempId)
      this.globalData.userId = tempId
    }
  },

  // 初始化会话
  initSession() {
    const today = new Date().toISOString().split('T')[0]
    const sessionId = wx.getStorageSync('session_id')
    const sessionDate = wx.getStorageSync('session_date')

    if (sessionId && sessionDate === today) {
      this.globalData.sessionId = sessionId
    } else {
      const newSessionId = `session_${today}_${Date.now()}`
      wx.setStorageSync('session_id', newSessionId)
      wx.setStorageSync('session_date', today)
      this.globalData.sessionId = newSessionId
    }
  }
})
