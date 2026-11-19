import { useEffect, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { getJson } from '../api'

/** SuperAgent 가 부른 도구 1건 (실행 기록) */
interface Step {
  tool: string
  group: 'ERP' | 'MES' | '품질' | '설비' | string
  input: Record<string, unknown>
  ms: number
  ok: boolean
  summary: string
}

interface Answer {
  question: string
  answer: string
  steps: Step[]
  turns: number
  stopped: string | null
  model: string
  seconds: number
  at?: string
}

const TOOL_LABEL: Record<string, string> = {
  erp_sales_orders: '판매 주문',
  erp_production_orders: '생산 오더',
  erp_inventory: '재고',
  erp_purchase_orders: '구매 발주',
  erp_standard_cost: '표준 원가',
  mes_jobs: '생산 지시 · 배치',
  mes_line_state: '배합기 상태',
  mes_batch_record: '배치 기록',
  quality_assessments: '품질 판정',
  equipment_alarms: '알람',
  equipment_work_orders: 'AI 조치 지시서',
  equipment_action_stats: '조치 이력 통계',
}

const EXAMPLES = [
  '지금 납기에 위험한 주문이 있어? 이유와 우리가 해야 할 일은?',
  '품질 홀드 때문에 출하가 막힌 주문이 있어?',
  '배합기에서 다음에 무엇을 해야 해? 세정이 필요한지도 알려줘',
  '캡슐 세제 A 원가에서 가장 큰 자재는 뭐고, 재고는 충분해?',
]

/**
 * 경영 화면의 SuperAgent (IR 의 NEXA Command 역할). 질문 하나에 Claude 가 ERP · MES · 품질 · 설비 도구를 스스로 골라
 * 여러 번 조회하고 답한다. 읽기 전용이라 실행은 사람이 한다. 어떤 도구를 어떤 순서로 불렀는지 실행 기록을 함께 보여 준다.
 */
export function SuperAgentPanel() {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [busy, setBusy] = useState(false)
  const [elapsed, setElapsed] = useState(0)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getJson<Answer[]>('/command/history')
      .then((h) => h.length && setAnswer(h[0]))
      .catch(() => undefined)
  }, [])

  useEffect(() => {
    if (!busy) return
    const started = Date.now()
    const id = window.setInterval(() => setElapsed(Math.round((Date.now() - started) / 1000)), 500)
    return () => window.clearInterval(id)
  }, [busy])

  const ask = async (q: string) => {
    const text = q.trim()
    if (text.length < 2) return
    setQuestion(text)
    setBusy(true)
    setElapsed(0)
    setError(null)
    try {
      const res = await fetch('/command/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: text }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error((body as { detail?: string }).detail ?? `HTTP ${res.status}`)
      setAnswer(body as Answer)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="card panel superagent">
      <header className="panel__head">
        <h2>SuperAgent</h2>
        <span className="muted erp__hint">ERP · MES · 품질 · 설비를 Claude가 골라 조회해 답합니다 · 읽기 전용</span>
      </header>
      <form
        className="superagent__ask"
        onSubmit={(e) => {
          e.preventDefault()
          void ask(question)
        }}
      >
        <input
          id="superagent-question"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="예: 이번 품질 홀드로 납기에 영향이 있어?"
          aria-label="SuperAgent 에게 질문"
          maxLength={500}
          disabled={busy}
        />
        <button className="button" disabled={busy || question.trim().length < 2}>
          {busy ? `조회 중… ${elapsed}초` : '질문'}
        </button>
      </form>
      <div className="superagent__examples">
        {EXAMPLES.map((q) => (
          <button key={q} type="button" className="link-button" disabled={busy} onClick={() => void ask(q)}>
            {q}
          </button>
        ))}
      </div>
      {error && <p className="action__error">답하지 못했습니다: {error}</p>}
      {answer && !busy && (
        <div className="superagent__result">
          <p className="muted superagent__q">Q. {answer.question}</p>
          <div className="markdown superagent__answer">
            <ReactMarkdown>{answer.answer}</ReactMarkdown>
          </div>
          <details className="superagent__trace" open>
            <summary>
              실행 기록 · 도구 {answer.steps.length}번 · {answer.turns}왕복 · {answer.seconds}초 · {answer.model}
              {answer.stopped && ` · ${answer.stopped}에서 멈춤`}
            </summary>
            <ol>
              {answer.steps.map((s, i) => (
                <li key={i} className={s.ok ? undefined : 'superagent__step--error'}>
                  <span className={`superagent__group superagent__group--${s.group}`}>{s.group}</span>
                  <b>{TOOL_LABEL[s.tool] ?? s.tool}</b>
                  {Object.values(s.input).some((v) => v != null && v !== '') && (
                    <span className="muted">
                      {' '}
                      ({Object.entries(s.input)
                        .filter(([, v]) => v != null && v !== '')
                        .map(([k, v]) => `${k}=${String(v)}`)
                        .join(', ')}
                      )
                    </span>
                  )}
                  <span className="muted"> · {s.ms}ms{s.ok ? '' : ' · 조회 실패'}</span>
                </li>
              ))}
            </ol>
          </details>
        </div>
      )}
    </section>
  )
}
