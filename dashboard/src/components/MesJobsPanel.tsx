import { useCallback, useEffect, useState } from 'react'
import { getJson, postJson, type BatchState } from '../api'
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

  const start = async (job: ProductionJob) => {
    setBusy(job.id)
    setError(null)
    const worker = loadWorker() ?? ''
    try {
      await postJson(`/api/mes/jobs/${job.id}/start-batch`, { worker })
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

  return (
    <section className="card panel mes">
      <header className="panel__head">
        <h2>생산 지시 (ERP → MES)</h2>
        <span className="count">{open.filter((j) => j.status !== 'COMPLETED').length}</span>
      </header>
      <ul className="mes__list">
        {open.map((job) => {
          const last = job.batches[job.batches.length - 1]
          const active = job.batches.some((b) => b.status === 'REQUESTED' || b.status === 'RUNNING')
          const done = job.status === 'COMPLETED'
          const pct = Math.round((job.batchesDone / job.batchesTotal) * 100)
          return (
            <li key={job.id} className="mes__job">
              <div className="mes__top">
                <strong>{job.erpOrderNo}</strong>
                <span>{job.itemName}</span>
                <span className="muted">{job.qty.toLocaleString('ko-KR')}파우치</span>
              </div>
              <div className="mes__progress" role="progressbar" aria-valuenow={pct} aria-valuemin={0} aria-valuemax={100}>
                <span style={{ width: `${pct}%` }} />
              </div>
              <div className="mes__meta">
                배치 {job.batchesDone}/{job.batchesTotal} · 생산 {job.producedQty.toLocaleString('ko-KR')}파우치
                {last && (
                  <span className={`mes__batch mes__batch--${last.status.toLowerCase()}`}>
                    {last.batchId} {BATCH_LABEL[last.status]}
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
