import type { SetpointChange, WorkOrder, WorkOrderStatus } from '../api'
import { formatTime } from '../format'
import { SETPOINT_STATUS_LABEL, withUnit } from './SetpointCard'
import { StatusBadge } from './StatusBadge'

function SetpointLine({ change }: { change: SetpointChange }) {
  return (
    <div className="wo__setpoint">
      <span className={`chip setpoint-chip setpoint-chip--${change.status.toLowerCase()}`}>
        {SETPOINT_STATUS_LABEL[change.status]}
      </span>
      <span>
        {change.label ?? change.tag} {withUnit(change.valueBefore ?? change.currentValue, change.unit)} →{' '}
        {withUnit(change.proposedValue, change.unit)}
      </span>
    </div>
  )
}
import { OUTCOME_LABEL } from './WorkOrderAction'

interface Props {
  workOrders: WorkOrder[]
  setpointChanges: SetpointChange[]
  onOpen: (wo: WorkOrder) => void
}

const GENERATOR_LABEL: Record<string, string> = { template: '매뉴얼 템플릿', llm: 'Claude (LLM)' }

const STATUS_LABEL: Record<WorkOrderStatus, string> = {
  OPEN: '미확인',
  ACKNOWLEDGED: '조치 중',
  COMPLETED: '완료',
  SUPERSEDED: '함께 처리',
}

function statusText(wo: WorkOrder): string {
  if (wo.status === 'COMPLETED' && wo.outcome) return `완료 · ${OUTCOME_LABEL[wo.outcome]}`
  return STATUS_LABEL[wo.status]
}

export function WorkOrderPanel({ workOrders, setpointChanges, onOpen }: Props) {
  // 지시서마다 가장 최근 설정값 제안 (목록에 '승인 대기' 등을 표시)
  const proposalOf = new Map<number, SetpointChange>()
  for (const c of setpointChanges) {
    if (c.workOrderId !== null && !proposalOf.has(c.workOrderId)) proposalOf.set(c.workOrderId, c)
  }

  return (
    <section className="card panel panel--grow">
      <header className="panel__head">
        <h2>AI 조치 지시서</h2>
        <span className="count">{workOrders.length}</span>
      </header>
      {workOrders.length === 0 ? (
        <p className="empty muted">아직 작성된 지시서가 없습니다. 알람이 발생하면 에이전트가 매뉴얼을 검색해 작성합니다.</p>
      ) : (
        <ul className="wo-list">
          {workOrders.map((wo) => (
            <li key={wo.id}>
              <button className="wo" onClick={() => onOpen(wo)}>
                <div className="wo__top">
                  <StatusBadge status={wo.severity} compact />
                  <span className="wo__title">{wo.title.replace(/^\[\w+\]\s*/, '')}</span>
                  <span className={`chip chip--${wo.status.toLowerCase()}`}>{statusText(wo)}</span>
                </div>
                {wo.summary && <p className="wo__summary">{wo.summary}</p>}
                {proposalOf.has(wo.id) && <SetpointLine change={proposalOf.get(wo.id)!} />}
                <div className="wo__meta muted">
                  WO-{wo.id} · 알람 #{wo.alarmId} · {formatTime(wo.createdAt)} ·{' '}
                  {GENERATOR_LABEL[wo.generator] ?? wo.generator}
                  {wo.references[0] && <> · 근거 {wo.references[0].manualId}</>}
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
