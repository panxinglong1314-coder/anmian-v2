/**
 * 实时流 ASR 集成层 - 双向贯通版
 *
 * 连接后端 WebSocket 端点 (/api/v1/asr/ws)，后端转发到腾讯 ASR
 * 不再在前端存 credentials，更安全
 *
 * 协议：
 * - 发送到后端：二进制 PCM（RecorderManager.onFrameRecorded）
 * - 发送到后端：{"type": "end"} JSON 结束标记
 * - 从后端接收：{"text": "...", "slice_type": 2, "is_final": false}  中间结果
 * - 从后端接收：{"text": "...", "slice_type": 1, "is_final": true}   最终结果
 * - 从后端接收：{"done": true}  识别完成
 * - 从后端接收：{"error": "..."}  错误
 */

'use strict'

const recorderManager = wx.getRecorderManager()

// Mini Program 全局 app 实例
let app = null
try { app = getApp() } catch (e) {}

class RealtimeASRHandler {
  constructor(options = {}) {
    // 后端 API 地址（不需要 credentials）
    this.apiBaseUrl = options.apiBaseUrl || 'https://sleepai.chat'
    // WebSocket 版本用 wss
    this.wsBaseUrl = this.apiBaseUrl.replace('http://', 'ws://').replace('https://', 'wss://')
    this.userId = options.userId || 'anon_default'
    this.sessionId = options.sessionId || 'session_' + Date.now()

    // 事件回调
    this.onIntermediateResult = options.onIntermediateResult || (() => {})
    this.onFinalResult = options.onFinalResult || (() => {})
    this.onResponse = options.onResponse || (() => {})
    this.onError = options.onError || (() => {})
    this.onListening = options.onListening || (() => {})
    this.onSpeaking = options.onSpeaking || (() => {})  // AI 正在说话

    this._socketTask = null
    this._isListening = false
    this._pendingText = ''
    this._audioBuffer = []
    this._sendTimer = null
    this._recorderManager = null
    this._accumulatedBytes = 0
    this._finalText = ''
  }

  /**
   * 开始监听（VAD 检测到声音后调用）
   * @param {string} vadFilePath - VAD 已录到的音频文件路径（第一段）
   */
  startListening(vadFilePath = null) {
    if (this._isListening) return
    this._isListening = true
    this._pendingText = ''
    this._finalText = ''
    this._audioBuffer = []
    this._accumulatedBytes = 0

    console.log('[RealtimeASRHandler] 启动实时流ASR（连接后端WS）')
    this._connectWS()
  }

  /**
   * 停止监听
   */
  stopListening() {
    if (!this._isListening) return
    this._isListening = false

    this._stopRecorder()
    this._flushRemaining()
    this._sendEnd()

    // 延迟关闭 WebSocket，等腾讯返回最终结果
    setTimeout(() => {
      this._closeWS()
    }, 3000)
  }

  // ─── WebSocket 连接（连接后端）────────────────────────────────────────

  _connectWS() {
    const url = `${this.wsBaseUrl}/api/v1/asr/ws`
    console.log('[RealtimeASRHandler] 连接后端 ASR WS:', url)

    this._socketTask = wx.connectSocket({ url })

    this._socketTask.onOpen(() => {
      console.log('[RealtimeASRHandler] 后端 WS 已连接')
      this.onListening()
      this._startRecorder()
    })

    this._socketTask.onMessage(res => {
      this._handleWSMessage(res.data)
    })

    this._socketTask.onError(err => {
      console.error('[RealtimeASRHandler] WS 错误:', err)
      this._stopRecorder()
      this.onError('ASR 连接失败，请重试')
    })

    this._socketTask.onClose(res => {
      console.log('[RealtimeASRHandler] WS 关闭', res)
      this._isListening = false
      this._stopRecorder()
    })
  }

  _handleWSMessage(data) {
    try {
      const msg = typeof data === 'string' ? JSON.parse(data) : data

      if (msg.error) {
        console.error('[RealtimeASRHandler] ASR错误:', msg.error)
        this.onError(msg.error)
        return
      }

      if (msg.done) {
        console.log('[RealtimeASRHandler] 识别完成，最终文本:', this._finalText)
        if (this._finalText.trim()) {
          this._sendToCBT(this._finalText.trim())
        }
        return
      }

      if (msg.text && msg.slice_type !== undefined) {
        // slice_type: 0=开始, 1=最终, 2=中间
        console.log(`[RealtimeASRHandler] 结果 slice_type=${msg.slice_type}:`, msg.text)
        this._pendingText = msg.text

        if (msg.is_final || msg.slice_type === 1) {
          // 最终结果
          this._finalText = msg.text
          this.onFinalResult(msg.text)
        } else {
          // 中间结果
          this.onIntermediateResult(msg.text)
        }
      }
    } catch (e) {
      console.warn('[RealtimeASRHandler] 消息解析失败:', e)
    }
  }

