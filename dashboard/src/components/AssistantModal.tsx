import { useEffect, useState, type FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import { postJson, type AssistantTask } from '../api'
import { formatDuration, formatTime } from '../format'

interface Props {
  tasks: AssistantTask[]
  now: number
  selectedId: number | null
  onSelect: (id: number) => void
  onCreated: (task: AssistantTask) => void
  onClose: () => void
}

const EXAMPLES = [
  '배합기 진동 원인이 주로 뭐였어?',
  '오늘 아직 처리 안 된 지시서가 있어?',
  '원료 탱크 온도가 오르면 먼저 뭘 확인해야 해?',
]
const TYPE_LABEL: Record<AssistantTask['type'], string> = { QUESTION: '질문', MANUAL_PROPOSAL: '매뉴얼 개선 제안' }
const GENERATOR_LABEL: Record<string, string> = { template: '템플릿', llm: 'Claude (LLM)' }
/** 이 시간이 지나도 작성 중이면 에이전트가 꺼져 있을 가능성이 크다 */
const STALE_MS = 90_000

function taskLabel(t: AssistantTask): string {
  if (t.type === 'QUESTION') return t.question ?? ''
  return t.title ?? `${t.equipmentId} ${t.metric} 매뉴얼 개선 제안`
}

/**
 * AI 작업 창: 자연어 질의와 매뉴얼 개선 제안 결과를 함께 보여 준다.
 * 질문하면 에이전트가 최근 7일 알람·조치 기록과 매뉴얼을 근거로 답한다 (SSE 로 갱신).
 */
export function AssistantModal({ tasks, now, selectedId, onSelect, onCreated, onClose }: Props) {
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const selected = tasks.find((t) => t.id === selectedId) ?? tasks[0] ?? null

  const ask = async (e?: FormEvent) => {
    e?.preventDefault()
    const q = question.trim()
    if (!q) return
    setBusy(true)
    setError(null)
    try {
      const task = await postJson<AssistantTask>('/api/assistant/questions', { question: q })
      onCreated(task)
      onSelect(task.id)
      setQuestion('')
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusy(false)
    }
  }

  const body = selected?.body?.replace(/^# .*\n/, '') ?? ''

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="as-title" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <div>
            <div className="modal__badges muted">{selected ? TYPE_LABEL[selected.type] : 'AI 질의'}</div>
            <h2 id="as-title">{selected ? taskLabel(selected) : 'AI에게 질문'}</h2>
          </div>
          <button className="icon-button" onClick={onClose} aria-label="닫기">
            ✕
          </button>
        </header>
        <div className="modal__body">
          <form className="assistant__ask" onSubmit={ask}>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && (e.ctrlKey || e.metaKey) && void ask()}
              placeholder="최근 7일 알람·조치 기록과 설비 매뉴얼을 근거로 답합니다 (Ctrl+Enter 로 보내기)"
              rows={2}
              maxLength={500}
              aria-label="질문"
            />
            <button className="button" type="submit" disabled={busy || !question.trim()}>
              질문하기
            </button>
          </form>
          <div className="assistant__examples">
            {EXAMPLES.map((ex) => (
              <button key={ex} type="button" className="cause-option" onClick={() => setQuestion(ex)}>
                {ex}
              </button>
            ))}
          </div>
          {error && <p className="action__error">요청하지 못했습니다: {error}</p>}

          {tasks.length > 0 && (
            <ul className="handover__list">
              {tasks.map((t) => (
                <li key={t.id}>
                  <button
                    type="button"
                    className={`handover__item${selected?.id === t.id ? ' handover__item--on' : ''}`}
                    onClick={() => onSelect(t.id)}
                  >
                    <span className="assistant__item-label">
                      <span className="chip">{TYPE_LABEL[t.type]}</span> {taskLabel(t)}
                    </span>
                    <span className="muted">
                      {t.status === 'PENDING' ? '작성 중…' : (GENERATOR_LABEL[t.generator ?? ''] ?? t.generator)} ·{' '}
                      {formatTime(t.createdAt).slice(0, 5)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}

          {selected?.status === 'PENDING' && (
            <p className="empty muted pulse">
              에이전트가 기록과 매뉴얼을 찾아 작성하고 있습니다 ({formatDuration(now - Date.parse(selected.createdAt))}).
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
