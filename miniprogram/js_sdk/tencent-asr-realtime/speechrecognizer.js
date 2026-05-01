/**
 * 腾讯云实时语音识别 - Mini Program WebSocket 版
 *
 * 基于腾讯云 ASR WebSocket API (asr.cloud.tencent.com/asr/v2/)
 * https://cloud.tencent.com/document/product/1093/48982
 *
 * 使用方式:
 *   const asr = new TencentASR({
 *     appid: '1251656042',
 *     secretid: 'AKIDw0sY2KUWM0...',
 *     secretkey: 'z0oOnRuADGUc...',
 *     engine_model_type: '16k_zh',
 *     voice_format: 1,  // 1=PCM
 *   })
 *
 *   asr.onStart = () => console.log('ASR started')
 *   asr.onResult = (text, isFinal) => console.log('result:', text, isFinal)
 *   asr.onError = (err) => console.error('error:', err)
 *
 *   asr.start()           // 开始识别
 *   asr.sendAudio(pcmData) // 发送音频数据（PCM Int8Array，16kHz）
 *   asr.stop()             // 停止识别
 */

'use strict';

// ─── HMAC-SHA1 实现（Mini Program 环境） ───────────────────────────────────
function hmacSha1(key, message) {
  // 使用微信内置 CryptoJS（HMAC-SHA1）
  if (typeof wx !== 'undefined' && wx.requireMiniProgram) {
    // 降级：手动实现 HMAC-SHA1
    return _hmacSha1Manual(key, message)
  }
  return _hmacSha1Manual(key, message)
}

function _hmacSha1Manual(key, message) {
  // 简化的 HMAC-SHA1 实现
  // B64 encode using wx.arrayBufferToBase64 if available
  const wordArray = _strToWords(message)
  const keyWords = _strToWords(key)

  // Pad or hash key to 64 bytes
  const oKeyPad = new Array(64).fill(0x5c)
  const iKeyPad = new Array(64).fill(0x36)

  for (let i = 0; i < keyWords.length && i < 16; i++) {
    oKeyPad[i * 4] = (keyWords[i] >> 24) & 0xff
    oKeyPad[i * 4 + 1] = (keyWords[i] >> 16) & 0xff
    oKeyPad[i * 4 + 2] = (keyWords[i] >> 8) & 0xff
    oKeyPad[i * 4 + 3] = keyWords[i] & 0xff
    iKeyPad[i * 4] = (keyWords[i] >> 24) & 0xff
    iKeyPad[i * 4 + 1] = (keyWords[i] >> 16) & 0xff
    iKeyPad[i * 4 + 2] = (keyWords[i] >> 8) & 0xff
    iKeyPad[i * 4 + 3] = keyWords[i] & 0xff
  }

  const inner = _sha1(String.fromCharCode.apply(null, iKeyPad) + message)
  const outer = _sha1(String.fromCharCode.apply(null, oKeyPad) + inner)

  // Convert to base64
  const b64chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
  let result = ''
  const chars = outer.match(/.{1,2}/g) || []
  for (let i = 0; i < chars.length; i++) {
    const v = parseInt(chars[i], 16)
    result += b64chars[(v >> 6) & 0x3f] + b64chars[v & 0x3f]
  }
  // Padding
  while (result.length % 4 !== 0) result += '='
  return result
}

function _strToWords(str) {
  const words = []
  for (let i = 0; i < str.length; i++) {
    const c = str.charCodeAt(i)
    words.push((c >> 24) | ((c >> 16) & 0xff) << 8 | ((c >> 8) & 0xff) << 16 | (c & 0xff) << 24)
  }
  return words
}

