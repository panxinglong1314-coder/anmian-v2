// pages/subscribe/subscribe.js

const app = getApp()
const API = app.globalData.apiBaseUrl || 'https://sleepai.chat'

// 定价方案
const PLANS = {
  monthly: {
    price: '¥25/月',
    productId: 'com.zhimian.premium.monthly',
  },
  yearly: {
    price: '¥199/年',
    pricePerMonth: '≈¥16.6/月',
    productId: 'com.zhimian.premium.yearly',
  },
  max: {
    price: '¥60/月',
    productId: 'com.zhimian.premium.max',
  },
}

Page({
  data: {
    isPremium: false,
    expireDate: '',
    planType: 'yearly',  // 'monthly' | 'yearly' | 'max'
    isInTrial: false,
    trialDaysLeft: 0,
    trialEndDate: '',
    plans: PLANS,
    freeChatsLeft: 3,     // 今日剩余免费对话次数
  },

  onLoad() {
    this.initTrial()
    this.checkSubscription()
    this._updateFreeChatsLeft()
  },

  onShow() {
    this.initTrial()
    this.checkSubscription()
    this._updateFreeChatsLeft()
  },

  // 更新今日剩余免费对话次数
  // 规则：首周试用期内每日3次，试用期结束后仍然每日3次，付费后无限
  _updateFreeChatsLeft() {
    const sub = wx.getStorageSync('subscription') || {}
    // 付费用户无限次
    if (sub.isPremium) {
      this.setData({ freeChatsLeft: '∞' })
      return
    }
    // 试用期或非付费用户，每日限制3次
    const today = new Date().toISOString().split('T')[0]
    const stored = wx.getStorageSync('daily_chat_count') || {}
    const record = stored[today]
    const used = record ? record.count : 0
    this.setData({ freeChatsLeft: Math.max(0, 3 - used) })
  },

  // 初始化首周试用
  initTrial() {
    let trialStart = wx.getStorageSync('trial_start_date')
    if (!trialStart) {
      // 首次使用，设定7天试用期
      const now = new Date()
      wx.setStorageSync('trial_start_date', now.toISOString())
      wx.setStorageSync('trial_end_date', new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString())
      trialStart = now.toISOString()
    }
    this.updateTrialState()
  },

  // 检查是否在首周试用期内（已订阅则不算试用）
  checkTrial() {
    // 已有付费订阅，不算试用
    const sub = wx.getStorageSync('subscription') || {}
    if (sub.isPremium) return false

    const trialStart = wx.getStorageSync('trial_start_date')
    if (!trialStart) {
      const now = new Date()
      wx.setStorageSync('trial_start_date', now.toISOString())
      wx.setStorageSync('trial_end_date', new Date(now.getTime() + 7 * 24 * 60 * 60 * 1000).toISOString())
      return true
    }
    const trialEnd = new Date(wx.getStorageSync('trial_end_date'))
    const now = new Date()
    return now < trialEnd
  },

  // 更新试用状态
  updateTrialState() {
    const trialEnd = new Date(wx.getStorageSync('trial_end_date'))
    const now = new Date()
    const isInTrial = now < trialEnd
    const diffMs = trialEnd - now
    const trialDaysLeft = Math.ceil(diffMs / (1000 * 60 * 60 * 24))
    const trialEndDate = trialEnd.toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    })

    this.setData({
      isInTrial,
      trialDaysLeft: isInTrial ? trialDaysLeft : 0,
      trialEndDate,
    })
  },

  checkSubscription() {
    // 从 storage 读取本地缓存
    const sub = wx.getStorageSync('subscription') || {}
    const localPremium = sub.isPremium || false
    const localExpireDate = sub.expireDate || ''

    // 先用本地状态显示，避免延迟
    this.setData({
      isPremium: localPremium && !!localExpireDate,
      expireDate: localExpireDate,
    })

    // 再从后端验证（异步，覆盖本地状态）
    if (app.globalData.userId) {
      wx.request({
        url: `${app.globalData.apiBaseUrl}/api/v1/subscription/${app.globalData.userId}`,
        success: res => {
          if (res.statusCode === 200) {
            const backendActive = res.data.is_active
            if (backendActive) {
              // 后端确认有效，更新本地缓存
              const newSub = {
                isPremium: true,
                planType: res.data.plan || sub.planType || 'yearly',
                expireDate: res.data.expire_date || localExpireDate,
                activateAt: res.data.activated_at || sub.activateAt,
              }
              wx.setStorageSync('subscription', newSub)
              this.setData({
                isPremium: true,
                expireDate: newSub.expireDate,
              })
            } else if (localPremium) {
              // 本地有缓存但后端已过期，更新本地
              wx.setStorageSync('subscription', { ...sub, isPremium: false })
              this.setData({ isPremium: false })
            }
          }
        }
      })
    }
  },

  setPlanType(e) {
    this.setData({ planType: e.currentTarget.dataset.type })
  },

  subscribe() {
    const planType = this.data.planType
    const plan = PLANS[planType]
    const price = plan.price

    // 微信小程序支付（productId 替换为真实微信支付配置）
    // 目前先用模拟支付，后续接入 wx.requestPayment
    wx.showModal({
      title: '确认订阅',
      content: `${price}，确认开通 ${planType === 'yearly' ? 'Pro' : planType === 'max' ? 'Max' : 'Pro'} 会员？`,
      confirmText: '确认',
      cancelText: '取消',
      success: res => {
        if (res.confirm) {
          this.processSubscription(planType)
        }
      }
    })
  },

  processSubscription(planType) {
    wx.showLoading({ title: '开通中...' })

    // 模拟订阅成功（实际接微信支付）
    setTimeout(() => {
      const now = new Date()
      const expire = new Date(now)
      if (planType === 'monthly') {
        expire.setMonth(expire.getMonth() + 1)
      } else if (planType === 'yearly') {
        expire.setFullYear(expire.getFullYear() + 1)
      } else {
        expire.setMonth(expire.getMonth() + 1)
      }
      const expireDate = expire.toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })

      const sub = {
        isPremium: true,
        planType,
        expireDate,
        activateAt: now.toISOString(),
      }
      wx.setStorageSync('subscription', sub)

      // 上报后端
      wx.request({
        url: `${app.globalData.apiBaseUrl}/api/v1/subscription/activate`,
        method: 'POST',
        data: {
          user_id: app.globalData.userId,
          plan: planType,
          expire_date: expire.toISOString(),
        },
        fail: () => {}
      })

      wx.hideLoading()
      wx.showToast({ title: '开通成功！👑', icon: 'none', duration: 2500 })

      this.setData({
        isPremium: true,
        expireDate,
      })
    }, 1500)
  },

  restorePurchase() {
    wx.showToast({ title: '正在恢复购买...', icon: 'none' })
    // 实际接微信支付 restore 逻辑
    setTimeout(() => {
      this.checkSubscription()
    }, 1000)
  },

  openTerms() {
    wx.showModal({
      title: '用户协议',
      content: '知眠用户协议全文...（接入时填充真实链接）',
      showCancel: false,
      confirmText: '知道了',
    })
  },

  openPrivacy() {
    wx.showModal({
      title: '隐私政策',
      content: '知眠隐私政策全文...（接入时填充真实链接）',
      showCancel: false,
      confirmText: '知道了',
    })
  },
})
