// Reliable, session-long browser TTS for monitoring alerts.
//
// The browser speechSynthesis API is stateful and can occasionally get stuck
// after a long run. We therefore keep a single FIFO queue, never overlap
// utterances, and use a watchdog to recover a stalled utterance. We also
// serialize all access through one scheduler so a burst of alerts cannot
// exhaust the browser's speech queue.

const SUPPORTED = typeof window !== 'undefined' && 'speechSynthesis' in window
const queue = []
const spokenKeys = new Map()
const MAX_QUEUE = 50
const DEBOUNCE_MS = 1200
const WATCHDOG_GRACE_MS = 2500

let speaking = false
let currentUtterance = null
let watchdogTimer = null
let recoveryAttempts = 0

function clearWatchdog() {
  if (watchdogTimer) {
    window.clearTimeout(watchdogTimer)
    watchdogTimer = null
  }
}

function estimateDurationMs(text) {
  // ~165 words/minute plus a small browser/voice startup allowance.
  const words = String(text || '').trim().split(/\s+/).filter(Boolean).length
  return Math.max(3500, Math.min(30000, (words / 2.75) * 1000 + WATCHDOG_GRACE_MS))
}

function finishCurrent() {
  clearWatchdog()
  speaking = false
  currentUtterance = null
  recoveryAttempts = 0
  pumpQueue()
}

function recoverStalledSpeech() {
  if (!SUPPORTED || !speaking) return

  // Cancel only the stuck utterance. It does not clear our own FIFO queue.
  try { window.speechSynthesis.cancel() } catch { /* browser-specific */ }
  currentUtterance = null
  speaking = false

  // Give the browser a tick before starting the next utterance. This avoids
  // the common Chrome state where speak() immediately after cancel() is lost.
  window.setTimeout(() => pumpQueue(), 80)
}

function speakOne(item) {
  if (!SUPPORTED) return
  speaking = true
  recoveryAttempts = item.retryCount || 0

  const utterance = new SpeechSynthesisUtterance(item.message)
  currentUtterance = utterance
  utterance.rate = 0.95
  utterance.pitch = 1
  utterance.volume = 1

  const done = () => {
    if (currentUtterance !== utterance) return
    finishCurrent()
  }

  utterance.onend = done
  utterance.onerror = (event) => {
    if (currentUtterance !== utterance) return

    // 'interrupted'/'canceled' can be caused by our own recovery path. Retry
    // once for transient browser failures; otherwise continue the queue.
    const transient = ['interrupted', 'canceled', 'synthesis-failed', 'audio-busy'].includes(event?.error)
    if (transient && recoveryAttempts < 1) {
      clearWatchdog()
      currentUtterance = null
      speaking = false
      queue.unshift({ ...item, retryCount: recoveryAttempts + 1 })
      window.setTimeout(pumpQueue, 120)
      return
    }
    finishCurrent()
  }

  try {
    window.speechSynthesis.speak(utterance)
  } catch {
    if (recoveryAttempts < 1) {
      speaking = false
      currentUtterance = null
      queue.unshift({ ...item, retryCount: recoveryAttempts + 1 })
      window.setTimeout(pumpQueue, 150)
      return
    }
    finishCurrent()
    return
  }

  clearWatchdog()
  watchdogTimer = window.setTimeout(() => {
    // If the browser reports neither onend nor onerror within a reasonable
    // time, it is almost certainly stuck. Recover without dropping later
    // alerts from our queue.
    if (currentUtterance === utterance && speaking) {
      recoverStalledSpeech()
      if (recoveryAttempts < 1) {
        queue.unshift({ ...item, retryCount: recoveryAttempts + 1 })
      }
    }
  }, estimateDurationMs(item.message))
}

function pumpQueue() {
  if (!SUPPORTED || speaking || queue.length === 0) return

  // If Chrome left the engine paused/stuck between utterances, reset it before
  // starting the next item. We never use pause()/resume() while speaking.
  try {
    if (window.speechSynthesis.paused) window.speechSynthesis.resume()
  } catch { /* browser-specific */ }

  const item = queue.shift()
  speakOne(item)
}

