import { useCallback, useEffect, useReducer } from 'react'
import {
  getJson,
  type Alarm,
  type AlarmEventMessage,
  type AlarmShelf,
  type AssistantTask,
  type BatchState,
  type Forecast,
  type ForecastEventMessage,
  type HandoverReport,
  type PhaseRules,
  type Reading,
  type Rules,
  type SetpointChange,
  type WorkOrder,
} from './api'

/** 차트에 보여 줄 시간 창 */
export const WINDOW_MS = 5 * 60 * 1000
const MAX_ALARMS = 50
const MAX_WORK_ORDERS = 50
const MAX_HANDOVERS = 10
const MAX_ASSISTANT_TASKS = 20
const MAX_SETPOINT_CHANGES = 30

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
  assistantTasks: AssistantTask[]
  /** 설정값 변경 제안 · 승인 · 결과 (최근 순) */
  setpointChanges: SetpointChange[]
  /** 진행 중인 예측 경보 (seriesKey → 예측). 실제 알람으로 이어지면 알람의 forecastLeadSeconds 에 남는다 */
  forecasts: Record<string, Forecast>
  /** 설비 → 현재 배치 단계 (가상 PLC 모드에서만) */
  batchStates: Record<string, BatchState>
  /** 진행 중인 알람 억제 */
  shelves: AlarmShelf[]
  rules: Rules
  phaseRules: PhaseRules
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
      assistantTasks: AssistantTask[]
      setpointChanges: SetpointChange[]
      forecasts: Forecast[]
      batchStates: BatchState[]
      shelves: AlarmShelf[]
      rules: Rules
      phaseRules: PhaseRules
    }
  | { type: 'forecast'; message: ForecastEventMessage }
  | { type: 'setpoint'; change: SetpointChange }
  | { type: 'batch'; state: BatchState }
  | { type: 'shelf'; shelf: AlarmShelf }
  | { type: 'assistant'; task: AssistantTask }
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
  assistantTasks: [],
  setpointChanges: [],
  forecasts: {},
  batchStates: {},
  shelves: [],
  rules: {},
  phaseRules: {},
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

