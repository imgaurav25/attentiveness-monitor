// Small helpers around getUserMedia and frame capture.

export async function openCamera({ audio = false } = {}) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new Error('Camera API is unavailable in this browser/context.')
  }

  let lastError
  for (let attempt = 0; attempt < 3; attempt += 1) {
    try {
      return await navigator.mediaDevices.getUserMedia({
        video: { width: { ideal: 640, max: 1280 }, height: { ideal: 480, max: 720 }, facingMode: 'user' },
        audio,
      })
    } catch (err) {
      lastError = err
      await new Promise((resolve) => setTimeout(resolve, 500 * (attempt + 1)))
    }
  }
  throw lastError || new Error('Could not open camera')
}

export function stopStream(stream) {
  if (stream) stream.getTracks().forEach((t) => t.stop())
}

export function captureFrameBase64(videoEl, quality = 0.7) {
  if (!videoEl || !videoEl.videoWidth) return null
  const canvas = document.createElement('canvas')
  canvas.width = videoEl.videoWidth
  canvas.height = videoEl.videoHeight
  const ctx = canvas.getContext('2d')
  ctx.drawImage(videoEl, 0, 0, canvas.width, canvas.height)
  return canvas.toDataURL('image/jpeg', quality).split(',')[1]
}
