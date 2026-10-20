import type { Alarm, Forecast, WorkOrder } from '../api'
import { displayUnit, EQUIPMENT_BY_ID, METRIC_LABEL, PHASE_LABEL } from '../equipment'
import { formatDuration, formatTime, formatValue } from '../format'
import { seriesKey, type SeriesMap } from '../useLiveData'
import { forecastText } from './EquipmentCard'
import { StatusBadge } from './StatusBadge'

interface Props {
  forecasts: Record<string, Forecast>
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
export function AlarmPanel({ forecasts, alarms, workOrders, series, now, onOpenWorkOrder }: Props) {
  const active = alarms
    .filter((a) => a.status === 'ACTIVE')
    .sort((a, b) =>
      a.severity === b.severity ? Date.parse(b.raisedAt) - Date.parse(a.raisedAt) : a.severity === 'CRITICAL' ? -1 : 1,
    )
  const predicted = Object.values(forecasts)

  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>활성 알람</h2>
        <span className="count">{active.length}</span>
      </header>
      {predicted.length > 0 && (
        <ul className="alarm-list">
          {predicted.map((f) => {
            const unit = displayUnit(f.unit)
            return (
              <li key={seriesKey(f.equipmentId, f.metric)} className="alarm alarm--forecast">
                <div className="alarm__top">
                  <StatusBadge status="FORECAST" compact />
                  <strong>
                    {EQUIPMENT_BY_ID[f.equipmentId]?.name ?? f.equipmentId} {METRIC_LABEL[f.metric] ?? f.metric}
                  </strong>
                  <span className="muted alarm__elapsed">{formatTime(f.raisedAt)} 감지</span>
                </div>
                <div className="alarm__values">
                  <b>{forecastText(f, now)}</b> · 현재 {formatValue(f.currentValue)}
                  {unit} · 추세 {f.slopePerMinute > 0 ? '+' : ''}
                  {formatValue(f.slopePerMinute)}
                  {unit}/분
                </div>
                <div className="alarm__foot muted">아직 기준 전 — 추세로 미리 알림 (점검 준비)</div>
              </li>
            )
          })}
        </ul>
      )}
      {active.length === 0 && predicted.length > 0 ? null : active.length === 0 ? (
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
                {a.batchPhase && (
                  <div className="alarm__phase">
                    배치 {a.batchId ?? ''} · {PHASE_LABEL[a.batchPhase] ?? a.batchPhase} 단계 기준으로 판정
                  </div>
                )}
                {a.forecastLeadSeconds != null && (
                  <div className="alarm__lead">◆ 발생 {a.forecastLeadSeconds}초 전에 추세로 예측됨</div>
                )}
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
