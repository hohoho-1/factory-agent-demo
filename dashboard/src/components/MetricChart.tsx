import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { Threshold } from '../api'
import { formatTime, formatValue } from '../format'
import type { Point } from '../useLiveData'

interface Props {
  points: Point[]
  threshold?: Threshold
  unit: string
  label: string
}

interface Limit {
  y: number
  kind: 'warning' | 'critical'
  text: string
}

function limitsOf(t?: Threshold): Limit[] {
  if (!t) return []
  const out: Limit[] = []
  if (t.warnHigh != null) out.push({ y: t.warnHigh, kind: 'warning', text: `경고 ${t.warnHigh}` })
  if (t.critHigh != null) out.push({ y: t.critHigh, kind: 'critical', text: `위험 ${t.critHigh}` })
  if (t.warnLow != null) out.push({ y: t.warnLow, kind: 'warning', text: `경고 ${t.warnLow}` })
  if (t.critLow != null) out.push({ y: t.critLow, kind: 'critical', text: `위험 ${t.critLow}` })
  return out
}

/** 지표 1개의 최근 5분 추세. 단일 시리즈 + 경고/위험 기준선. */
export function MetricChart({ points, threshold, unit, label }: Props) {
  const limits = limitsOf(threshold)

  return (
    <div className="metric-chart" role="img" aria-label={`${label} 최근 5분 추세`}>
      <ResponsiveContainer width="100%" height={96}>
        <LineChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <CartesianGrid vertical={false} stroke="var(--grid)" />
          <XAxis dataKey="t" type="number" domain={['dataMin', 'dataMax']} hide />
          <YAxis
            width={36}
            axisLine={false}
            tickLine={false}
            tick={{ fill: 'var(--muted)', fontSize: 11 }}
            tickCount={3}
            domain={['auto', 'auto']}
          />
          {limits.map((l) => (
            <ReferenceLine
              key={l.text}
              y={l.y}
              ifOverflow="extendDomain"
              stroke={`var(--status-${l.kind})`}
              strokeDasharray="4 3"
              strokeWidth={1}
              // 경고는 오른쪽, 위험은 왼쪽에 라벨을 둬서 가까운 두 기준선의 글자가 겹치지 않게 한다
              label={{
                value: l.text,
                position: l.kind === 'warning' ? 'insideTopRight' : 'insideTopLeft',
                fill: 'var(--text-secondary)',
                fontSize: 10,
              }}
            />
          ))}
          <Tooltip
            cursor={{ stroke: 'var(--axis)', strokeWidth: 1 }}
            isAnimationActive={false}
            content={({ active, payload }) => {
              const p = payload?.[0]?.payload as Point | undefined
              if (!active || !p) return null
              return (
                <div className="chart-tooltip">
                  <div className="chart-tooltip__time">{formatTime(p.t)}</div>
                  <div>
                    <span className="chart-tooltip__swatch" /> {label}{' '}
                    <strong>
                      {formatValue(p.v)}
                      {unit}
                    </strong>
                  </div>
                </div>
              )
            }}
          />
          <Line
            type="monotone"
            dataKey="v"
            stroke="var(--series-1)"
            strokeWidth={2}
            dot={false}
            activeDot={{ r: 4, stroke: 'var(--surface)', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
