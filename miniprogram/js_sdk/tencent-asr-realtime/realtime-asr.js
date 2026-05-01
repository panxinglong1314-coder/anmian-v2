/**
 * 腾讯云实时语音识别 — Mini Program 流式版
 *
 * 真正的流式采集 + 流式识别：
 * 1. RecorderManager 以 PCM 16kHz 采集（onFrame 回调）
 * 2. 通过 WebSocket 实时发送 PCM chunk 到腾讯云 ASR
 * 3. 实时接收增量识别结果
 *
 * 注意：需要微信基础库 2.26+ 支持 onFrame 回调的 PCM 模式
 */

'use strict'

const TencentASR = require('./speechrecognizer.js')

// PCM 16kHz 单声道 每100ms的数据量: 16000 * 0.1 * 2 = 3200 bytes
const CHUNK_DURATION_MS = 100
const SAMPLE_RATE = 16000
const BITS_PER_SAMPLE = 16
const CHUNK_SIZE = Math.floor(SAMPLE_RATE * CHUNK_DURATION_MS / 1000) * 2  // bytes

class RealtimeASR {
  constructor(options = {}) {
    this.appid = options.appid || ''
    this.secretid = options.secretid || ''
    this.secretkey = options.secretkey || ''

    // 录音参数
    this.sampleRate = options.sampleRate || 16000
    this.numberOfChannels = options.numberOfChannels || 1
    this.encodeBitRate = options.encodeBitRate || 32000

    // 识别回调
    this.onRecognized = options.onRecognized || (() => {})
    this.onIntermediateResult = options.onIntermediateResult || (() => {})
    this.onError = options.onError || (() => {})
    this.onStart = options.onStart || (() => {})
    this.onEnd = options.onEnd || (() => {})

    this._asr = null
    this._recorderManager = null
    this._isRecording = false
    this._audioBuffer = []  // 累积的 PCM 数据
    this._lastSendTime = 0
    this._accumulatedBytes = 0
    this._sendTimer = null
  }

  /**
   * 开始录音 + 识别
   */
  start() {
    if (this._isRecording) return

    this._isRecording = true
    this._audioBuffer = []
    this._accumulatedBytes = 0
    this._lastSendTime = Date.now()

    // 初始化 ASR
    this._asr = new TencentASR({
      appid: this.appid,
      secretid: this.secretid,
      secretkey: this.secretkey,
      engine_model_type: '16k_zh',
      voice_format: 1,  // PCM
      isLog: true,
    })

    this._asr.onStart = () => {
      console.log('[RealtimeASR] ASR 已启动')
      this.onStart()
    }

    this._asr.onSentenceBegin = () => {
      console.log('[RealtimeASR] 一句话开始')
    }

    this._asr.onResultChange = (text) => {
      if (text) {
        console.log('[RealtimeASR] 中间结果:', text)
        this.onIntermediateResult(text)
      }
    }

    this._asr.onSentenceEnd = (text) => {
      console.log('[RealtimeASR] 句子结束:', text)
      if (text) this.onRecognized(text)
    }

    this._asr.onComplete = (finalText) => {
      if (finalText) this.onRecognized(finalText)
    }

    this._asr.onError = (err) => {
      console.error('[RealtimeASR] ASR 错误:', err)
      this.onError(err)
    }

    // 启动 ASR WebSocket
    this._asr.start()

    // 启动录音
    this._startRecorder()
  }

  /**
   * 停止录音 + 识别
   */
  stop() {
    if (!this._isRecording) return
    this._isRecording = false

    // 停止录音
    if (this._recorderManager) {
      try { this._recorderManager.stop() } catch (e) {}
    }

    // 发送剩余数据
    this._flushRemaining()

    // 结束 ASR
    if (this._asr) {
      this._asr.stop()
      this._asr = null
    }

    if (this._sendTimer) {
      clearInterval(this._sendTimer)
      this._sendTimer = null
    }

    this.onEnd()
  }

  // ─── 私有方法 ──────────────────────────────────────────────────────────

