// pages/subscribe/subscribe.js

const app = getApp()

// 定价方案
const PLANS = {
  free: {
    id: 'free',
    name: '免费版',
    voice: '10分钟/天',
    text: '30分钟/天',
    priceMonthly: 0,
    priceYearly: 0,
  },
  basic: {
    id: 'basic',
    name: '基础 Pro',
    voice: '10小时/月',
    text: '30小时/月',
    priceMonthly: 60,
    priceYearly: Math.round(60 * 12 * 0.85),
    recommended: true,
  },
  core: {
    id: 'core',
    name: '核心 Pro',
    voice: '25小时/月',
    text: '60小时/月',
    priceMonthly: 100,
    priceYearly: Math.round(100 * 12 * 0.85),
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
    this.loadPricing()
  },

  // 从后端读取可由 admin 后台修改的最新定价
  loadPricing() {
    if (!app.globalData.userId) return
    app.authRequest({
      url: `${app.globalData.apiBaseUrl}/api/v1/pricing`,
      success: res => {
        const p = res.data && res.data.plans
        if (res.statusCode !== 200 || !p) return
        const plans = this.data.plans
        if (p.basic) {
          plans.basic.priceMonthly = p.basic.monthly
          plans.basic.priceYearly = p.basic.yearly
        }
        if (p.core) {
          plans.core.priceMonthly = p.core.monthly
          plans.core.priceYearly = p.core.yearly
        }
        this.setData({
          plans,
          planList: [plans.free, plans.basic, plans.core],
        }, () => this.updatePriceDisplay())
      },
      fail: err => console.warn('[loadPricing] fail:', err)
    })
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
    // 价目仅作展示,实际开通能力即将开放,先不进入交易流程
    this._logInterest('button')
    wx.showToast({
      title: '敬请期待,即将开放',
      icon: 'none',
      duration: 2000,
    })
  },

  restorePurchase() {
    // 付费能力暂未开放
    this._logInterest('restore')
    wx.showToast({ title: '敬请期待,即将开放', icon: 'none', duration: 2000 })
  },

  // 上报付费意向到后端,fire-and-forget,失败不影响 UX
  _logInterest(source) {
    try {
      app.authRequest({
        url: `${app.globalData.apiBaseUrl}/api/v1/interest/subscribe`,
        method: 'POST',
        data: {
          plan: this.data.selectedPlan || '',
          billing_cycle: this.data.billingCycle || '',
          source: source || 'button',
        },
        timeout: 4000,
        success: () => {},
        fail: () => {},
      })
    } catch (e) {}
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
