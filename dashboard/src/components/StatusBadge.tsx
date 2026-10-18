import type { Severity } from '../api'

export type Status = 'NORMAL' | Severity

const LABEL: Record<Status, string> = { NORMAL: '정상', WARNING: '경고', CRITICAL: '위험' }

/** 상태는 색만으로 전달하지 않는다: 모양이 다른 아이콘 + 글자 라벨을 함께 쓴다. */
function Icon({ status }: { status: Status }) {
  if (status === 'CRITICAL') {
    return (
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <rect x="1.5" y="1.5" width="9" height="9" rx="1.5" />
      </svg>
    )
  }
  if (status === 'WARNING') {
    return (
      <svg viewBox="0 0 12 12" aria-hidden="true">
        <path d="M6 1 11 10.5H1Z" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 12 12" aria-hidden="true">
      <circle cx="6" cy="6" r="4.5" />
    </svg>
  )
}

export function StatusBadge({ status, compact = false }: { status: Status; compact?: boolean }) {
  return (
    <span className={`badge badge--${status.toLowerCase()}${compact ? ' badge--compact' : ''}`}>
      <Icon status={status} />
      {LABEL[status]}
    </span>
  )
}

export function worstStatus(statuses: Status[]): Status {
  if (statuses.includes('CRITICAL')) return 'CRITICAL'
  if (statuses.includes('WARNING')) return 'WARNING'
  return 'NORMAL'
}
