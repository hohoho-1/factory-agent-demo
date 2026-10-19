import { useEffect, useState, type FormEvent } from 'react'
import { postJson, type ActionOutcome, type ActionResult, type WorkOrder } from '../api'
import { formatTime } from '../format'

interface Props {
  workOrder: WorkOrder
  onUpdated: (wo: WorkOrder) => void
  /** 저장하지 않은 입력이 있는지 알린다 (모달이 닫기 전에 확인하도록) */
  onDirtyChange: (dirty: boolean) => void
}

/** 모달 머리의 바로가기 버튼이 스크롤해 올 위치 */
export const ACTION_SECTION_ID = 'wo-action'

export const OUTCOME_LABEL: Record<ActionOutcome, string> = {
  RESOLVED: '해결',
  PARTIAL: '부분 해결',
  UNRESOLVED: '미해결',
}

const WORKER_KEY = 'worker'

function loadWorker(): string {
  try {
    return localStorage.getItem(WORKER_KEY) ?? ''
  } catch {
    return ''
  }
}

function saveWorker(worker: string) {
  try {
    localStorage.setItem(WORKER_KEY, worker)
  } catch {
    /* 저장 못 해도 동작에는 문제 없음 */
  }
}

/**
 * 작업자 피드백: 지시서 확인 → 조치 완료·결과 입력.
 * 입력한 원인·조치·결과는 같은 설비·지표에 다음 알람이 나면 AI 지시서의 '과거 유사 조치 이력'에 들어간다.
 */
export function WorkOrderAction({ workOrder, onUpdated, onDirtyChange }: Props) {
  const [worker, setWorker] = useState(loadWorker)
  const [rootCause, setRootCause] = useState('')
  const [actionTaken, setActionTaken] = useState('')
  const [outcome, setOutcome] = useState<ActionOutcome>('RESOLVED')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const closed = workOrder.status === 'COMPLETED' || workOrder.status === 'SUPERSEDED'
  const dirty = !closed && (rootCause.trim() !== '' || actionTaken.trim() !== '')
  useEffect(() => onDirtyChange(dirty), [dirty, onDirtyChange])

  const send = async (path: string, body: unknown) => {
    setBusy(true)
    setError(null)
    try {
      saveWorker(worker.trim())
      onUpdated(await postJson<WorkOrder>(path, body))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const acknowledge = () => send(`/api/work-orders/${workOrder.id}/acknowledge`, { worker })

  const complete = (e: FormEvent) => {
    e.preventDefault()
    const result: ActionResult = { worker, rootCause, actionTaken, outcome }
    void send(`/api/work-orders/${workOrder.id}/complete`, result)
  }

  if (workOrder.status === 'SUPERSEDED') {
    return (
      <section id={ACTION_SECTION_ID} className="action action--superseded">
        <h2>함께 처리됨</h2>
        <p className="muted">
          같은 알람의 WO-{workOrder.supersededBy} 조치가 완료되어 이 지시서도 닫혔습니다
          {workOrder.completedAt && ` (${formatTime(workOrder.completedAt)})`}. 조치 결과는 WO-{workOrder.supersededBy}
          에서 볼 수 있습니다.
        </p>
      </section>
    )
  }

  if (workOrder.status === 'COMPLETED') {
    return (
      <section id={ACTION_SECTION_ID} className="action action--done">
        <h2>조치 결과</h2>
        <dl className="action__result">
          <dt>결과</dt>
          <dd>
            <b>{workOrder.outcome ? OUTCOME_LABEL[workOrder.outcome] : '-'}</b>
          </dd>
          <dt>확인한 원인</dt>
          <dd>{workOrder.rootCause ?? '미확인'}</dd>
          <dt>조치 내용</dt>
          <dd className="action__text">{workOrder.actionTaken}</dd>
          <dt>작업자</dt>
          <dd>
            {workOrder.worker} · {workOrder.completedAt && formatTime(workOrder.completedAt)} 완료
          </dd>
        </dl>
        <p className="muted action__hint">
          이 기록은 같은 설비·지표에 다음 이상이 생기면 AI 지시서의 '과거 유사 조치 이력'에 들어갑니다.
        </p>
      </section>
    )
  }

  return (
    <section id={ACTION_SECTION_ID} className="action">
      <h2>작업자 조치</h2>
      <label className="field">
        <span>작업자</span>
        <input value={worker} onChange={(e) => setWorker(e.target.value)} placeholder="이름 (비우면 '현장 작업자')" />
      </label>

      {workOrder.status === 'OPEN' ? (
        <div className="action__row">
          <span className="muted">지시서를 읽었으면 확인을 누르고 점검을 시작하세요.</span>
          <button className="button" onClick={acknowledge} disabled={busy}>
            지시서 확인
          </button>
        </div>
      ) : (
        <form onSubmit={complete}>
          <p className="muted action__hint">
            {workOrder.worker} · {workOrder.acknowledgedAt && formatTime(workOrder.acknowledgedAt)} 확인. 점검·조치를
            마치면 결과를 남겨 주세요.
          </p>
          <label className="field">
            <span>확인한 원인</span>
            <input
              value={rootCause}
              onChange={(e) => setRootCause(e.target.value)}
              placeholder="예: 모터측 베어링 윤활 부족"
            />
          </label>
          <label className="field">
            <span>조치 내용 *</span>
            <textarea
              value={actionTaken}
              onChange={(e) => setActionTaken(e.target.value)}
              placeholder="예: 그리스 보충, 커플링 볼트 재조임 후 재가동. 진동 2.8mm/s 확인"
              rows={3}
              required
            />
          </label>
          <fieldset className="field field--inline">
            <span>결과</span>
            {(Object.keys(OUTCOME_LABEL) as ActionOutcome[]).map((o) => (
              <label key={o} className="radio">
                <input type="radio" name="outcome" checked={outcome === o} onChange={() => setOutcome(o)} />
                {OUTCOME_LABEL[o]}
              </label>
            ))}
          </fieldset>
          <div className="action__row action__row--end">
            <button className="button" type="submit" disabled={busy || !actionTaken.trim()}>
              조치 완료
            </button>
          </div>
        </form>
      )}
      {error && <p className="action__error">저장하지 못했습니다: {error}</p>}
    </section>
  )
}
