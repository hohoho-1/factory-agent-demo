import type { Alarm, Forecast, Rules } from '../api'
import { displayUnit, METRIC_LABEL, type EquipmentInfo } from '../equipment'
import { formatValue } from '../format'
import { seriesKey, type SeriesMap } from '../useLiveData'
import { MetricChart } from './MetricChart'
import { withUnit } from './SetpointCard'
import { StatusBadge, worstStatus, type Status } from './StatusBadge'

interface Props {
  equipment: EquipmentInfo
  series: SeriesMap
  units: Record<string, string | null>
  rules: Rules
  activeAlarms: Map<string, Alarm>
  forecasts: Record<string, Forecast>
  now: number
}

/** 예측 경보 문구: "경고 기준 4.5 까지 약 25초" (화면이 etaAt 으로 직접 카운트다운) */
export function forecastText(f: Forecast, now: number): string {
  const seconds = Math.max(0, Math.round((Date.parse(f.etaAt) - now) / 1000))
  return `기준 ${f.direction === 'HIGH' ? '≥' : '≤'} ${formatValue(f.limit)} 까지 약 ${seconds}초`
}

export function EquipmentCard({ equipment, series, units, rules, activeAlarms, forecasts, now }: Props) {
  const statusOf = (metric: string): Status => {
    const key = seriesKey(equipment.id, metric)
    return activeAlarms.get(key)?.severity ?? (forecasts[key] ? 'FORECAST' : 'NORMAL')
  }
  const cardStatus = worstStatus(equipment.metrics.map(statusOf))

  return (
    <section className={`card equipment equipment--${cardStatus.toLowerCase()}`}>
      <header className="equipment__head">
        <div>
          <h2>{equipment.name}</h2>
          <p className="muted">
            {equipment.id} · {equipment.description}
          </p>
        </div>
        <StatusBadge status={cardStatus} />
      </header>

      {equipment.setpoints?.map((sp) => {
        const last = (metric: string) => {
          const points = series[seriesKey(equipment.id, metric)] ?? []
          const p = points[points.length - 1]
          // 30초 넘게 안 들어온 값은 쓰지 않는다 (가상 센서 모드로 바꿨거나 게이트웨이가 끊김)
          return p && now - p.t < 30_000 ? p.v : undefined
        }
        const value = last(sp.tag)
        if (value === undefined) return null // 가상 센서 모드: PLC 설정값 없음
        const unit = units[seriesKey(equipment.id, sp.tag)] ?? null
        const pv = sp.pv ? last(sp.pv) : undefined
        return (
          <div className="sp-row" key={sp.tag} title="PLC 설정값(SP) — AI 제안을 승인하면 바뀝니다">
            <span className="sp-row__label">SP {sp.label}</span>
            <b>{withUnit(value, unit)}</b>
            {pv !== undefined && Math.abs(pv - value) >= 0.05 && (
              <span className="muted">실제 {withUnit(pv, unit)} (따라가는 중)</span>
            )}
          </div>
        )
      })}

      {equipment.metrics.map((metric) => {
        const key = seriesKey(equipment.id, metric)
        const points = series[key] ?? []
        const last = points[points.length - 1]
        const unit = displayUnit(units[key])
        const label = METRIC_LABEL[metric] ?? metric
        const status = statusOf(metric)
        const forecast = status === 'FORECAST' ? forecasts[key] : undefined
        return (
          <div className="metric" key={metric}>
            <div className="metric__head">
              <span className="metric__label">{label}</span>
              {status !== 'NORMAL' && <StatusBadge status={status} compact />}
              {forecast && <span className="forecast-eta">{forecastText(forecast, now)}</span>}
              <span className="metric__value">
                {last ? formatValue(last.v) : '—'}
                <small>{unit}</small>
              </span>
            </div>
            <MetricChart points={points} threshold={rules[equipment.type]?.[metric]} unit={unit} label={label} />
          </div>
        )
      })}
    </section>
  )
}
