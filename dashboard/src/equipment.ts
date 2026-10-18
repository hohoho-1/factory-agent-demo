export interface EquipmentInfo {
  id: string
  type: string
  name: string
  description: string
  metrics: string[]
}

/** 미니 라인 구성 (python/sensors/virtual_sensors.py 와 같은 설비) */
export const EQUIPMENT: EquipmentInfo[] = [
  { id: 'TANK-01', type: 'RAW_TANK', name: '원료 탱크 1', description: '수상 원료 · 25°C', metrics: ['level', 'temperature'] },
  { id: 'TANK-02', type: 'RAW_TANK', name: '원료 탱크 2', description: '오일상·계면활성제 · 40°C', metrics: ['level', 'temperature'] },
  { id: 'MIXER-01', type: 'MIXER', name: '배합기', description: '유화·교반', metrics: ['vibration', 'current'] },
  { id: 'FILLER-01', type: 'FILLER', name: '충진기', description: '로터리 액상 충진', metrics: ['speed'] },
]

export const EQUIPMENT_BY_ID = Object.fromEntries(EQUIPMENT.map((e) => [e.id, e]))

export const METRIC_LABEL: Record<string, string> = {
  level: '레벨',
  temperature: '온도',
  vibration: '진동',
  current: '전류',
  speed: '속도',
}

export function displayUnit(unit: string | null | undefined): string {
  if (!unit) return ''
  return unit === 'C' ? '°C' : unit
}
