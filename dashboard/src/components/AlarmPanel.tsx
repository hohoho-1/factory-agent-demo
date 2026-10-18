import type { Alarm, WorkOrder } from '../api'
import { displayUnit, EQUIPMENT_BY_ID, METRIC_LABEL } from '../equipment'
import { formatDuration, formatTime, formatValue } from '../format'
import { seriesKey, type SeriesMap } from '../useLiveData'
import { StatusBadge } from './StatusBadge'

interface Props {
  alarms: Alarm[]
  workOrders: WorkOrder[]
  series: SeriesMap
  now: number
  onOpenWorkOrder: (wo: WorkOrder) => void
}

/**
 * 현재 활성 알람. 심각도 높은 순, 같은 심각도는 최근 발생 순.
 * 알람 이벤트는 발생·상승·해제 때만 오므로, 현재값·최악값은 실시간 측정값으로 보정해 보여 준다.
 */
export function AlarmPanel({ alarms, workOrders, series, now, onOpenWorkOrder }: Props) {
  const active = alarms
    .filter((a) => a.status === 'ACTIVE')
    .sort((a, b) =>
      a.severity === b.severity ? Date.parse(b.raisedAt) - Date.parse(a.raisedAt) : a.severity === 'CRITICAL' ? -1 : 1,
    )

  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>활성 알람</h2>
        <span className="count">{active.length}</span>
      </header>
      {active.length === 0 ? (
        <p className="empty">
          <StatusBadge status="NORMAL" /> 모든 설비 정상 운전 중
        </p>
      ) : (
        <ul className="alarm-list">
          {active.map((a) => {
            const unit = displayUnit(a.unit)
            const latestWo = workOrders.find((w) => w.alarmId === a.id)
            const points = series[seriesKey(a.equipmentId, a.metric)] ?? []
            const current = points.length ? points[points.length - 1].v : a.lastValue
            const peak = a.direction === 'HIGH' ? Math.max(a.peakValue, current) : Math.min(a.peakValue, current)
            return (
              <li key={a.id} className={`alarm alarm--${a.severity.toLowerCase()}`}>
                <div className="alarm__top">
                  <StatusBadge status={a.severity} compact />
                  <strong>
                    {EQUIPMENT_BY_ID[a.equipmentId]?.name ?? a.equipmentId} {METRIC_LABEL[a.metric] ?? a.metric}
                  </strong>
                  <span className="muted alarm__elapsed">{formatDuration(now - Date.parse(a.raisedAt))} 경과</span>
                </div>
                <div className="alarm__values">
                  현재 <b>{formatValue(current)}{unit}</b> · 최악 {formatValue(peak)}{unit} · 기준{' '}
                  {a.direction === 'HIGH' ? '≥' : '≤'} {formatValue(a.thresholdValue)}{unit}
                </div>
                <div className="alarm__foot">
                  <span className="muted">#{a.id} · {formatTime(a.raisedAt)} 발생</span>
                  {latestWo ? (
                    <button className="link-button" onClick={() => onOpenWorkOrder(latestWo)}>
                      AI 조치 지시서 보기 →
                    </button>
                  ) : (
                    <span className="muted pulse">AI 지시서 작성 중…</span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