/** 설정값 변경 진행 단계: 제안(0) → 명령 전송(1) → 끝(2: 반영 · 인터록 거부 · 실패 · 거절) */
function setpointStage(c: SetpointChange): number {
  if (c.status === 'PROPOSED') return 0
  return c.status === 'SENT' ? 1 : 2
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
        assistantTasks: action.assistantTasks,
        setpointChanges: action.setpointChanges,
        forecasts: Object.fromEntries(action.forecasts.map((f) => [seriesKey(f.equipmentId, f.metric), f])),
        batchStates: Object.fromEntries(action.batchStates.map((b) => [b.equipmentId, b])),
        shelves: action.shelves,
        rules: action.rules,
        phaseRules: action.phaseRules,
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
    case 'forecast': {
      const { type, forecast } = action.message
      const key = seriesKey(forecast.equipmentId, forecast.metric)
      if (type !== 'CLEARED') return { ...state, forecasts: { ...state.forecasts, [key]: forecast } }
      const { [key]: _removed, ...forecasts } = state.forecasts
      return { ...state, forecasts }
    }
    case 'batch':
      return { ...state, batchStates: { ...state.batchStates, [action.state.equipmentId]: action.state } }
    case 'shelf': {
      // 시작과 해제가 같은 id 로 온다. 해제된 것은 목록에서 뺀다
      const rest = state.shelves.filter((s) => s.id !== action.shelf.id)
      return { ...state, shelves: action.shelf.releasedAt ? rest : [action.shelf, ...rest] }
    }
    case 'assistant': {
      // 요청(PENDING)과 작성 완료(DONE)가 같은 id 로 온다. 최근 요청 순
      const rest = state.assistantTasks.filter((t) => t.id !== action.task.id)
      const assistantTasks = [action.task, ...rest]
        .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
        .slice(0, MAX_ASSISTANT_TASKS)
      return { ...state, assistantTasks }
    }
    case 'setpoint': {
      // 제안 → 승인 → 반영/인터록 거부가 같은 id 로 온다. 최근 순.
      // PLC 결과(SSE)가 승인 POST 응답보다 먼저 올 수 있으므로 앞 단계 상태로 되돌리지 않는다
      const existing = state.setpointChanges.find((c) => c.id === action.change.id)
      if (existing && setpointStage(action.change) < setpointStage(existing)) return state
      const rest = state.setpointChanges.filter((c) => c.id !== action.change.id)
      const setpointChanges = [action.change, ...rest]
        .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
        .slice(0, MAX_SETPOINT_CHANGES)
      return { ...state, setpointChanges }
    }
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
  updateAssistant: (task: AssistantTask) => void
  updateSetpoint: (change: SetpointChange) => void
  updateShelf: (shelf: AlarmShelf) => void
} {
  const [state, dispatch] = useReducer(reducer, initialState)
  // POST 응답을 바로 반영한다 (SSE 로도 같은 값이 오지만 기다리지 않게)
  const updateWorkOrder = useCallback((workOrder: WorkOrder) => dispatch({ type: 'workOrder', workOrder }), [])
  const updateHandover = useCallback((report: HandoverReport) => dispatch({ type: 'handover', report }), [])
  const updateAssistant = useCallback((task: AssistantTask) => dispatch({ type: 'assistant', task }), [])
  const updateSetpoint = useCallback((change: SetpointChange) => dispatch({ type: 'setpoint', change }), [])
  const updateShelf = useCallback((shelf: AlarmShelf) => dispatch({ type: 'shelf', shelf }), [])

  useEffect(() => {
    let cancelled = false
    let source: EventSource | null = null
    let needsResync = false

    const loadSnapshot = async () => {
      try {
        const [
          readings,
          alarms,
          workOrders,
          handovers,
          assistantTasks,
          setpointChanges,
          forecasts,
          batchStates,
          shelves,
          rules,
          phaseRules,
        ] = await Promise.all([
          getJson<Reading[]>(`/api/readings/history?minutes=${WINDOW_MS / 60000}`),
          getJson<Alarm[]>('/api/alarms'),
          getJson<WorkOrder[]>('/api/work-orders'),
          getJson<HandoverReport[]>('/api/handover-reports'),
          getJson<AssistantTask[]>('/api/assistant/tasks'),
          getJson<SetpointChange[]>('/api/setpoint-changes'),
          getJson<Forecast[]>('/api/forecasts'),
          getJson<BatchState[]>('/api/batch/state'),
          getJson<AlarmShelf[]>('/api/alarm-shelves'),
          getJson<Rules>('/api/alarm-rules'),
          getJson<PhaseRules>('/api/alarm-rules/phases'),
        ])
        if (!cancelled) {
          dispatch({
            type: 'snapshot',
            readings,
            alarms,
            workOrders,
            handovers,
            assistantTasks,
            setpointChanges,
            forecasts,
            batchStates,
            shelves,
            rules,
            phaseRules,
          })
        }
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
      source.addEventListener('forecast', (e) => dispatch({ type: 'forecast', message: parse<ForecastEventMessage>(e) }))
      source.addEventListener('assistant', (e) => dispatch({ type: 'assistant', task: parse<AssistantTask>(e) }))
      source.addEventListener('setpoint', (e) => dispatch({ type: 'setpoint', change: parse<SetpointChange>(e) }))
      source.addEventListener('batch', (e) => dispatch({ type: 'batch', state: parse<BatchState>(e) }))
      source.addEventListener('shelf', (e) => dispatch({ type: 'shelf', shelf: parse<AlarmShelf>(e) }))
    })

    return () => {
      cancelled = true
      source?.close()
    }
  }, [])

  return { ...state, updateWorkOrder, updateHandover, updateAssistant, updateSetpoint, updateShelf }
}
