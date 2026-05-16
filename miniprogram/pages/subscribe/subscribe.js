// pages/subscribe/subscribe.js

const app = getApp()

// 定价方案
const PLANS = {
  free: {
    id: 'free',
    name: '免费版',
    voice: '3分钟/天',
    text: '10分钟/天',
    priceMonthly: 0,
    priceYearly: 0,
  },
  basic: {
    id: 'basic',
    name: '基础 Pro',
    voice: '15小时/月',
    text: '15小时/月',
    priceMonthly: 30,
    priceYearly: Math.round(30 * 12 * 0.85),
    recommended: true,
  },
  core: {
    id: 'core',
    name: '核心 Pro',
    voice: '30小时/月',
    text: '30小时/月',
    priceMonthly: 45,
    priceYearly: Math.round(45 * 12 * 0.85),
  },
}

Page({
  data: {
    isPremium: false,
    expireDate: '',
    selectedPlan: 'basic',
    billingCycle: 'monthly',
    plans: PLANS,
    planList: [PLANS.free, PLANS.basic, PLANS.core],
    currentPlanName: '',
    currentPrice: '',
  },

  onLoad() {
    this.checkSubscription()
    this.updatePriceDisplay()
  },

  onShow() {
    this.checkSubscription()
  },

  checkSubscription() {
    const sub = wx.getStorageSync('subscription') || {}
    const isPremium = sub.isPremium || false
    const expireDate = sub.expireDate || ''
    const planType = sub.planType || ''

    let currentPlanName = '免费版'
    if (planType === 'basic') currentPlanName = '基础 Pro'
    if (planType === 'core') currentPlanName = '核心 Pro'

    if (app.globalData.userId) {
      // ⚠️ 必须用 app.authRequest 携带 JWT，否则 401
      app.authRequest({
        url: `${app.globalData.apiBaseUrl}/api/v1/subscription/${app.globalData.userId}`,
        success: res => {
          if (res.statusCode === 200 && res.data && res.data.is_active) {
            this.setData({
              isPremium: true,
              expireDate: res.data.expire_date || '',
            })
          }
        },
        fail: err => console.warn('[checkSubscription] fail:', err)
      })
    }

    this.setData({
      isPremium: isPremium && !!expireDate,
      expireDate,
      currentPlanName,
    })
  },

  setBillingCycle(e) {
    this.setData({ billingCycle: e.currentTarget.dataset.cycle })
    this.updatePriceDisplay()
  },

  selectPlan(e) {
    this.setData({ selectedPlan: e.currentTarget.dataset.plan })
    this.updatePriceDisplay()
  },

  updatePriceDisplay() {
    const plan = PLANS[this.data.selectedPlan]
    if (!plan) return
    const price = this.data.billingCycle === 'monthly' ? plan.priceMonthly : plan.priceYearly
    const unit = this.data.billingCycle === 'monthly' ? '/月' : '/年'
    this.setData({ currentPrice: price > 0 ? `¥${price}${unit}` : '' })
  },

  subscribe() {
    if (this.data.selectedPlan === 'free') return

    const plan = PLANS[this.data.selectedPlan]
    const price = this.data.billingCycle === 'monthly' ? plan.priceMonthly : plan.priceYearly
    const cycleText = this.data.billingCycle === 'monthly' ? '月付' : '年付'

    wx.showModal({
      title: '确认订阅',
      content: `${plan.name}（${cycleText}）¥${price}，确认开通？`,
      confirmText: '确认',
      cancelText: '取消',
      success: res => {
        if (res.confirm) {
          this.processSubscription(this.data.selectedPlan, this.data.billingCycle)
        }
      }
    })
  },

  processSubscription(planType, billingCycle) {
    wx.showLoading({ title: '开通中...' })

    setTimeout(() => {
      const now = new Date()
      const expire = new Date(now)
      if (billingCycle === 'monthly') {
        expire.setMonth(expire.getMonth() + 1)
      } else {
        expire.setFullYear(expire.getFullYear() + 1)
      }
      const expireDate = expire.toLocaleDateString('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
      })

      const sub = {
        isPremium: true,
        planType,
        billingCycle,
        expireDate,
        activateAt: now.toISOString(),
      }
      wx.setStorageSync('subscription', sub)

      wx.request({
        url: `${app.globalData.apiBaseUrl}/api/v1/subscription/activate`,
        method: 'POST',
        data: {
          user_id: app.globalData.userId,
          plan: planType,
          billing_cycle: billingCycle,
          expire_date: expire.toISOString(),
        },
        fail: () => {}
      })

      wx.hideLoading()
      wx.showToast({ title: '开通成功！', icon: 'none', duration: 2500 })

      let currentPlanName = ''
      if (planType === 'basic') currentPlanName = '基础 Pro'
      if (planType === 'core') currentPlanName = '核心 Pro'

      this.setData({
        isPremium: true,
        expireDate,
        currentPlanName,
      })
    }, 1500)
  },

  restorePurchase() {
    wx.showToast({ title: '正在恢复购买...', icon: 'none' })
    setTimeout(() => { this.checkSubscription() }, 1000)
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
