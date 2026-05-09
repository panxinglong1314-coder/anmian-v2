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
    // 0. 提前预检隐私+麦克风授权（首次静默处理，避免进入页面后再弹框）
    this._preauthorizePrivacyAndMic()

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

  // 【优化】同意隐私政策（仅在 chat 页面调用，app.js 不再单独处理）
  agreePrivacy() {
    wx.setStorageSync('privacy_agreed', true)
    wx.setStorageSync('privacy_agreed_time', Date.now())
    this.globalData.needShowPrivacy = false
  },

  // 【新增】onLaunch 预授权：静默处理隐私协议+麦克风授权
  // 成功 → privacy_agreed=true，后续进 app 直接进睡眠模式
  // 失败/拒绝 → privacy_agreed=false，用户到 chat 页面后再处理
  _preauthorizePrivacyAndMic() {
    // 先检查隐私是否已同意（已同意则跳过）
    const alreadyAgreed = wx.getStorageSync('privacy_agreed')
    if (alreadyAgreed) {
      console.log('[PreAuth] 隐私已同意，检查麦克风权限...')
      // 隐私已同意 → 检查麦克风权限是否已授权
      wx.getSetting({
        success: (res) => {
          if (!res.authSetting['scope.record']) {
            // 麦克风未授权，提前静默触发（失败不影响流程）
            wx.authorize({ scope: 'scope.record', success: () => {
              console.log('[PreAuth] 麦克风预授权成功')
            }, fail: () => {
              console.log('[PreAuth] 麦克风预授权失败（用户将在 chat 页面看到提示）')
            }})
          } else {
            console.log('[PreAuth] 麦克风已授权')
          }
        }
      })
      this.globalData.needShowPrivacy = false
      return
    }

    // 隐私未同意 → 检查是否需要微信隐私协议弹窗
    if (!wx.getPrivacySetting) {
      // 低版本微信：直接标记需要显示隐私弹窗
      this.globalData.needShowPrivacy = true
      return
    }
    wx.getPrivacySetting({
      success: (res) => {
        if (res.needAuthorization) {
          // 需要弹隐私协议 → onLaunch 无法静默处理，跳到 chat 页面处理
          console.log('[PreAuth] 需要隐私授权，将在 chat 页面引导')
          this.globalData.needShowPrivacy = true
        } else {
          // 不需要微信隐私协议弹窗 → 直接走麦克风授权
          console.log('[PreAuth] 无需微信隐私协议，直接请求麦克风')
          wx.authorize({
            scope: 'scope.record',
            success: () => {
              wx.setStorageSync('privacy_agreed', true)
              wx.setStorageSync('privacy_agreed_time', Date.now())
              this.globalData.needShowPrivacy = false
              console.log('[PreAuth] 麦克风授权成功，隐私同意已完成')
            },
            fail: () => {
              // 麦克风拒绝 → 隐私已同意，麦克风未授权
              wx.setStorageSync('privacy_agreed', true)
              wx.setStorageSync('privacy_agreed_time', Date.now())
              this.globalData.needShowPrivacy = false
              console.log('[PreAuth] 麦克风拒绝，但隐私已同意')
            }
          })
        }
      },
      fail: () => {
        // 出错 → 交给 chat 页面处理
        this.globalData.needShowPrivacy = true
      }
    })
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