  _sendPCM(buffer) {
    if (!this._socketTask || !this._isListening) return
    try {
      this._socketTask.send({
        data: buffer,
        fail: err => console.error('[RealtimeASRHandler] 发送PCM失败:', err)
      })
    } catch (e) {
      console.error('[RealtimeASRHandler] send error:', e)
    }
  }

  _sendEnd() {
    if (!this._socketTask) return
    try {
      this._socketTask.send({
        data: JSON.stringify({ type: 'end' }),
        fail: err => console.error('[RealtimeASRHandler] 发送end失败:', err)
      })
    } catch (e) {}
  }

  _closeWS() {
    if (this._socketTask) {
      try { this._socketTask.close() } catch (e) {}
      this._socketTask = null
    }
  }

  // ─── 录音管理 ───────────────────────────────────────────────────────

  _startRecorder() {
    const rm = wx.getRecorderManager()

    const recordOptions = {
      format: 'pcm',
      sampleRate: 16000,
      numberOfChannels: 1,
      encodeBitRate: 32000,
      duration: 60000,
    }

    rm.onStart(() => {
      console.log('[RealtimeASRHandler] 录音已开始 (PCM 16kHz)')
      this._isListening = true
      // 每100ms发送一次累积数据
      this._sendTimer = setInterval(() => {
        this._flushAccumulated()
      }, 100)
    })

    rm.onFrameRecorded(res => {
      if (!this._isListening) return
      const { frameBuffer, isLastFrame } = res
      if (!frameBuffer) return

      this._audioBuffer.push(frameBuffer)
      this._accumulatedBytes += frameBuffer.byteLength

      // 超过200ms数据立即发送
      if (this._accumulatedBytes >= 3200 * 2) {
        this._flushAccumulated()
      }

      if (isLastFrame) {
        console.log('[RealtimeASRHandler] 录音结束（isLastFrame）')
        this._isListening = false
        this._flushRemaining()
        this._sendEnd()
        if (this._sendTimer) {
          clearInterval(this._sendTimer)
          this._sendTimer = null
        }
      }
    })

    rm.onError(err => {
      console.error('[RealtimeASRHandler] 录音错误:', err)
      this._isListening = false
      if (this._sendTimer) {
        clearInterval(this._sendTimer)
        this._sendTimer = null
      }
    })

    rm.onStop(res => {
      console.log('[RealtimeASRHandler] 录音停止')
      if (this._isListening) {
        this._isListening = false
        this._flushRemaining()
        this._sendEnd()
      }
      if (this._sendTimer) {
        clearInterval(this._sendTimer)
        this._sendTimer = null
      }
    })

    try {
      rm.start(recordOptions)
      this._recorderManager = rm
    } catch (e) {
      console.error('[RealtimeASRHandler] 启动录音失败:', e)
      // fallback 到 AAC 格式
      recordOptions.format = 'aac'
      try {
        rm.start(recordOptions)
        this._recorderManager = rm
        console.log('[RealtimeASRHandler] 回退到 AAC 格式')
      } catch (e2) {
        this.onError('无法启动录音: ' + e2.message)
      }
    }
  }

  _stopRecorder() {
    if (this._recorderManager) {
      try { this._recorderManager.stop() } catch (e) {}
      this._recorderManager = null
    }
    if (this._sendTimer) {
      clearInterval(this._sendTimer)
      this._sendTimer = null
    }
  }

  _flushAccumulated() {
    if (this._audioBuffer.length === 0) return

    const totalSize = this._audioBuffer.reduce((sum, b) => sum + b.byteLength, 0)
    if (totalSize < 320) return  // 小于100ms不发送

    const merged = new ArrayBuffer(totalSize)
    const view = new Uint8Array(merged)
    let offset = 0
    for (const buf of this._audioBuffer) {
      const u8 = new Uint8Array(buf)
      view.set(u8, offset)
      offset += u8.byteLength
    }

    this._sendPCM(merged)
    this._audioBuffer = []
    this._accumulatedBytes = 0
  }

  _flushRemaining() {
    if (this._audioBuffer.length === 0) return
    this._flushAccumulated()
  }

  // ─── 发送给 CBT ──────────────────────────────────────────────────────

  _sendToCBT(text) {
    console.log('[RealtimeASRHandler] 发送CBT:', text)
    this.onSpeaking()

    wx.request({
      url: `${this.apiBaseUrl}/api/v1/chat/cbt`,
      method: 'POST',
      header: { 'Content-Type': 'application/json' },
      data: {
        user_id: this.userId,
        message: text,
        session_id: this.sessionId,
      },
      success: (res) => {
        if (res.statusCode !== 200 || !res.data?.response) {
          this.onError('服务暂时不稳定，请重试')
          return
        }
        const responseText = res.data.response
        const ttsParams = res.data.tts_params || { rate: 1.0 }
        console.log('[RealtimeASRHandler] CBT回复:', responseText.substring(0, 100))
        this.onResponse(responseText, ttsParams)
      },
      fail: (err) => {
        console.error('[RealtimeASRHandler] CBT请求失败:', err)
        this.onError('网络不稳定，请重试')
      }
    })
  }
}

module.exports = RealtimeASRHandler
