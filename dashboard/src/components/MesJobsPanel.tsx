import { useCallback, useEffect, useState } from 'react'
import { getJson, type BatchState } from '../api'
import { formatTime } from '../format'
import { loadWorker, saveWorker } from './WorkOrderAction'

/** MES 생산 지시 (ERP 생산 오더를 현장에서 받은 것). 배치 번호는 MES 가 정한다: {ERP 오더번호}-{순번} */
interface JobBatch {
  id: number
  seq: number
  batchId: string
  qty: number
  status: 'REQUESTED' | 'RUNNING' | 'COMPLETED' | 'FAILED'
  message: string | null
  requestedBy: string | null
  requestedAt: string
  completedAt: string | null
  reportedAt: string | null
  /** 계획 순서를 건너뛰고 작업자 확인 후 시작한 배치 */
  outOfOrder: boolean
}

interface ProductionJob {
  id: number
  erpOrderNo: string
  itemCode: string
  itemName: string
  qty: number
  batchesTotal: number
  batchesDone: number
  producedQty: number
  status: 'RECEIVED' | 'IN_PROGRESS' | 'COMPLETED'
  /** ERP 생산 계획의 시작일. 목록은 이 순서로 온다 */
  plannedStart: string | null
  createdAt: string
  batches: JobBatch[]
}

const BATCH_LABEL: Record<JobBatch['status'], string> = {
  REQUESTED: 'PLC 요청 중',
  RUNNING: '진행 중',
  COMPLETED: '완료',
  FAILED: 'PLC 거부',
}

interface Props {
  /** 배합기 현재 배치 (다른 배치가 돌고 있으면 시작 버튼을 막는다) */
  mixerBatch: BatchState | undefined
}

/**
 * 현장 관제 화면의 생산 지시 목록. ERP 에서 '현장 지시'한 오더가 여기 들어오고,
 * 작업자가 '배치 시작'을 누르면 배치 번호 · 레시피가 PLC 로 내려간다 (OPC UA, 인터록 검사).
 * 배치가 끝나면 MES 가 ERP 에 실적을 올린다. 지시가 없으면 패널을 그리지 않는다.
 */
export function MesJobsPanel({ mixerBatch }: Props) {
  const [jobs, setJobs] = useState<ProductionJob[]>([])
  const [busy, setBusy] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setJobs(await getJson<ProductionJob[]>('/api/mes/jobs'))
    } catch {
      /* 백엔드가 잠깐 끊겨도 다음 주기에 다시 읽는다 */
    }
  }, [])

  useEffect(() => {
    void load()
    const id = window.setInterval(() => void load(), 3000)
    return () => window.clearInterval(id)
  }, [load])

  /**
   * 배치 시작. 계획 순서상 앞선 지시가 남아 있으면 MES 가 409(OUT_OF_ORDER)로 멈추고,
   * 작업자가 확인하면 '순서 변경'으로 기록하고 시작한다.
   */
  const start = async (job: ProductionJob) => {
    setBusy(job.id)
    setError(null)
    const worker = loadWorker() ?? ''
    const send = (confirmOutOfOrder: boolean) =>
      fetch(`/api/mes/jobs/${job.id}/start-batch`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ worker, confirmOutOfOrder }),
      })
    try {
      let res = await send(false)
      if (res.status === 409) {
        const body = (await res.json().catch(() => ({}))) as { code?: string; message?: string }
        if (body.code !== 'OUT_OF_ORDER') throw new Error(body.message ?? 'HTTP 409')
        if (!window.confirm(`${body.message}
그래도 ${job.erpOrderNo}을(를) 먼저 시작할까요? 순서 변경으로 기록됩니다.`)) return
        res = await send(true)
      }
      if (!res.ok) {
        const body = (await res.json().catch(() => ({}))) as { message?: string }
        throw new Error(body.message ?? `HTTP ${res.status}`)
      }
      if (worker) saveWorker(worker)
      await load()
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(null)
    }
  }

  const open = jobs.filter((j) => j.status !== 'COMPLETED' || Date.now() - Date.parse(j.createdAt) < 30 * 60_000)
  if (open.length === 0) return null
  const mixerBusy = mixerBatch != null && mixerBatch.phase !== 'IDLE' && mixerBatch.batchId != null
  // 목록은 계획 순서(끝나지 않은 지시 먼저, 계획 시작일 순)로 온다. 맨 앞의 미완료 지시가 다음 순서
  const nextId = open.find((j) => j.status !== 'COMPLETED')?.id

  return (
    <section className="card panel mes">
      <header className="panel__head">
        <h2>생산 지시 (ERP → MES)</h2>
        <span className="count">{open.filter((j) => j.status !== 'COMPLETED').length}</span>
      </header>
      <ul className="mes__list">
        {open.map((job, i) => {
          const last = job.batches[job.batches.length - 1]
          const active = job.batches.some((b) => b.status === 'REQUESTED' || b.status === 'RUNNING')
          const done = job.status === 'COMPLETED'
          const pct = Math.round((job.batchesDone / job.batchesTotal) * 100)
          return (
            <li key={job.id} className="mes__job">
              <div className="mes__top">
                <span className="mes__order">{i + 1}</span>
                <strong>{job.erpOrderNo}</strong>
                {job.id === nextId && <span className="chip chip--open mes__next">다음 순서</span>}
                <span>{job.itemName}</span>
                <span className="muted">
                  {job.qty.toLocaleString('ko-KR')}파우치
                  {job.plannedStart && ` · ${job.plannedStart.slice(5).replace('-', '/')} 시작 계획`}
                </span>
              </div>
              <div className="mes__progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${pct}%` }} />
              </div>
              <div className="mes__meta">
                배치 {job.batchesDone}/{job.batchesTotal} · 생산 {job.producedQty.toLocaleString('ko-KR')}파우치
                {last && (
                  <span className={`mes__batch mes__batch--${last.status.toLowerCase()}`}>
                    {last.batchId} {BATCH_LABEL[last.status]}
                    {last.outOfOrder && ' · 순서 변경'}
                    {last.status === 'COMPLETED' && (last.reportedAt ? ' · ERP 보고됨' : ' · ERP 보고 대기')}
                    {last.status === 'FAILED' && last.message && ` — ${last.message}`}
                  </span>
                )}
              </div>
              {!done && (
                <div className="mes__actions">
                  <button
                    className="button"
                    disabled={busy === job.id || active || mixerBusy}
                    onClick={() => void start(job)}
                    title={mixerBusy ? `배합기에서 ${mixerBatch?.batchId} 진행 중` : undefined}
                  >
                    {job.batchesDone + 1}번째 배치 시작
                  </button>
                  {mixerBusy && !active && <span className="muted">배합기 사용 중 ({mixerBatch?.batchId})</span>}
                </div>
              )}
              {done && <div className="muted">완료 · {formatTime(job.batches[job.batches.length - 1]?.completedAt ?? job.createdAt)}</div>}
            </li>
          )
        })}
      </ul>
      {error && <p className="action__error">배치를 시작하지 못했습니다: {error}</p>}
    </section>
  )
}
