import { useEffect, useMemo, useState } from 'react'
import type { Alarm, WorkOrder } from './api'
import { ActionStatsTable } from './components/ActionStatsTable'
import { AlarmPanel } from './components/AlarmPanel'
import { AlarmTable } from './components/AlarmTable'
import { EquipmentCard } from './components/EquipmentCard'
import { HandoverModal } from './components/HandoverModal'
import { WorkOrderModal } from './components/WorkOrderModal'
import { WorkOrderPanel } from './components/WorkOrderPanel'
import { EQUIPMENT } from './equipment'
import { seriesKey, useLiveData } from './useLiveData'

function useNow(intervalMs: number): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), intervalMs)
    return () => window.clearInterval(id)
  }, [intervalMs])
  return now
}

type Theme = 'light' | 'dark'

function useTheme(): [Theme | null, () => void] {
  const [theme, setTheme] = useState<Theme | null>(() => {
    try {
      return (localStorage.getItem('theme') as Theme | null) ?? null
    } catch {
      return null
    }
  })
  useEffect(() => {
    if (theme) document.documentElement.dataset.theme = theme
    else delete document.documentElement.dataset.theme
  }, [theme])
  const toggle = () => {
    const current = theme ?? (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light')
    const next: Theme = current === 'dark' ? 'light' : 'dark'
    setTheme(next)
    try {
      localStorage.setItem('theme', next)
    } catch {
      /* 저장 못 해도 동작에는 문제 없음 */
    }
  }
  return [theme, toggle]
}

export default function App() {
  const live = useLiveData()
  const now = useNow(1000)
  const [, toggleTheme] = useTheme()
  // id 만 들고 있다가 목록에서 찾는다: 확인·조치 완료가 반영된 최신 상태를 모달에 보여 주기 위해
  const [openWoId, setOpenWoId] = useState<number | null>(null)
  const openWo = live.workOrders.find((w) => w.id === openWoId) ?? null
  const setOpenWo = (wo: WorkOrder) => setOpenWoId(wo.id)
  const [handoverOpen, setHandoverOpen] = useState(false)

  const activeAlarms = useMemo(() => {
    const map = new Map<string, Alarm>()
    for (const a of live.alarms) {
      if (a.status === 'ACTIVE') map.set(seriesKey(a.equipmentId, a.metric), a)
    }
    return map
  }, [live.alarms])

  // 알람 발생·상승·해제나 조치 완료가 있을 때만 요약을 다시 읽는다 (측정값 갱신마다 읽지 않게)
  const statsKey = useMemo(() => {
    const alarmPart = live.alarms.map((a) => `${a.id}${a.severity[0]}${a.status[0]}`).join(',')
    const donePart = live.workOrders.filter((w) => w.status === 'COMPLETED').map((w) => w.id).join(',')
    return `${alarmPart}|${donePart}`
  }, [live.alarms, live.workOrders])

  const critical = [...activeAlarms.values()].filter((a) => a.severity === 'CRITICAL').length
  const warning = activeAlarms.size - critical

  return (
    <div className="app">
      <header className="topbar">
        <div>
          <h1>Line 1 실시간 관제</h1>
          <p className="muted">KMPC 스타일 미니 라인 · 원료 탱크 2 · 배합기 1 · 충진기 1</p>
        </div>
        <div className="topbar__right">
          <div className="kpi">
            <span className="kpi__label">위험</span>
            <span className={`kpi__value${critical ? ' kpi__value--critical' : ''}`}>{critical}</span>
          </div>
          <div className="kpi">
            <span className="kpi__label">경고</span>
            <span className={`kpi__value${warning ? ' kpi__value--warning' : ''}`}>{warning}</span>
          </div>
          <span className={`conn ${live.connected ? 'conn--on' : 'conn--off'}`}>
            <span className="conn__dot" />
            {live.connected ? '실시간 연결' : '연결 끊김'}
          </span>
          <button className="button button--ghost" onClick={() => setHandoverOpen(true)}>
            교대 인수인계
          </button>
          <span className="clock">{new Date(now).toLocaleTimeString('ko-KR', { hour12: false })}</span>
          <button className="icon-button" onClick={toggleTheme} aria-label="밝게/어둡게 전환" title="밝게/어둡게 전환">
            ◐
          </button>
        </div>
      </header>

      {live.error && <div className="error">백엔드에 연결하지 못했습니다: {live.error}</div>}

      <main className="layout">
        <div className="equipment-grid">
          {EQUIPMENT.map((eq) => (
            <EquipmentCard
              key={eq.id}
              equipment={eq}
              series={live.series}
              units={live.units}
              rules={live.rules}
              activeAlarms={activeAlarms}
            />
          ))}
        </div>
        {/* 오른쪽 열은 높이를 설비 카드 영역에 맞추고, 넘치는 지시서 목록은 패널 안에서 스크롤한다 */}
        <aside className="side">
          <div className="side__inner">
            <AlarmPanel
              alarms={live.alarms}
              workOrders={live.workOrders}
              series={live.series}
              now={now}
              onOpenWorkOrder={setOpenWo}
            />
            <WorkOrderPanel workOrders={live.workOrders} onOpen={setOpenWo} />
          </div>
        </aside>
        <div className="full">
          <ActionStatsTable refreshKey={statsKey} />
        </div>
        <div className="full">
          <AlarmTable alarms={live.alarms} now={now} />
        </div>
      </main>

      {openWo && (
        <WorkOrderModal workOrder={openWo} onUpdated={live.updateWorkOrder} onClose={() => setOpenWoId(null)} />
      )}
      {handoverOpen && (
        <HandoverModal
          reports={live.handovers}
          now={now}
          onCreated={live.updateHandover}
          onClose={() => setHandoverOpen(false)}
        />
      )}
    </div>
  )
}