  _startRecorder() {
    const recorderManager = wx.getRecorderManager()

    // 使用 onFrame 回调获取原始音频数据（需要微信 2.26+）
    // format: 'pcm' 时，onFrame 回调返回原始 PCM 数据
    const recordOptions = {
      format: 'pcm',
      sampleRate: this.sampleRate,
      numberOfChannels: this.numberOfChannels,
      encodeBitRate: this.encodeBitRate,
      // duration 必须设置，否则真机上可能没有 onFrame 回调
      duration: 60000,  // 最大 60 秒
    }

    console.log('[RealtimeASR] 开始录音, options:', JSON.stringify(recordOptions))

    recorderManager.onStart(() => {
      console.log('[RealtimeASR] 录音已开始 (PCM 16kHz)')
      this._isRecording = true

      // 定期（每100ms）发送累积数据
      this._sendTimer = setInterval(() => {
        this._flushAccumulated()
      }, CHUNK_DURATION_MS)
    })

    // onFrame: 实时获取音频帧数据（仅 PCM 格式支持）
    recorderManager.onFrameRecorded((res) => {
      if (!this._isRecording) return

      const { frameBuffer, isLastFrame } = res
      if (!frameBuffer) return

      // frameBuffer 是 ArrayBuffer（原始 PCM）
      this._audioBuffer.push(frameBuffer)
      this._accumulatedBytes += frameBuffer.byteLength

      // 如果累积超过 200ms 数据，立即发送（降低延迟）
      if (this._accumulatedBytes >= CHUNK_SIZE * 2) {
        this._flushAccumulated()
      }

      if (isLastFrame) {
        console.log('[RealtimeASR] 录音结束（收到 isLastFrame）')
        this._isRecording = false
        this._flushRemaining()
        if (this._asr) this._asr.stop()
        if (this._sendTimer) {
          clearInterval(this._sendTimer)
          this._sendTimer = null
        }
      }
    })

    recorderManager.onError((err) => {
      console.error('[RealtimeASR] 录音错误:', err)
      this.onError('[RealtimeASR] 录音错误: ' + JSON.stringify(err))
      this._isRecording = false
      if (this._sendTimer) {
        clearInterval(this._sendTimer)
        this._sendTimer = null
      }
    })

    recorderManager.onStop((res) => {
      console.log('[RealtimeASR] 录音停止, duration=', res.duration, 'fileSize=', res.fileSize)
      if (this._isRecording) {
        this._isRecording = false
        this._flushRemaining()
        if (this._asr) this._asr.stop()
      }
      if (this._sendTimer) {
        clearInterval(this._sendTimer)
        this._sendTimer = null
      }
    })

    // 开始录音
    try {
      recorderManager.start(recordOptions)
      this._recorderManager = recorderManager
    } catch (e) {
      console.error('[RealtimeASR] start() 失败:', e)
      // fallback: format 可能是 pcm 不支持，改用 aac
      recordOptions.format = 'aac'
      try {
        recorderManager.start(recordOptions)
        this._recorderManager = recorderManager
        console.log('[RealtimeASR] 回退到 AAC 格式录制')
      } catch (e2) {
        this.onError('[RealtimeASR] 无法启动录音: ' + e2.message)
      }
    }
  }

  _flushAccumulated() {
    if (this._audioBuffer.length === 0 || !this._asr || !this._asr._isStarted) return

    // 合并所有 buffer
    const totalSize = this._audioBuffer.reduce((sum, b) => sum + b.byteLength, 0)
    if (totalSize < 320) return  // 小于 100ms 的数据不发送

    // 合并成一个 ArrayBuffer
    const merged = new ArrayBuffer(totalSize)
    const view = new Uint8Array(merged)
    let offset = 0
    for (const buf of this._audioBuffer) {
      const u8 = new Uint8Array(buf)
      view.set(u8, offset)
      offset += u8.byteLength
    }

    // 发送
    this._asr.sendAudio(merged)
    this._audioBuffer = []
    this._accumulatedBytes = 0
    this._lastSendTime = Date.now()
  }

  _flushRemaining() {
    if (this._audioBuffer.length === 0) return
    this._flushAccumulated()
  }
}

// ─── 导出 ─────────────────────────────────────────────────────────────────
module.exports = RealtimeASR