function _sha1(str) {
  // SHA-1 implementation for HMAC
  const _sha1RotateLeft = (n, s) => (n << s) | (n >>> (32 - s))
  const _f = [
    (b, c, d) => (b & c) | ((~b) & d),
    (b, c, d) => (b ^ c ^ d),
    (b, c, d) => (b & c) | (b & d) | (c & d),
    (b, c, d) => (b ^ c ^ d)
  ]
  const _k = [0x5a827999, 0x6ed9eba1, 0x8f1bbcdc, 0xca62c1d6]

  // Convert string to bytes
  const bytes = []
  for (let i = 0; i < str.length; i++) bytes.push(str.charCodeAt(i) & 0xff)

  // Pre-processing
  const msgLen = bytes.length
  const bitLen = msgLen * 8
  bytes.push(0x80)
  while ((bytes.length % 64) !== 56) bytes.push(0x00)
  for (let i = 7; i >= 0; i--) bytes.push((bitLen >>> (i * 8)) & 0xff)

  // Initialize hash
  let h0 = 0x67452301, h1 = 0xefcdab89, h2 = 0x98badcfe, h3 = 0x10325476, h4 = 0xc3d2e1f0

  // Process chunks
  for (let chunk = 0; chunk < bytes.length / 64; chunk++) {
    const w = new Array(80)
    for (let i = 0; i < 16; i++) {
      const off = chunk * 64 + i * 4
      w[i] = (bytes[off] << 24) | (bytes[off + 1] << 16) | (bytes[off + 2] << 8) | bytes[off + 3]
    }
    for (let i = 16; i < 80; i++) {
      w[i] = _sha1RotateLeft(w[i - 3] ^ w[i - 8] ^ w[i - 14] ^ w[i - 16], 1)
    }
    let a = h0, b = h1, c = h2, d = h3, e = h4
    for (let i = 0; i < 80; i++) {
      const fi = i < 20 ? 0 : (i < 40 ? 1 : (i < 60 ? 2 : 3))
      const ki = i < 20 ? 0 : (i < 40 ? 1 : (i < 60 ? 2 : 3))
      const temp = (_sha1RotateLeft(a, 5) + _f[fi](b, c, d) + e + w[i] + _k[ki]) >>> 0
      e = d; d = c; c = _sha1RotateLeft(b, 30) >>> 0; b = a; a = temp
    }
    h0 = (h0 + a) >>> 0; h1 = (h1 + b) >>> 0; h2 = (h2 + c) >>> 0; h3 = (h3 + d) >>> 0; h4 = (h4 + e) >>> 0
  }

  const toHex = n => {
    let s = ''
    for (let i = 3; i >= 0; i--) {
      const byte = (n >>> (i * 8)) & 0xff
      s += (byte >> 4).toString(16) + (byte & 0xf).toString(16)
    }
    return s
  }
  return toHex(h0) + toHex(h1) + toHex(h2) + toHex(h3) + toHex(h4)
}

// ─── 主要类 ────────────────────────────────────────────────────────────────
class TencentASR {
  constructor(options = {}) {
    this.appid = options.appid || ''
    this.secretid = options.secretid || ''
    this.secretkey = options.secretkey || ''
    this.engine_model_type = options.engine_model_type || '16k_zh'
    this.voice_format = options.voice_format || 1  // 1=PCM, 2=WAV
    this.nonce = options.nonce || Math.round(Math.random() * 100000)
    this.Timeout = options.Timeout || 60000
    this.isLog = options.isLog !== false

    this._socketTask = null
    this._audioChunks = []  // 待发送的音频数据
    this._isStarted = false
    this._isEnded = false
    this._pendingInit = false
    this._serverTimeOffset = 0  // 服务器时间偏移
  }

  // ─── 事件回调 ───────────────────────────────────────────────────────────
  onStart() {}
  onStop() {}
  onRecognitionStart() {}     // 识别开始事件
  onSentenceBegin() {}        // 一句话开始
  onResultChange(text) {}     // 识别结果变化（中间结果）
  onSentenceEnd(text) {}      // 一句话结束（最终结果）
  onComplete(finalText) {}    // 识别完成
  onError(err) {}

  // ─── 核心方法 ───────────────────────────────────────────────────────────

  /**
   * 开始识别：建立 WebSocket 连接
   */
  start() {
    if (this._isStarted) return
    this._isStarted = true
    this._isEnded = false
    this._audioChunks = []

    if (this.isLog) console.log('[TencentASR] 开始连接...')

    this._buildAuthUrl().then(url => {
      if (this.isLog) console.log('[TencentASR] WebSocket URL:', url.substring(0, 80) + '...')
      this._connect(url)
    }).catch(err => {
      this.onError('[TencentASR] 鉴权失败: ' + err)
    })
  }

  /**
   * 发送音频数据（PCM Int8Array，16kHz 单声道）
   * @param {ArrayBuffer|Int8Array} audioData
   */
  sendAudio(audioData) {
    if (!this._isStarted || this._isEnded) return
    if (!audioData || audioData.byteLength === 0) return

    this._audioChunks.push(audioData)

    // 如果尚未发送 init，先等一下
    if (!this._pendingInit) {
      this._flushChunks()
    }
  }

