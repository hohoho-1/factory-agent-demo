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
