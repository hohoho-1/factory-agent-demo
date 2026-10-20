import { useCallback, useEffect, useState } from 'react'
import { getJson, type BatchRecord, type BatchRun } from '../api'
import { EQUIPMENT_BY_ID, METRIC_LABEL, PHASE_LABEL } from '../equipment'
import { formatDuration, formatTime, formatValue } from '../format'
import { StatusBadge } from './StatusBadge'
import { SETPOINT_STATUS_LABEL, withUnit } from './SetpointCard'

interface Props {
  /** 값이 바뀌면 목록을 다시 읽는다 (배치 단계가 바뀔 때) */
  refreshKey: string
}

const VERDICT_CLASS: Record<BatchRecord['verdict']['level'], string> = {
  OK: 'verdict--ok',
  REVIEW: 'verdict--review',
  HOLD: 'verdict--hold',
  RUNNING: 'verdict--running',
}

function duration(run: BatchRun): string {
  if (!run.endedAt) return '진행 중'
  return formatDuration(Date.parse(run.endedAt) - Date.parse(run.startedAt))
}

/** 배치 기록 한 장: 단계별 소요 시간·온도 범위, 배치 중 알람과 조치, 설정값 변경, 판정 요약 */
function BatchRecordModal({ id, onClose }: { id: number; onClose: () => void }) {
  const [record, setRecord] = useState<BatchRecord | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    getJson<BatchRecord>(`/api/batches/${id}/record`)
      .then(setRecord)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
  }, [id])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onClose])

  const run = record?.batch
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="batch-title" onClick={(e) => e.stopPropagation()}>
        <header className="modal__head">
          <div>
            <div className="modal__badges">
              <span className="muted">전자 배치 기록 (간이)</span>
            </div>
            <h2 id="batch-title">
              {run ? `배치 ${run.batchId} · ${run.recipe ?? '-'}` : '배치 기록'}
            </h2>
          </div>
          <div className="modal__actions">
            <button className="icon-button" onClick={onClose} aria-label="닫기">
              ✕
            </button>
          </div>
        </header>
        <div className="modal__body">
          {error && <p className="action__error">불러오지 못했습니다: {error}</p>}
          {!record && !error && <p className="muted">불러오는 중…</p>}
          {record && run && (
            <>
              <div className={`verdict ${VERDICT_CLASS[record.verdict.level]}`}>
                <b>{record.verdict.text}</b>
                <span className="muted">
                  {EQUIPMENT_BY_ID[run.equipmentId]?.name ?? run.equipmentId} · {formatTime(run.startedAt)} 시작 ·{' '}
                  {duration(run)} · 알람 {record.verdict.alarmCount}건 (위험 {record.verdict.criticalCount})
                </span>
              </div>

              <h3 className="record__title">단계</h3>
              <div className="table-wrap">
                <table className="table">
                  <thead>
                    <tr>
                      <th>단계</th>
                      <th>시작</th>
                      <th className="num">소요</th>
                      <th>측정 범위</th>
                    </tr>
                  </thead>
                  <tbody>
                    {run.phases.map((p) => (
                      <tr key={`${p.phase}-${p.startedAt}`}>
                        <td>
                          <b>{PHASE_LABEL[p.phase] ?? p.phase}</b>
                        </td>
                        <td>{formatTime(p.startedAt)}</td>
                        <td className="num">{p.seconds != null ? `${p.seconds}초` : '진행 중'}</td>
                        <td>
                          {Object.entries(p.metrics ?? {})
                            .filter(([m]) => m === 'temperature' || m === 'vibration')
                            .map(([m, [lo, hi]]) => `${METRIC_LABEL[m] ?? m} ${formatValue(lo)}~${formatValue(hi)}`)
                            .join(' · ') || '-'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>

              <h3 className="record__title">배치 중 이상과 조치</h3>
              {record.alarms.length === 0 ? (
                <p className="muted">배치 중 발생한 알람이 없습니다.</p>
              ) : (
                <ul className="record__list">
                  {record.alarms.map((a) => {
                    const orders = record.workOrders.filter((w) => w.alarmId === a.id)
                    const done = orders.find((w) => w.status === 'COMPLETED')
                    return (
                      <li key={a.id}>
                        <StatusBadge status={a.severity} compact /> {formatTime(a.raisedAt)}{' '}
                        {EQUIPMENT_BY_ID[a.equipmentId]?.name ?? a.equipmentId} {METRIC_LABEL[a.metric] ?? a.metric}
                        {a.batchPhase && <span className="muted"> ({PHASE_LABEL[a.batchPhase] ?? a.batchPhase} 단계)</span>}
                        {' · '}
                        {done ? (
                          <span>
                            조치 완료 WO-{done.id}: {done.rootCause ?? '원인 미기록'} / {done.actionTaken} ({done.worker})
                          </span>
                        ) : orders.length ? (
                          <b>조치 미완료 (WO-{orders.map((w) => w.id).join(', WO-')})</b>
                        ) : (
                          <b>지시서 없음</b>
                        )}
                      </li>
                    )
                  })}
                </ul>
              )}

              <h3 className="record__title">설정값 변경과 승인</h3>
              {record.setpointChanges.length === 0 ? (
                <p className="muted">배치 중 설정값 변경이 없습니다.</p>
              ) : (
                <ul className="record__list">
                  {record.setpointChanges.map((c) => (
                    <li key={c.id}>
                      {formatTime(c.createdAt)} {c.label ?? c.tag}{' '}
                      {withUnit(c.valueBefore ?? c.currentValue, c.unit)} → {withUnit(c.proposedValue, c.unit)} ·{' '}
                      {SETPOINT_STATUS_LABEL[c.status]}
                      {c.decidedBy && ` · ${c.origin === 'AI' ? '승인' : '요청'} ${c.decidedBy}`}
                    </li>
                  ))}
                </ul>
              )}
              <p className="muted record__note">
                출하 판정은 품질팀이 합니다. 이 기록은 AI 판단과 작업자 승인 · 조치를 배치 단위로 묶어 남긴 것입니다.
              </p>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

/** 최근 배치 목록. 가상 PLC 모드에서 배치를 돌리면 쌓인다 */
export function BatchRecords({ refreshKey }: Props) {
  const [runs, setRuns] = useState<BatchRun[]>([])
  const [openId, setOpenId] = useState<number | null>(null)
  const close = useCallback(() => setOpenId(null), [])

  useEffect(() => {
    getJson<BatchRun[]>('/api/batches')
      .then(setRuns)
      .catch(() => setRuns([]))
  }, [refreshKey])

  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>배치 기록</h2>
        <span className="muted panel__note">단계 · 이상 · 조치 · 승인을 배치 단위로 (간이 EBR)</span>
      </header>
      {runs.length === 0 ? (
        <p className="empty muted">
          아직 배치가 없습니다. 가상 PLC 모드에서 <code>inject.ps1 batch_start</code> 로 배치를 시작하면 여기에 쌓입니다.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>배치</th>
                <th>레시피</th>
                <th>시작</th>
                <th className="num">소요</th>
                <th>단계</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.id}>
                  <td>
                    <b>{r.batchId}</b>
                  </td>
                  <td>{r.recipe ?? '-'}</td>
                  <td>{formatTime(r.startedAt)}</td>
                  <td className="num">{duration(r)}</td>
                  <td>
                    {r.status === 'RUNNING'
                      ? `${PHASE_LABEL[r.phases[r.phases.length - 1]?.phase] ?? '-'} 진행 중`
                      : `완료 (${r.phases.length}단계)`}
                  </td>
                  <td>
                    <button className="link-button" onClick={() => setOpenId(r.id)}>
                      기록 보기
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {openId != null && <BatchRecordModal id={openId} onClose={close} />}
    </section>
  )
}