function enqueue(message, key = message) {
  if (!SUPPORTED || !message) return

  const now = Date.now()
  const lastAt = spokenKeys.get(key) || 0
  if (now - lastAt < DEBOUNCE_MS) return
  spokenKeys.set(key, now)

  if (spokenKeys.size > 1000) {
    for (const [k, timestamp] of spokenKeys) {
      if (now - timestamp > DEBOUNCE_MS) spokenKeys.delete(k)
    }
  }

  queue.push({ message, retryCount: 0 })
  if (queue.length > MAX_QUEUE) queue.splice(0, queue.length - MAX_QUEUE)
  pumpQueue()
}

if (SUPPORTED) {
  const loadVoices = () => window.speechSynthesis.getVoices()
  loadVoices()
  window.speechSynthesis.addEventListener?.('voiceschanged', loadVoices)

  // If the engine becomes paused while we are speaking, resume it. This is a
  // lightweight health check; unlike the previous implementation it does not
  // pause/resume every 10 seconds, which could itself interrupt speech.
  window.setInterval(() => {
    if (!speaking) return
    try {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume()
    } catch { /* browser-specific */ }
  }, 2500)
}

export function speakAttentivenessAlert(data, { self = false } = {}) {
  const reason = data?.reason || 'an attentiveness issue'
  const elapsed = Number(data?.elapsed || 0)
  const seconds = Math.max(1, Math.round(elapsed))
  const who = data?.who || 'A participant'

  if (self) {
    const selfText =
      reason === 'Looking away'
        ? `Please alert. You are looking away for ${seconds} seconds.`
        : reason === 'Eyes closed / drowsy'
          ? `Please alert. Your eyes are closed for ${seconds} seconds.`
          : reason === 'Away from camera'
            ? `Please alert. Your face is not visible to the camera for ${seconds} seconds.`
            : reason === 'Extra person present'
              ? `Please alert. An extra person is present in your camera.`
              : `Please alert. ${reason} for ${seconds} seconds.`
    enqueue(selfText, `self-attention|${reason}|${seconds}`)
    return
  }

  enqueue(`Attention alert. ${who} is ${reason.toLowerCase()} for ${seconds} seconds.`, `host-attention|${who}|${reason}|${seconds}`)
}

export function speakIdentityMismatchAlert(data, { self = false } = {}) {
  const claimed = data?.claimed_name || 'This participant'
  const recognized = data?.recognized_name

  if (self) {
    const text = recognized
      ? `Please alert. Your face does not match your claimed identity. The camera recognizes ${recognized}.`
      : `Please alert. Your face does not match your claimed identity.`
    enqueue(text, `self-identity|${claimed}|${recognized || 'unknown'}`)
    return
  }

  const text = recognized
    ? `Attention alert. ${claimed}'s identity does not match. The face is recognized as ${recognized}.`
    : `Attention alert. ${claimed}'s identity does not match the registered face.`
  enqueue(text, `host-identity|${claimed}|${recognized || 'unknown'}`)
}

export function speakExtraPersonAlert(data, { self = false } = {}) {
  const who = data?.who || data?.claimed_name || 'A participant'
  if (self) enqueue('Please alert. Another person is present in your camera.', `self-extra|${who}`)
  else enqueue(`Attention alert. ${who} has another person present in the camera.`, `host-extra|${who}`)
}

export function speakUnknownPersonAlert(data) {
  const nearby = data?.nearby_student?.name
  const text = nearby
    ? `Attention alert. The face in ${nearby}'s place does not match the registered identity.`
    : `Attention alert. An unknown face is present.`
  enqueue(text, `unknown|${data?.unknown_id || nearby || 'unknown'}`)
}

export function stopVoiceAlerts() {
  if (!SUPPORTED) return
  queue.length = 0
  clearWatchdog()
  speaking = false
  currentUtterance = null
  try { window.speechSynthesis.cancel() } catch { /* browser-specific */ }
}
