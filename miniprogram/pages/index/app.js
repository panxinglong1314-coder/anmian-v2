// app.js - 微信小程序入口
// 睡前大脑关机助手

App({
  globalData: {
    // API 配置（开发环境）
    apiBaseUrl: 'https://api.yourdomain.com', // 上线后替换

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
    // 1. 获取用户唯一标识
    this.getUserId()

    // 2. 初始化会话
    this.initSession()

    // 3. 检查网络状态
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

  // 获取用户唯一标识（使用微信 UnionID 或 OpenID）
  getUserId() {
    // 推荐：使用微信 UnionID（需绑定公众号/网站）
    // 简化：使用 OpenID
    const userId = wx.getStorageSync('user_id')
    if (userId) {
      this.globalData.userId = userId
    } else {
      // 首次使用，生成临时 ID
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
      // 新会话
      const newSessionId = `session_${today}_${Date.now()}`
      wx.setStorageSync('session_id', newSessionId)
      wx.setStorageSync('session_date', today)
      this.globalData.sessionId = newSessionId
    }
  }
})
