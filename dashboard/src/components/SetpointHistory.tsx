import type { SetpointChange } from '../api'
import { formatTime } from '../format'
import { SETPOINT_STATUS_LABEL, withUnit } from './SetpointCard'

interface Props {
  changes: SetpointChange[]
  /** AI 제안이면 해당 지시서를 연다 */
  onOpenWorkOrder: (workOrderId: number) => void
}

/**
 * 설정값 변경 이력: AI 제안 · 승인/거절 · PLC 반영/인터록 거부. 백엔드를 거치지 않은 외부 명령의 결과도 남는다.
 * (변경 하나하나의 감사 기록은 GET /api/setpoint-changes/{id}/audit)
 */
export function SetpointHistory({ changes, onOpenWorkOrder }: Props) {
  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>설정값 변경 이력</h2>
        <span className="muted panel__note">AI 제안 → 작업자 승인 → 게이트웨이 → PLC (인터록)</span>
      </header>
      {changes.length === 0 ? (
        <p className="empty muted">
          아직 설정값 변경이 없습니다. 가상 PLC 모드(start-demo.ps1 -OpcUa)에서 AI 지시서가 설정값 조정을 권하면 여기에
          쌓입니다.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>시각</th>
                <th>설비 · 설정값</th>
                <th>변경</th>
                <th>상태</th>
                <th>요청 · 승인</th>
                <th>결과</th>
              </tr>
            </thead>
            <tbody>
              {changes.map((c) => (
                <tr key={c.id}>
                  <td>{formatTime(c.createdAt)}</td>
                  <td>
                    <b>{c.equipmentId}</b> {c.label ?? c.tag}
                  </td>
                  <td>
                    {withUnit(c.valueBefore ?? c.currentValue, c.unit)} → <b>{withUnit(c.proposedValue, c.unit)}</b>
                  </td>
                  <td>
                    <span className={`chip setpoint-chip setpoint-chip--${c.status.toLowerCase()}`}>
                      {SETPOINT_STATUS_LABEL[c.status]}
                    </span>
                  </td>
                  <td>
                    {c.origin === 'AI' && c.workOrderId ? (
                      <button className="link-button" onClick={() => onOpenWorkOrder(c.workOrderId!)}>
                        AI · WO-{c.workOrderId}
                      </button>
                    ) : (
                      '외부 명령 (승인 없음)'
                    )}
                    {c.decidedBy && c.origin === 'AI' && <div className="muted">{c.decidedBy}</div>}
                  </td>
                  <td className="setpoint-history__result">
                    {c.status === 'APPLIED' && `PLC 값 ${withUnit(c.valueAfter, c.unit)}`}
                    {(c.status === 'INTERLOCKED' || c.status === 'FAILED') && c.resultMessage}
                    {c.status === 'REJECTED' && (c.decisionNote ?? '-')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  )
}
