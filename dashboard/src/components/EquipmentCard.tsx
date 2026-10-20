import { useState } from 'react'
import { postJson, type Alarm, type AlarmShelf, type BatchState, type Forecast, type PhaseRules, type Rules } from '../api'
import { BATCH_PHASES, displayUnit, METRIC_LABEL, PHASE_LABEL, type EquipmentInfo } from '../equipment'
import { formatDuration, formatValue } from '../format'
import { seriesKey, type SeriesMap } from '../useLiveData'
import { MetricChart } from './MetricChart'
import { withUnit } from './SetpointCard'
import { StatusBadge, worstStatus, type Status } from './StatusBadge'
import { loadWorker } from './WorkOrderAction'

interface Props {
  equipment: EquipmentInfo
  series: SeriesMap
  units: Record<string, string | null>
  rules: Rules
  phaseRules: PhaseRules
  activeAlarms: Map<string, Alarm>
  forecasts: Record<string, Forecast>
  batch: BatchState | undefined
  shelf: AlarmShelf | undefined
  onShelfChanged: (shelf: AlarmShelf) => void
  now: number
}

/** 30초 넘게 안 들어온 값은 쓰지 않는다 (가상 센서 모드로 바꿨거나 게이트웨이가 끊김) */
const FRESH_MS = 30_000

/** 예측 경보 문구: "경고 기준 4.5 까지 약 25초" (화면이 etaAt 으로 직접 카운트다운) */
export function forecastText(f: Forecast, now: number): string {
  const seconds = Math.max(0, Math.round((Date.parse(f.etaAt) - now) / 1000))
  return `기준 ${f.direction === 'HIGH' ? '≥' : '≤'} ${formatValue(f.limit)} 까지 약 ${seconds}초`
}

/** 배치 진행 표시: 배치 번호 · 레시피 · 현재 단계(경과) + 단계 순서 점 */
function BatchBanner({ batch, now }: { batch: BatchState; now: number }) {
  const running = batch.batchId != null && batch.phase !== 'IDLE'
  const current = BATCH_PHASES.indexOf(batch.phase as (typeof BATCH_PHASES)[number])
  return (
    <div className={`batch${running ? '' : ' batch--idle'}`}>
      <div className="batch__head">
        <span className="batch__label">{running ? `배치 ${batch.batchId}` : '배치 대기'}</span>
        {running && batch.recipe && <span className="muted">{batch.recipe}</span>}
        <span className="batch__phase">
          <b>{PHASE_LABEL[batch.phase] ?? batch.phase}</b>
          {running && <span className="muted"> {formatDuration(now - Date.parse(batch.phaseStartedAt))}</span>}
        </span>
      </div>
      {running && (
        <ol className="batch__steps" aria-label="배치 단계">
          {BATCH_PHASES.map((p, i) => (
            <li
              key={p}
              className={i < current ? 'batch__step--done' : i === current ? 'batch__step--now' : ''}
              aria-current={i === current ? 'step' : undefined}
            >
              {PHASE_LABEL[p]}
            </li>
          ))}
        </ol>
      )}
    </div>
  )
}

export function EquipmentCard(props: Props) {
  const { equipment, series, units, rules, phaseRules, activeAlarms, forecasts, batch, shelf, now } = props
  const onShelf = props.onShelfChanged
  const [busy, setBusy] = useState(false)
  const fresh = (metric: string) => {
    const points = series[seriesKey(equipment.id, metric)] ?? []
    const p = points[points.length - 1]
    return p && now - p.t < FRESH_MS ? p.v : undefined
  }
  const metrics = [...equipment.metrics, ...(equipment.optionalMetrics ?? []).filter((m) => fresh(m) !== undefined)]
  const statusOf = (metric: string): Status => {
    const key = seriesKey(equipment.id, metric)
    return activeAlarms.get(key)?.severity ?? (forecasts[key] ? 'FORECAST' : 'NORMAL')
  }
  const cardStatus = worstStatus(metrics.map(statusOf))
  const phase = batch?.phase

  const shelve = async () => {
    // eslint-disable-next-line no-alert -- 작업자 사유 한 줄만 받는 데모 화면
    const reason = window.prompt(`${equipment.name}의 새 알람을 30분 동안 억제합니다. 사유를 입력하세요 (예: 베어링 교체 중)`)
    if (!reason?.trim()) return
    setBusy(true)
    try {
      onShelf(await postJson<AlarmShelf>('/api/alarm-shelves', {
        equipmentId: equipment.id,
        minutes: 30,
        reason,
        worker: loadWorker(),
      }))
    } finally {
      setBusy(false)
    }
  }
  const release = async () => {
    if (!shelf) return
    setBusy(true)
    try {
      onShelf(await postJson<AlarmShelf>(`/api/alarm-shelves/${shelf.id}/release`, { worker: loadWorker() }))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className={`card equipment equipment--${cardStatus.toLowerCase()}`}>
      <header className="equipment__head">
        <div>
          <h2>{equipment.name}</h2>
          <p className="muted">
            {equipment.id} · {equipment.description}
          </p>
        </div>
        <div className="equipment__status">
          <StatusBadge status={cardStatus} />
          {!shelf && (
            <button className="link-button equipment__shelve" onClick={shelve} disabled={busy}>
              알람 억제
            </button>
          )}
        </div>
      </header>

      {shelf && (
        <div className="shelf" title={`${shelf.shelvedBy} · ${shelf.reason}`}>
          <span>
            <b>알람 억제 중</b> · {formatDuration(Date.parse(shelf.untilAt) - now)} 남음 · {shelf.reason}
          </span>
          <button className="link-button" onClick={release} disabled={busy}>
            해제
          </button>
        </div>
      )}

      {batch && <BatchBanner batch={batch} now={now} />}

      {equipment.setpoints?.map((sp) => {
        const value = fresh(sp.tag)
        if (value === undefined) return null // 가상 센서 모드: PLC 설정값 없음
        const unit = units[seriesKey(equipment.id, sp.tag)] ?? null
        const pv = sp.pv ? fresh(sp.pv) : undefined
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

      {metrics.map((metric) => {
        const key = seriesKey(equipment.id, metric)
        const points = series[key] ?? []
        const last = points[points.length - 1]
        const unit = displayUnit(units[key])
        const label = METRIC_LABEL[metric] ?? metric
        const status = statusOf(metric)
        const forecast = status === 'FORECAST' ? forecasts[key] : undefined
        const phaseRule = phase ? phaseRules[equipment.type]?.[metric]?.[phase] : undefined
        return (
          <div className="metric" key={metric}>
            <div className="metric__head">
              <span className="metric__label">{label}</span>
              {phaseRule && phase && <span className="phase-rule">{PHASE_LABEL[phase] ?? phase} 기준</span>}
              {status !== 'NORMAL' && <StatusBadge status={status} compact />}
              {forecast && <span className="forecast-eta">{forecastText(forecast, now)}</span>}
              <span className="metric__value">
                {last ? formatValue(last.v) : '—'}
                <small>{unit}</small>
              </span>
            </div>
            <MetricChart
              points={points}
              threshold={phaseRule ?? rules[equipment.type]?.[metric]}
              unit={unit}
              label={label}
            />
          </div>
        )
      })}
    </section>
  )
}
