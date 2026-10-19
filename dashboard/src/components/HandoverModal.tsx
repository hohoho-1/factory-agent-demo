import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { postJson, type HandoverReport } from '../api'
import { formatDuration, formatTime } from '../format'

interface Props {
  reports: HandoverReport[]
  now: number
  onCreated: (report: HandoverReport) => void
  onClose: () => void
}

const HOURS = [1, 8, 24]
const GENERATOR_LABEL: Record<string, string> = { template: '템플릿', llm: 'Claude (LLM)' }
/** 이 시간이 지나도 작성 중이면 에이전트가 꺼져 있을 가능성이 크다 */
const STALE_MS = 90_000

function windowLabel(r: HandoverReport): string {
  const d = new Date(r.windowFrom)
  const day = `${d.getMonth() + 1}/${d.getDate()}`
  return `${day} ${formatTime(r.windowFrom).slice(0, 5)} ~ ${formatTime(r.windowTo).slice(0, 5)}`
}

/**
 * 교대 인수인계 리포트. 요청하면 에이전트가 해당 시간대의 알람·조치를 요약해 채운다 (SSE 로 갱신).
 * 집계 숫자는 에이전트 코드가 세고, 문장은 Claude 가 알람·지시서 번호를 근거로 쓴다.
 */
export function HandoverModal({ reports, now, onCreated, onClose }: Props) {
  const [hours, setHours] = useState(8)
  const [selectedId, setSelectedId] = useState<number | null>(reports[0]?.id ?? null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const selected = reports.find((r) => r.id === selectedId) ?? reports[0] ?? null

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const report = await postJson<HandoverReport>('/api/handover-reports', { hours })
      onCreated(report)
      setSelectedId(report.id)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const body = selected?.body?.replace(/^# .*\n/, '') ?? ''

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="ho-title" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <div>
            <div className="modal__badges muted">교대 인수인계</div>
            <h2 id="ho-title">{selected?.title ?? '인수인계 리포트'}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </header>
        <div className="modal__body">
          <div className="handover__controls">
            <span className="muted">최근</span>
            {HOURS.map((h) => (
              <button
                key={h}
                type="button"
                className={`cause-option${hours === h ? ' cause-option--on' : ''}`}
                aria-pressed={hours === h}
                onClick={() => setHours(h)}
              >
                {h}시간
              </button>
            ))}
            <button className="button handover__create" onClick={create} disabled={busy}>
              리포트 작성
            </button>
          </div>
          {error && <p className="action__error">요청하지 못했습니다: {error}</p>}

          {reports.length > 0 && (
            <ul className="handover__list">
              {reports.map((r) => (
                <li key={r.id}>
                  <button
                    type="button"
                    className={`handover__item${selected?.id === r.id ? ' handover__item--on' : ''}`}
                    onClick={() => setSelectedId(r.id)}
                  >
                    <span>{windowLabel(r)}</span>
                    <span className="muted">
                      {r.status === 'PENDING' ? '작성 중…' : (GENERATOR_LABEL[r.generator ?? ''] ?? r.generator)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {!selected && <p className="empty muted">아직 리포트가 없습니다. 시간대를 고르고 리포트 작성을 누르세요.</p>}
          {selected?.status === 'PENDING' && (
            <p className="empty muted pulse">
              에이전트가 {windowLabel(selected)} 알람·조치를 정리하고 있습니다 ({formatDuration(now - Date.parse(selected.createdAt))}
              ).
              {now - Date.parse(selected.createdAt) > STALE_MS && ' 응답이 없으면 AI 에이전트 창이 켜져 있는지 확인하세요.'}
            </p>
          )}
          {selected?.status === 'DONE' && (
            <div className="markdown">
              <ReactMarkdown>{body}</ReactMarkdown>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
