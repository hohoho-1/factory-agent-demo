import { useState } from 'react'
import { postJson, type QualityAssessment, type QualityLevel, type QualityStatus } from '../api'
import { formatTime } from '../format'
import { loadWorker, saveWorker } from './WorkOrderAction'

export const QUALITY_LEVEL_LABEL: Record<QualityLevel, string> = {
  NO_IMPACT: '품질 영향 없음',
  INSPECT: '추가 검사 필요',
  HOLD: '배치 홀드 · 출하 보류 권고',
}

export const QUALITY_STATUS_LABEL: Record<QualityStatus, string> = {
  RECORDED: '기록됨',
  PENDING: '품질팀 승인 대기',
  APPROVED: '품질팀 홀드 승인',
  REJECTED: '품질팀 홀드 거절',
}

interface Props {
  assessment: QualityAssessment
  onUpdated: (q: QualityAssessment) => void
}

/**
 * 품질 에이전트(두 번째 에이전트)의 판정. 배치 진행 중 알람이면 지시서 에이전트 다음에 나온다.
 * 판정은 규칙으로 정하고 이유 설명만 LLM 이 쓴다. HOLD 는 품질팀이 승인해야 확정된다.
 */
export function QualityCard({ assessment: q, onUpdated }: Props) {
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
      const updated = await postJson<QualityAssessment>(`/api/quality-assessments/${q.id}/${kind}`, { worker, note })
      if (worker.trim()) saveWorker(worker.trim())
      onUpdated(updated)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={`quality quality--${q.level.toLowerCase()} quality--${q.status.toLowerCase()}`}>
      <header className="setpoint__head">
        <h2>품질 영향 판정</h2>
        <span className={`chip quality-chip quality-chip--${q.status.toLowerCase()}`}>{QUALITY_STATUS_LABEL[q.status]}</span>
      </header>
      <div className="quality__level">
        <span className={`quality__badge quality__badge--${q.level.toLowerCase()}`}>{QUALITY_LEVEL_LABEL[q.level]}</span>
        <span className="muted">
          배치 {q.batchId}
          {q.batchPhase && ` · ${q.batchPhase}`}
        </span>
      </div>
      <p className="setpoint__meta muted">규칙: {q.basis}</p>
      {q.reason && <p className="setpoint__reason">{q.reason}</p>}
      <p className="setpoint__meta muted">
        품질 에이전트 · 설명 {q.generator === 'llm' ? 'Claude (LLM)' : '템플릿'} · {formatTime(q.createdAt)}
      </p>

      {q.status === 'PENDING' && (
        <div className="setpoint__decide">
          <input
            value={worker}
            onChange={(e) => setWorker(e.target.value)}
            placeholder="품질팀 승인자 (비우면 '품질팀')"
            aria-label="품질팀 승인자 이름"
          />
          {lastWorker && worker.trim() !== lastWorker && (
            <button type="button" className="link-button" onClick={() => setWorker(lastWorker)}>
              {lastWorker}(으)로 입력
            </button>
          )}
          <button className="button button--ghost" onClick={() => decide('reject')} disabled={busy}>
            홀드 거절
          </button>
          <button className="button" onClick={() => decide('approve')} disabled={busy}>
            홀드 승인
          </button>
        </div>
      )}
      {q.decidedAt && (
        <p className="setpoint__meta muted">
          {formatTime(q.decidedAt)} {q.status === 'APPROVED' ? '홀드 승인' : '홀드 거절'} · {q.decidedBy}
          {q.decisionNote && ` — ${q.decisionNote}`}
        </p>
      )}
      {error && <p className="action__error">처리하지 못했습니다: {error}</p>}
    </section>
  )
}
