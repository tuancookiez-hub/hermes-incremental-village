// The village's sound, made entirely here with Web Audio: no files, nothing fetched. It starts only
// after the player turns it on, because a plugin should not make noise unasked.

const FULL = 0.5

export function createSound() {
  let ac = null
  let master = null
  let windGain = null
  let on = false
  let nextCall = 0

  function noise(seconds) {
    const buffer = ac.createBuffer(1, ac.sampleRate * seconds, ac.sampleRate)
    const data = buffer.getChannelData(0)
    let last = 0
    for (let i = 0; i < data.length; i++) {
      last = last * 0.97 + (Math.random() * 2 - 1) * 0.03 // soft, reddish noise reads as air, not hiss
      data[i] = last * 8
    }
    return buffer
  }

  function wake() {
    if (ac) return
    const Ctx = window.AudioContext ?? window.webkitAudioContext
    if (!Ctx) return
    ac = new Ctx()
    master = ac.createGain()
    master.gain.value = 0
    master.connect(ac.destination)
    const wind = ac.createBufferSource()
    wind.buffer = noise(6)
    wind.loop = true
    const air = ac.createBiquadFilter()
    air.type = 'lowpass'
    air.frequency.value = 520
    windGain = ac.createGain()
    windGain.gain.value = 0.05
    wind.connect(air).connect(windGain).connect(master)
    wind.start()
  }

  function tone(freq, start, length, volume, type = 'sine', slide = 1) {
    const osc = ac.createOscillator()
    const gain = ac.createGain()
    osc.type = type
    osc.frequency.setValueAtTime(freq, start)
    osc.frequency.exponentialRampToValueAtTime(freq * slide, start + length)
    gain.gain.setValueAtTime(0.0001, start)
    gain.gain.exponentialRampToValueAtTime(volume, start + Math.min(0.03, length / 3))
    gain.gain.exponentialRampToValueAtTime(0.0001, start + length)
    osc.connect(gain).connect(master)
    osc.start(start)
    osc.stop(start + length + 0.02)
  }

  function bird(at) {
    const base = 2400 + Math.random() * 1600
    const notes = 2 + Math.floor(Math.random() * 3)
    for (let i = 0; i < notes; i++) tone(base * (1 + Math.random() * 0.25), at + i * 0.13, 0.09, 0.05, 'sine', 0.85 + Math.random() * 0.4)
  }

  function cricket(at) {
    for (let i = 0; i < 3; i++) tone(4300, at + i * 0.07, 0.04, 0.012, 'triangle')
  }

  /** Called a few times a second with what the day looks like. */
  function tick({ phase, season, paused }) {
    if (!on || !ac) return
    const now = ac.currentTime
    const cold = season === 'winter'
    windGain.gain.setTargetAtTime(paused ? 0.02 : cold ? 0.16 : 0.05, now, 1.2)
    if (paused || cold || now < nextCall) return
    if (phase === 'Night' || phase === 'Dusk') {
      if (season !== 'spring') cricket(now)
      nextCall = now + 0.7 + Math.random() * 1.6
    } else {
      bird(now)
      nextCall = now + 2.5 + Math.random() * 6
    }
  }

  /** A moment worth marking: someone died, or the village learned something. */
  function cue(kind) {
    if (!on || !ac) return
    const now = ac.currentTime
    if (kind === 'death') {
      tone(196, now, 2.6, 0.18)
      tone(233, now + 0.04, 2.4, 0.09)
    } else if (kind === 'learn') {
      tone(523, now, 0.5, 0.08)
      tone(659, now + 0.13, 0.6, 0.08)
      tone(784, now + 0.26, 0.9, 0.08)
    }
  }

  return {
    set(value) {
      on = !!value
      if (on) {
        wake()
        void ac?.resume?.()
      }
      if (master) master.gain.setTargetAtTime(on ? FULL : 0, ac.currentTime, 0.3)
    },
    tick,
    cue,
    dispose() {
      on = false
      void ac?.close?.()
      ac = null
    }
  }
}
