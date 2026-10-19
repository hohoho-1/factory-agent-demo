export type Severity = 'WARNING' | 'CRITICAL'
export type AlarmStatus = 'ACTIVE' | 'CLEARED'

export interface Reading {
  id: number
  equipmentId: string
  equipmentType: string
  metric: string
  value: number
  unit: string | null
  measuredAt: string
}

export interface Alarm {
  id: number
  equipmentId: string
  equipmentType: string
  metric: string
  unit: string | null
  severity: Severity
  status: AlarmStatus
  direction: 'HIGH' | 'LOW'
  thresholdValue: number
  triggerValue: number
  peakValue: number
  lastValue: number
  message: string
  raisedAt: string
  updatedAt: string
  clearedAt: string | null
}

export interface ReferenceDoc {
  manualId: string
  title: string
  section: string
  score: number
}

export interface WorkOrder {
  id: number
  alarmId: number
  equipmentId: string
  metric: string
  severity: Severity
  title: string
  summary: string | null
  body: string
  references: ReferenceDoc[]
  generator: string
  createdAt: string
  equipmentType: string
  /** 근거 매뉴얼의 '가능 원인'. 작업자가 원인을 고르는 선택지 (이전 지시서는 빈 배열) */
  causeOptions: string[]
  status: WorkOrderStatus
  worker: string | null
  acknowledgedAt: string | null
  rootCause: string | null
  actionTaken: string | null
  outcome: ActionOutcome | null
  completedAt: string | null
  supersededBy: number | null
}

/** SUPERSEDED: 같은 알람의 다른 지시서가 조치 완료되어 함께 닫힘 */
export type WorkOrderStatus = 'OPEN' | 'ACKNOWLEDGED' | 'COMPLETED' | 'SUPERSEDED'
export type ActionOutcome = 'RESOLVED' | 'PARTIAL' | 'UNRESOLVED'

export interface ActionResult {
  worker: string
  rootCause: string
  actionTaken: string
  outcome: ActionOutcome
}

/** 교대 인수인계 리포트. PENDING 이면 에이전트가 작성 중 */
export interface HandoverReport {
  id: number
  windowFrom: string
  windowTo: string
  status: 'PENDING' | 'DONE'
  requestedBy: string | null
  generator: string | null
  title: string | null
  body: string | null
  createdAt: string
  completedAt: string | null
}

export interface ActionStats {
  equipmentId: string
  metric: string
  alarmCount: number
  criticalCount: number
  lastRaisedAt: string | null
  completedCount: number
  resolvedCount: number
  avgHandleMinutes: number | null
  topCauses: { cause: string; count: number }[]
}

export interface Threshold {
  warnHigh: number | null
  critHigh: number | null
  warnLow: number | null
  critLow: number | null
}

/** 설비 유형 → 지표 → 임계값 */
export type Rules = Record<string, Record<string, Threshold>>

export interface AlarmEventMessage {
  event: 'RAISED' | 'ESCALATED' | 'CLEARED'
  alarm: Alarm
}

export async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) {
    throw new Error(`${path} → HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}

export async function postJson<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    throw new Error(`${path} → HTTP ${res.status}`)
  }
  return res.json() as Promise<T>
}