  /**
   * 结束识别：发送 end 消息
   */
  stop() {
    if (!this._isStarted) return
    this._isEnded = true

    if (this._socketTask) {
      try {
        this._socketTask.send({
          data: JSON.stringify({ type: 'end' }),
          fail: err => this.isLog && console.error('[TencentASR] send end error:', err)
        })
      } catch (e) {}
    }

    setTimeout(() => {
      this._close()
    }, 200)
  }

  _close() {
    if (this._socketTask) {
      try { this._socketTask.close() } catch (e) {}
      this._socketTask = null
    }
    this._isStarted = false
    this.onStop()
  }

  // ─── 私有方法 ───────────────────────────────────────────────────────────

  async _buildAuthUrl() {
    // 1. 获取服务器时间偏移
    await this._syncServerTime()

    const timestamp = Math.floor(Date.now() / 1000) + this._serverTimeOffset
    const expired = timestamp + 86400  // 24小时有效期

    // 2. 构建 query string（字典序排列）
    const params = {
      appid: this.appid,
      secretid: this.secretid,
      engine_model_type: this.engine_model_type,
      timestamp: timestamp,
      expired: expired,
      nonce: this.nonce,
      voice_format: this.voice_format,
      // voice_id 在这里加或不加都行
    }

    // 按 key 字典序排列
    const sortedKeys = Object.keys(params).sort()
    const queryParts = sortedKeys.map(k => `${k}=${params[k]}`)
    const queryStr = queryParts.join('&')

    // 3. 签名原文：GETasr.cloud.tencent.com/asr/v2/{query}
    const signOrigin = `GETasr.cloud.tencent.com/asr/v2/${queryStr}`

    // 4. HMAC-SHA1 签名
    const signature = this._hmacSha1(this.secretkey, signOrigin)

    // 5. Base64 encode signature
    const signatureB64 = this._base64Encode(signature)

    // 6. 构建完整 URL
    const url = `wss://asr.cloud.tencent.com/asr/v2/${queryStr}&signature=${encodeURIComponent(signatureB64)}`

    return url
  }

  _hmacSha1(key, message) {
    return _hmacSha1Manual(key, message)
  }

  _base64Encode(str) {
    // str 是 hex 字符串，转 bytes 再 base64
    const bytes = []
    for (let i = 0; i < str.length; i += 2) {
      bytes.push(parseInt(str.substring(i, i + 2), 16))
    }
    const b64chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'
    let result = ''
    for (let i = 0; i < bytes.length; i += 3) {
      const b1 = bytes[i], b2 = bytes[i + 1] || 0, b3 = bytes[i + 2] || 0
      result += b64chars[b1 >> 2]
      result += b64chars[((b1 & 3) << 4) | (b2 >> 4)]
      result += bytes[i + 1] !== undefined ? b64chars[((b2 & 15) << 2) | (b3 >> 6)] : '='
      result += bytes[i + 2] !== undefined ? b64chars[b3 & 63] : '='
    }
    return result
  }

  async _syncServerTime() {
    try {
      const start = Date.now()
      const res = await this._request('GET', 'https://asr.cloud.tencent.com/server_time', null)
      const rtt = Date.now() - start
      const serverTime = parseInt(res)
      this._serverTimeOffset = Math.floor((serverTime * 1000 - Date.now() - rtt / 2) / 1000)
      if (this.isLog) console.log('[TencentASR] 服务器时间同步偏移:', this._serverTimeOffset, '秒')
    } catch (e) {
      this._serverTimeOffset = 0  // 无法同步，用本地时间
    }
  }

  _request(method, url, data) {
    return new Promise((resolve, reject) => {
      wx.request({
        url,
        method,
        data,
        success: res => {
          if (res.statusCode === 200 && res.data) resolve(res.data)
          else reject(new Error(`HTTP ${res.statusCode}`))
        },
        fail: err => reject(err)
      })
    })
  }

