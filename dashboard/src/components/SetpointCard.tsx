import { useState } from 'react'
import { postJson, type SetpointChange, type SetpointStatus } from '../api'
import { displayUnit } from '../equipment'
import { formatTime, formatValue } from '../format'
import { loadWorker, saveWorker } from './WorkOrderAction'

export const SETPOINT_STATUS_LABEL: Record<SetpointStatus, string> = {
  PROPOSED: '승인 대기',
  REJECTED: '거절됨',
  SENT: '설비 반영 중…',
  APPLIED: 'PLC 반영됨',
  INTERLOCKED: 'PLC 인터록 거부',
  FAILED: '실패',
}

/** 값 + 단위 (예: 51 rpm, 40°C) */
export function withUnit(v: number | null | undefined, unit: string | null): string {
  if (v === null || v === undefined || Number.isNaN(v)) return '—'
  const u = displayUnit(unit)
  return u.startsWith('°') ? `${formatValue(v)}${u}` : `${formatValue(v)} ${u}`
}

interface Props {
  change: SetpointChange
  onUpdated: (change: SetpointChange) => void
}

/**
 * AI 가 지시서와 함께 낸 권장 설정값 변경. 자율 수준은 '승인 후 실행':
 * 작업자가 승인해야 명령이 내려가고, 백엔드가 운전 범위를 다시 검사하며, PLC 인터록이 마지막으로 막을 수 있다.
 */
export function SetpointCard({ change, onUpdated }: Props) {
  const [worker, setWorker] = useState('')
  const [lastWorker] = useState(loadWorker)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const decide = async (kind: 'approve' | 'reject') => {
    let note: string | null = null
    if (kind === 'reject') {
      note = window.prompt('거절 사유 (선택)', '')
      if (note === null) return
    }
    setBusy(true)
    setError(null)
    try {
      const updated = await postJson<SetpointChange>(`/api/setpoint-changes/${change.id}/${kind}`, { worker, note })
      if (worker.trim()) saveWorker(worker.trim())
      onUpdated(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const before = change.valueBefore ?? change.currentValue
  return (
    <section className={`setpoint setpoint--${change.status.toLowerCase()}`}>
      <header className="setpoint__head">
        <h2>권장 설정값 변경</h2>
        <span className={`chip setpoint-chip setpoint-chip--${change.status.toLowerCase()}`}>
          {SETPOINT_STATUS_LABEL[change.status]}
        </span>
      </header>
      <div className="setpoint__change">
        <span className="setpoint__tag">
          {change.equipmentId} · {change.label ?? change.tag}
        </span>
        <span className="setpoint__values">
          {withUnit(before, change.unit)} <span aria-hidden>→</span>{' '}
          <b>{withUnit(change.proposedValue, change.unit)}</b>
        </span>
      </div>
      {change.reason && <p className="setpoint__reason">{change.reason}</p>}
      {change.sources && <p className="muted setpoint__meta">근거: {change.sources}</p>}

      {change.status === 'PROPOSED' && (
        <>
          <p className="muted setpoint__meta">
            승인하면 엣지 게이트웨이가 PLC 설정값 태그에 씁니다. 운전 범위는 승인 시점에 다시 검사하고, 위험 조건이면
            PLC 인터록이 거부합니다.
          </p>
          <div className="setpoint__decide">
            <input
              value={worker}
              onChange={(e) => setWorker(e.target.value)}
              placeholder="승인자 이름 (비우면 '현장 작업자')"
              aria-label="승인자 이름"
            />
            {lastWorker && worker.trim() !== lastWorker && (
              <button type="button" className="link-button" onClick={() => setWorker(lastWorker)}>
                {lastWorker}(으)로 입력
              </button>
            )}
            <button className="button button--ghost" onClick={() => decide('reject')} disabled={busy}>
              거절
            </button>
            <button className="button" onClick={() => decide('approve')} disabled={busy}>
              승인 후 실행
            </button>
          </div>
        </>
      )}

      {change.status !== 'PROPOSED' && (
        <ul className="setpoint__trail muted">
          <li>
            {formatTime(change.createdAt)} 제안 · {change.origin === 'AI' ? `AI (${change.generator ?? '-'})` : '외부 명령'}
          </li>
          {change.decidedAt && (
            <li>
              {formatTime(change.decidedAt)} {change.status === 'REJECTED' ? '거절' : '승인'} · {change.decidedBy}
              {change.decisionNote && ` — ${change.decisionNote}`}
            </li>
          )}
          {change.completedAt && change.status !== 'REJECTED' && (
            <li className={`setpoint__result setpoint__result--${change.status.toLowerCase()}`}>
              {formatTime(change.completedAt)} {SETPOINT_STATUS_LABEL[change.status]}
              {change.status === 'APPLIED' &&
                ` · ${withUnit(change.valueBefore, change.unit)} → ${withUnit(change.valueAfter, change.unit)}`}
              {change.status !== 'APPLIED' && change.resultMessage && ` · ${change.resultMessage}`}
              {change.resultCode && change.status === 'INTERLOCKED' && ` (${change.resultCode})`}
            </li>
          )}
        </ul>
      )}
      {error && <p className="action__error">처리하지 못했습니다: {error}</p>}
    </section>
  )
}
