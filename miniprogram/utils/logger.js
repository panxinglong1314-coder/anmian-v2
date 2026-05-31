// utils/logger.js
//
// 轻量日志封装。背景:
// - chat.js 等页面有大量状态机"防御性 warn"(如 [VAD] restart already pending),
//   这些是**正常用户行为**会触发的去重/竞态保护,不应在 prod 产生 noise。
// - 真错误(网络失败、音频硬故障、登录失败)需要继续可见。
//
// 用法:
//   const log = require('../../utils/logger')
//   log.dlog('[VAD]', 'restart pending')   // 仅开发工具,prod 静默
//   log.warn('[Recorder]', '硬故障', err)  // 等同 console.warn
//   log.error('[ASR]', 'parse failed', e)  // 等同 console.error
//
// 通过 wx.getStorageSync('debug_logging') 强制打开 prod 调试输出。

// WeChat 开发者工具的环境标识(SDKVersion + platform=='devtools')
let _isDev = false
try {
  const sysInfo = wx.getSystemInfoSync()
  _isDev = sysInfo && (sysInfo.platform === 'devtools' || sysInfo.platform === 'mac' || sysInfo.platform === 'windows')
} catch (e) { _isDev = false }

function _debugEnabled() {
  if (_isDev) return true
  try { return !!wx.getStorageSync('debug_logging') } catch (e) { return false }
}

function dlog(...args) {
  if (_debugEnabled()) {
    console.log.apply(console, args)
  }
}

function warn(...args) {
  console.warn.apply(console, args)
}

function error(...args) {
  console.error.apply(console, args)
}

module.exports = { dlog, warn, error }