  _connect(url) {
    this._socketTask = wx.connectSocket({ url })

    this._socketTask.onOpen(() => {
      if (this.isLog) console.log('[TencentASR] WebSocket 已连接')
      this._pendingInit = true

      // 发送初始化消息
      const initMsg = JSON.stringify({
        appid: this.appid,
        callback: '',
        sign: '',
        Timeout: this.Timeout,
        engine_model_type: this.engine_model_type,
        voice_format: this.voice_format,
        nonce: this.nonce,
        secretid: this.secretid,
        timestamp: Math.floor(Date.now() / 1000) + this._serverTimeOffset,
        expired: Math.floor(Date.now() / 1000) + this._serverTimeOffset + 86400,
      })

      this._socketTask.send({
        data: initMsg,
        success: () => {
          if (this.isLog) console.log('[TencentASR] 初始化消息已发送')
          this._pendingInit = false
          this.onStart()
          // 发送累积的音频数据
          this._flushChunks()
        },
        fail: err => {
          this.onError('[TencentASR] 发送初始化消息失败: ' + JSON.stringify(err))
        }
      })
    })

    this._socketTask.onMessage(res => {
      this._handleMessage(res.data)
    })

    this._socketTask.onError(err => {
      if (this.isLog) console.error('[TencentASR] WebSocket 错误:', err)
      this.onError('[TencentASR] 连接错误: ' + JSON.stringify(err))
    })

    this._socketTask.onClose(res => {
      if (this.isLog) console.log('[TencentASR] WebSocket 关闭', res)
      if (!this._isEnded) {
        this.onError('[TencentASR] 连接异常关闭')
      }
      this._isStarted = false
      this._socketTask = null
    })
  }

  _flushChunks() {
    // 发送所有累积的音频数据
    while (this._audioChunks.length > 0) {
      const chunk = this._audioChunks.shift()
      this._sendAudioChunk(chunk)
    }
  }

  _sendAudioChunk(chunkData) {
    if (!this._socketTask || !this._isStarted || this._isEnded) return

    // 确保是 ArrayBuffer
    let buffer
    if (chunkData instanceof ArrayBuffer) {
      buffer = chunkData
    } else if (chunkData instanceof Int8Array || chunkData instanceof Uint8Array) {
      buffer = chunkData.buffer.slice(chunkData.byteOffset, chunkData.byteOffset + chunkData.byteLength)
    } else {
      buffer = chunkData
    }

    try {
      this._socketTask.send({
        data: buffer,
        success: () => {},
        fail: err => {
          if (this.isLog) console.error('[TencentASR] 发送音频失败:', err)
        }
      })
    } catch (e) {
      if (this.isLog) console.error('[TencentASR] sendAudio error:', e)
    }
  }

  _handleMessage(data) {
    try {
      let msg
      if (typeof data === 'string') {
        msg = JSON.parse(data)
      } else {
        // 二进制消息（可能是音频响应）
        // 腾讯 ASR 识别结果通常是 JSON
        const decoder = new TextDecoder()
        msg = JSON.parse(decoder.decode(data))
      }

      if (this.isLog) console.log('[TencentASR] 收到消息:', JSON.stringify(msg).substring(0, 200))

      const code = msg.code
      if (code !== undefined && code !== 0) {
        this.onError(`[TencentASR] ASR 错误码: ${code}, 详情: ${msg.message || ''}`)
        return
      }

      // 识别开始
      if (msg.result && !this._hasStartedRecognition) {
        this._hasStartedRecognition = true
        this.onRecognitionStart()
      }

      // 结果处理
      if (msg.result) {
        const sliceType = msg.result.slice_type  // 0=开始, 1=结束, 2=中间
        const text = msg.result.text || ''

        if (sliceType === 0) {
          // 一句话开始
          this.onSentenceBegin()
          this._currentText = text
        } else if (sliceType === 1) {
          // 一句话结束（最终结果）
          this.onSentenceEnd(text)
          this._currentText = ''
        } else if (sliceType === 2) {
          // 中间结果
          this._currentText = text
          this.onResultChange(text)
        }
      }

      // 识别完成
      if (msg.is_final === true || msg.final === 1) {
        this.onComplete(msg.result?.text || '')
      }

      // Connection close
      if (msg.connection_closed === true) {
        if (this.isLog) console.log('[TencentASR] 服务端关闭连接')
        this._close()
      }

    } catch (e) {
      // 无法解析，可能是二进制数据或空消息
      if (this.isLog) console.log('[TencentASR] 消息解析失败:', e, typeof data, data?.byteLength)
    }
  }
}

// ─── 导出 ─────────────────────────────────────────────────────────────────
module.exports = TencentASR
