import { useEffect, useState } from 'react'
import { getJson, type ActionStats } from '../api'
import { EQUIPMENT_BY_ID, METRIC_LABEL } from '../equipment'
import { formatTime } from '../format'

interface Props {
  /** 값이 바뀌면 다시 읽는다 (알람 발생·해제, 조치 완료 시점) */
  refreshKey: string
  /** 이 설비·지표의 조치 이력으로 매뉴얼 개선 제안을 요청한다 */
  onPropose: (equipmentId: string, metric: string) => Promise<void>
}

/**
 * 조치 이력 요약: 설비·지표별 이상 횟수와 작업자가 입력한 원인·결과.
 * 기록이 쌓일수록 반복 고장 원인이 보이게 하는 표. 읽기 전용이라 실패해도 다른 화면에는 영향이 없다.
 */
export function ActionStatsTable({ refreshKey, onPropose }: Props) {
  const [stats, setStats] = useState<ActionStats[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [proposing, setProposing] = useState<string | null>(null)

  const propose = async (s: ActionStats) => {
    const key = `${s.equipmentId}:${s.metric}`
    setProposing(key)
    try {
      await onPropose(s.equipmentId, s.metric)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setProposing(null)
    }
  }

  useEffect(() => {
    let cancelled = false
    getJson<ActionStats[]>('/api/action-stats')
      .then((s) => {
        if (!cancelled) {
          setStats(s)
          setError(null)
        }
      })
      .catch((e) => !cancelled && setError(e instanceof Error ? e.message : String(e)))
    return () => {
      cancelled = true
    }
  }, [refreshKey])

  return (
    <section className="card panel">
      <header className="panel__head">
        <h2>조치 이력 요약</h2>
        <span className="muted">설비·지표별 누적 · 작업자가 입력한 원인과 결과</span>
      </header>
      {error && <p className="empty muted">요약을 불러오지 못했습니다: {error}</p>}
      {!error && stats?.length === 0 && <p className="empty muted">아직 알람 기록이 없습니다.</p>}
      {!error && stats && stats.length > 0 && (
        <div className="table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>설비</th>
                <th>지표</th>
                <th className="num">이상</th>
                <th className="num">위험</th>
                <th className="num">조치 완료</th>
                <th className="num">해결률</th>
                <th className="num">평균 처리</th>
                <th>주요 원인 (작업자 입력)</th>
                <th>최근 발생</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {stats.map((s) => (
                <tr key={`${s.equipmentId}:${s.metric}`}>
                  <td>{EQUIPMENT_BY_ID[s.equipmentId]?.name ?? s.equipmentId}</td>
                  <td>{METRIC_LABEL[s.metric] ?? s.metric}</td>
                  <td className="num">
                    <b>{s.alarmCount}</b>
                  </td>
                  <td className="num">{s.criticalCount}</td>
                  <td className="num">{s.completedCount}</td>
                  <td className="num">
                    {s.completedCount ? `${Math.round((s.resolvedCount / s.completedCount) * 100)}%` : '-'}
                  </td>
                  <td className="num">{s.avgHandleMinutes != null ? `${s.avgHandleMinutes}분` : '-'}</td>
                  <td className="stats__causes">
                    {s.topCauses.length === 0 ? (
                      <span className="muted">-</span>
                    ) : (
                      s.topCauses.map((c) => (
                        <span key={c.cause} className="cause">
                          {c.cause} <b>{c.count}</b>
                        </span>
                      ))
                    )}
                  </td>
                  <td>{s.lastRaisedAt ? formatTime(s.lastRaisedAt) : '-'}</td>
                  <td>
                    <button
                      type="button"
                      className="link-button"
                      onClick={() => void propose(s)}
                      disabled={s.completedCount === 0 || proposing !== null}
                      title={
                        s.completedCount === 0
                          ? '조치 완료 기록이 있어야 매뉴얼과 비교할 수 있습니다'
                          : 'AI가 조치 이력을 매뉴얼과 비교해 개선안 초안을 씁니다'
                      }
                    >
                      {proposing === `${s.equipmentId}:${s.metric}` ? '요청 중…' : '매뉴얼 개선 제안'}
                    </button>
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
