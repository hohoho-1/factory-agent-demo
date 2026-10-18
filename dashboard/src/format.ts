export function formatTime(iso: string | number): string {
  return new Date(iso).toLocaleTimeString('ko-KR', { hour12: false })
}

export function formatValue(v: number): string {
  return Number.isInteger(v) ? String(v) : v.toFixed(Math.abs(v) >= 100 ? 1 : 2)
}

/** 경과 시간: 45초 / 3분 12초 / 1시간 5분 */
export function formatDuration(ms: number): string {
  const s = Math.max(0, Math.floor(ms / 1000))
  if (s < 60) return `${s}초`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}분 ${s % 60}초`
  return `${Math.floor(m / 60)}시간 ${m % 60}분`
}
