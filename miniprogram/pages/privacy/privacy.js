Page({
  data: {
    from: ''
  },

  onLoad(options) {
    this.setData({ from: options.from || '' })
  },

  onAgree() {
    wx.setStorageSync('privacy_agreed', true)
    wx.setStorageSync('privacy_agreed_time', Date.now())
    wx.showToast({ title: '已同意', icon: 'success' })
    if (this.data.from === 'splash') {
      wx.reLaunch({ url: '/pages/chat/chat' })
    } else {
      wx.navigateBack()
    }
  }
})
