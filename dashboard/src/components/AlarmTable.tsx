import type { Alarm } from '../api'
import { displayUnit, EQUIPMENT_BY_ID, METRIC_LABEL } from '../equipment'
import { formatDuration, formatTime, formatValue } from '../format'
import { StatusBadge } from './StatusBadge'

/** 최근 알람 이력 (발생 → 상승 → 해제가 한 행). */
export function AlarmTable({ alarms, now }: { alarms: Alarm[]; now: number }) {
  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>알람 이력</h2>
        <span className="muted">최근 {alarms.length}건</span>
      </header>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>#</th>
              <th>설비</th>
              <th>지표</th>
              <th>심각도</th>
              <th>상태</th>
              <th className="num">발생값</th>
              <th className="num">최악값</th>
              <th className="num">기준</th>
              <th>발생</th>
              <th>지속</th>
            </tr>
          </thead>
          <tbody>
            {alarms.map((a) => {
              const unit = displayUnit(a.unit)
              const end = a.clearedAt ? Date.parse(a.clearedAt) : now
              return (
                <tr key={a.id}>
                  <td className="muted">{a.id}</td>
                  <td>{EQUIPMENT_BY_ID[a.equipmentId]?.name ?? a.equipmentId}</td>
                  <td>{METRIC_LABEL[a.metric] ?? a.metric}</td>
                  <td>
                    <StatusBadge status={a.severity} compact />
                  </td>
                  <td>{a.status === 'ACTIVE' ? <b>진행 중</b> : <span className="muted">해제</span>}</td>
                  <td className="num">{formatValue(a.triggerValue)}{unit}</td>
                  <td className="num">{formatValue(a.peakValue)}{unit}</td>
                  <td className="num">
                    {a.direction === 'HIGH' ? '≥' : '≤'} {formatValue(a.thresholdValue)}
                  </td>
                  <td>{formatTime(a.raisedAt)}</td>
                  <td>{formatDuration(end - Date.parse(a.raisedAt))}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
    </section>
  )
}
