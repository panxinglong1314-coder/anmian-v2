// pages/train/train.js
// Tab 2: 睡前训练 - 逻辑

const app = getApp()

Page({
  data: {
    // 当前选中的训练
    activeTrain: null,

    // 播放状态
    isPlaying: false,
    playing: false,
    volume: 70,

    // 计时器
    trainTimer: null,
    elapsedTime: '00:00',
    trainProgress: 0,

    // 呼吸训练
    breathingProgress: 0,
    currentPhase: 'ready',    // ready / inhale / hold / exhale
    currentPhaseText: '',
    currentCycle: 1,
    totalCycles: 4,
    phaseTimer: null,

    // 训练配置
    trainConfig: {
      breathing_478: {
        type: 'breathing_478',
        icon: '🌬️',
        title: '4-7-8 呼吸法',
        desc: '吸气4秒 · 屏息7秒 · 呼气8秒，重复4轮',
        duration: '约 3 分钟',
        phases: [
          { phase: 'inhale',   text: '吸气 4秒', tip: '用鼻子轻轻吸气...', duration: 4 },
          { phase: 'hold',     text: '屏息 7秒', tip: '屏住呼吸，保持安静...', duration: 7 },
          { phase: 'exhale',   text: '呼气 8秒', tip: '用嘴缓慢呼出...', duration: 8 }
        ],
        totalSeconds: 76
      },
      body_scan: {
        type: 'body_scan',
        icon: '🧘',
        title: '身体扫描冥想',
        desc: '从脚趾到头顶，逐部位感受并放松',
        duration: '约 5 分钟',
        totalSeconds: 300
      },
      white_noise: {
        type: 'white_noise',
        icon: '🌧️',
        title: '白噪音·雨声',
        desc: '轻柔雨声，沉浸式助眠',
        duration: '持续',
        totalSeconds: 0
      },
      muscle_relax: {
        type: 'muscle_relax',
        icon: '💆',
        title: '渐进式肌肉放松',
        desc: '交替收紧和放松各肌肉群，从头到脚',
        duration: '约 8 分钟',
        totalSeconds: 480
      },
      guided_imagery: {
        type: 'guided_imagery',
        icon: '🏔️',
        title: '引导想象·森林',
        desc: '漫步在宁静的森林中，随风放松',
        duration: '约 6 分钟',
        totalSeconds: 360
      }
    }
  },

  onLoad() {
    // nothing
  },

  // ========== 选择训练 ==========
  onSelectTrain(e) {
    const type = e.currentTarget.dataset.type
    const config = this.data.trainConfig[type]
    if (!config) return

    this.setData({ activeTrain: config })
  },

  // ========== 关闭训练弹窗 ==========
  onCloseTrain() {
    this.pauseAll()
    this.setData({
      activeTrain: null,
      isPlaying: false,
      playing: false,
      trainProgress: 0,
      elapsedTime: '00:00'
    })
  },

  // ========== 开始训练 ==========
  onStartTrain() {
    const train = this.data.activeTrain
    if (!train) return

    if (train.type === 'breathing_478') {
      this.startBreathing(train)
    } else if (train.type === 'white_noise') {
      this.startWhiteNoise()
    } else {
      this.startGenericTrain(train)
    }
  },

  // ========== 暂停训练 ==========
  onPauseTrain() {
    if (this.data.activeTrain?.type === 'white_noise') {
      this.pauseWhiteNoise()
    } else {
      this.pauseGenericTrain()
    }
  },

  // ========== 通用计时训练 ==========
  startGenericTrain(train) {
    let elapsed = 0
    const total = train.totalSeconds

    const timer = setInterval(() => {
      elapsed++

      const progress = total > 0 ? (elapsed / total) * 100 : 0
      const minutes = Math.floor(elapsed / 60)
      const seconds = elapsed % 60

      this.setData({
        isPlaying: true,
        elapsedTime: `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`,
        trainProgress: Math.min(progress, 100)
      })

      if (elapsed >= total) {
        clearInterval(timer)
        this.setData({ isPlaying: false })
        wx.showToast({ title: '训练完成 🎉', icon: 'none' })
      }
    }, 1000)

    this.data.trainTimer = timer
  },

  pauseGenericTrain() {
    const timer = this.data.trainTimer
    if (timer) clearInterval(timer)
    this.setData({ isPlaying: false })
  },

  // ========== 4-7-8 呼吸训练 ==========
  startBreathing(train) {
    const phases = train.phases
    let phaseIndex = 0
    let cycle = 1
    let phaseElapsed = 0

    this.setData({ isPlaying: true, currentPhaseText: '准备开始', currentPhase: 'ready' })

    const timer = setInterval(() => {
      phaseElapsed++

      const currentPhase = phases[phaseIndex]
      const phaseDuration = currentPhase.duration
      const totalDuration = train.totalSeconds

      // 更新进度
      let totalElapsed = 0
      for (let i = 0; i < phaseIndex; i++) {
        totalElapsed += phases[i].duration
      }
      totalElapsed += phaseElapsed

      const progress = (totalElapsed / totalDuration) * 100
      this.setData({
        breathingProgress: Math.min(progress, 100),
        currentPhaseText: currentPhase.text,
        currentPhase: phaseIndex === 0 ? 'inhale' : (phaseIndex === 1 ? 'hold' : 'exhale'),
        phaseTip: currentPhase.tip,
        currentCycle: cycle
      })

      // 阶段切换
      if (phaseElapsed >= phaseDuration) {
        phaseElapsed = 0
        phaseIndex++

        if (phaseIndex >= phases.length) {
          phaseIndex = 0
          cycle++
          if (cycle > this.data.totalCycles) {
            clearInterval(timer)
            this.setData({ isPlaying: false, currentPhaseText: '完成', currentPhase: 'exhale' })
            wx.showToast({ title: '呼吸训练完成 🎉', icon: 'none' })
            return
          }
        }

        this.setData({ currentCycle: cycle })
      }
    }, 1000)

    this.data.phaseTimer = timer
  },

  // ========== 白噪音 ==========
  startWhiteNoise() {
    // 实际项目中这里会调用 innerAudioContext
    // 这里用模拟替代
    this.setData({ playing: true, isPlaying: true })
    wx.showToast({ title: '🔊 雨声播放中', icon: 'none', duration: 1500 })
  },

  pauseWhiteNoise() {
    this.setData({ playing: false, isPlaying: false })
  },

  onToggleSound() {
    if (this.data.playing) {
      this.pauseWhiteNoise()
    } else {
      this.startWhiteNoise()
    }
  },

  onVolumeChange(e) {
    this.setData({ volume: e.detail.value })
  },

  // ========== 统一停止所有训练 ==========
  pauseAll() {
    const timer = this.data.trainTimer
    const phaseTimer = this.data.phaseTimer
    if (timer) clearInterval(timer)
    if (phaseTimer) clearInterval(phaseTimer)
  },

  onUnload() {
    this.pauseAll()
  }
})
