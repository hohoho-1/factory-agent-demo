import type { Alarm, Rules } from '../api'
import { displayUnit, METRIC_LABEL, type EquipmentInfo } from '../equipment'
import { formatValue } from '../format'
import { seriesKey, type SeriesMap } from '../useLiveData'
import { MetricChart } from './MetricChart'
import { StatusBadge, worstStatus, type Status } from './StatusBadge'

interface Props {
  equipment: EquipmentInfo
  series: SeriesMap
  units: Record<string, string | null>
  rules: Rules
  activeAlarms: Map<string, Alarm>
}

export function EquipmentCard({ equipment, series, units, rules, activeAlarms }: Props) {
  const statusOf = (metric: string): Status =>
    activeAlarms.get(seriesKey(equipment.id, metric))?.severity ?? 'NORMAL'
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

      {equipment.metrics.map((metric) => {
        const key = seriesKey(equipment.id, metric)
        const points = series[key] ?? []
        const last = points[points.length - 1]
        const unit = displayUnit(units[key])
        const label = METRIC_LABEL[metric] ?? metric
        const status = statusOf(metric)
        return (
          <div className="metric" key={metric}>
            <div className="metric__head">
              <span className="metric__label">{label}</span>
              {status !== 'NORMAL' && <StatusBadge status={status} compact />}
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
