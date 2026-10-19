import { useCallback, useEffect, useReducer } from 'react'
import {
  getJson,
  type Alarm,
  type AlarmEventMessage,
  type HandoverReport,
  type Reading,
  type Rules,
  type WorkOrder,
} from './api'

/** 차트에 보여 줄 시간 창 */
export const WINDOW_MS = 5 * 60 * 1000
const MAX_ALARMS = 50
const MAX_WORK_ORDERS = 50
const MAX_HANDOVERS = 10

export interface Point {
  t: number
  v: number
}

export type SeriesMap = Record<string, Point[]>

export const seriesKey = (equipmentId: string, metric: string) => `${equipmentId}:${metric}`

export interface LiveState {
  series: SeriesMap
  units: Record<string, string | null>
  alarms: Alarm[]
  workOrders: WorkOrder[]
  handovers: HandoverReport[]
  rules: Rules
  connected: boolean
  loaded: boolean
  error: string | null
}

type Action =
  | {
      type: 'snapshot'
      readings: Reading[]
      alarms: Alarm[]
      workOrders: WorkOrder[]
      handovers: HandoverReport[]
      rules: Rules
    }
  | { type: 'readings'; readings: Reading[] }
  | { type: 'alarm'; alarm: Alarm }
  | { type: 'workOrder'; workOrder: WorkOrder }
  | { type: 'handover'; report: HandoverReport }
  | { type: 'connection'; connected: boolean }
  | { type: 'error'; message: string }

const initialState: LiveState = {
  series: {},
  units: {},
  alarms: [],
  workOrders: [],
  handovers: [],
  rules: {},
  connected: false,
  loaded: false,
  error: null,
}

function appendReadings(
  series: SeriesMap,
  units: Record<string, string | null>,
  readings: Reading[],
): Pick<LiveState, 'series' | 'units'> {
  const nextSeries = { ...series }
  const nextUnits = { ...units }
  const touched = new Set<string>()
  let latest = 0

  for (const r of readings) {
    const key = seriesKey(r.equipmentId, r.metric)
    if (!touched.has(key)) {
      nextSeries[key] = [...(series[key] ?? [])]
      touched.add(key)
    }
    const t = Date.parse(r.measuredAt)
    nextSeries[key].push({ t, v: r.value })
    nextUnits[key] = r.unit
    latest = Math.max(latest, t)
  }

  // 시간 창 밖의 오래된 점은 앞에서부터 잘라낸다 (점은 시간순으로 들어온다)
  const cutoff = latest - WINDOW_MS
  for (const key of touched) {
    const points = nextSeries[key]
    const first = points.findIndex((p) => p.t >= cutoff)
    if (first > 0) nextSeries[key] = points.slice(first)
  }
  return { series: nextSeries, units: nextUnits }
}

function upsertAlarm(alarms: Alarm[], alarm: Alarm): Alarm[] {
  const rest = alarms.filter((a) => a.id !== alarm.id)
  return [alarm, ...rest]
    .sort((a, b) => Date.parse(b.raisedAt) - Date.parse(a.raisedAt))
    .slice(0, MAX_ALARMS)
}

function reducer(state: LiveState, action: Action): LiveState {
  switch (action.type) {
    case 'snapshot':
      return {
        ...state,
        ...appendReadings({}, {}, action.readings),
        alarms: action.alarms,
        workOrders: action.workOrders,
        handovers: action.handovers,
        rules: action.rules,
        loaded: true,
        error: null,
      }
    case 'readings':
      return { ...state, ...appendReadings(state.series, state.units, action.readings) }
    case 'alarm':
      return { ...state, alarms: upsertAlarm(state.alarms, action.alarm) }
    case 'workOrder':
      // 확인·조치 완료는 같은 id 로 다시 오므로 제자리에서 바꾼다
      if (state.workOrders.some((w) => w.id === action.workOrder.id)) {
        return {
          ...state,
          workOrders: state.workOrders.map((w) => (w.id === action.workOrder.id ? action.workOrder : w)),
        }
      }
      return { ...state, workOrders: [action.workOrder, ...state.workOrders].slice(0, MAX_WORK_ORDERS) }
    case 'handover': {
      // 요청(PENDING)과 작성 완료(DONE)가 같은 id 로 온다. 최근 요청 순, 10건까지
      const rest = state.handovers.filter((h) => h.id !== action.report.id)
      const handovers = [action.report, ...rest]
        .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
        .slice(0, MAX_HANDOVERS)
      return { ...state, handovers }
    }
    case 'connection':
      return { ...state, connected: action.connected }
    case 'error':
      return { ...state, error: action.message }
  }
}

/**
 * 초기 상태는 REST 로 한 번 읽고, 이후 변화는 SSE(/api/stream)로 받는다.
 * 연결이 끊겼다 다시 붙으면 놓친 알람·지시서를 맞추기 위해 REST 를 다시 읽는다.
 */
export function useLiveData(): LiveState & {
  updateWorkOrder: (wo: WorkOrder) => void
  updateHandover: (report: HandoverReport) => void
} {
  const [state, dispatch] = useReducer(reducer, initialState)
  // POST 응답을 바로 반영한다 (SSE 로도 같은 값이 오지만 기다리지 않게)
  const updateWorkOrder = useCallback((workOrder: WorkOrder) => dispatch({ type: 'workOrder', workOrder }), [])
  const updateHandover = useCallback((report: HandoverReport) => dispatch({ type: 'handover', report }), [])

  useEffect(() => {
    let cancelled = false
    let source: EventSource | null = null
    let needsResync = false

    const loadSnapshot = async () => {
      try {
        const [readings, alarms, workOrders, handovers, rules] = await Promise.all([
          getJson<Reading[]>(`/api/readings/history?minutes=${WINDOW_MS / 60000}`),
          getJson<Alarm[]>('/api/alarms'),
          getJson<WorkOrder[]>('/api/work-orders'),
          getJson<HandoverReport[]>('/api/handover-reports'),
          getJson<Rules>('/api/alarm-rules'),
        ])
        if (!cancelled) dispatch({ type: 'snapshot', readings, alarms, workOrders, handovers, rules })
      } catch (e) {
        if (!cancelled) dispatch({ type: 'error', message: e instanceof Error ? e.message : String(e) })
      }
    }

    const parse = <T,>(e: Event) => JSON.parse((e as MessageEvent<string>).data) as T

    loadSnapshot().finally(() => {
      if (cancelled) return
      source = new EventSource('/api/stream')
      source.onopen = () => {
        dispatch({ type: 'connection', connected: true })
        if (needsResync) {
          needsResync = false
          void loadSnapshot()
        }
      }
      source.onerror = () => {
        dispatch({ type: 'connection', connected: false })
        needsResync = true
      }
      source.addEventListener('readings', (e) => dispatch({ type: 'readings', readings: parse<Reading[]>(e) }))
      source.addEventListener('alarm', (e) => dispatch({ type: 'alarm', alarm: parse<AlarmEventMessage>(e).alarm }))
      source.addEventListener('work-order', (e) => dispatch({ type: 'workOrder', workOrder: parse<WorkOrder>(e) }))
      source.addEventListener('handover', (e) => dispatch({ type: 'handover', report: parse<HandoverReport>(e) }))
    })

    return () => {
      cancelled = true
      source?.close()
    }
  }, [])

  return { ...state, updateWorkOrder, updateHandover }
}
