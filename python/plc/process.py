"""
가상 PLC 의 공정 모델과 인터록. OPC UA 와 무관한 순수 로직이라 단독으로 시험할 수 있다.

설비 모델은 sensors/virtual_sensors.py 를 그대로 쓰고, 그 위에 쓰기 가능한 설정값(SP)을 얹는다.
- MIXER-01 speed_sp (교반 회전수 설정값, rpm): 실제 회전수(speed)가 초당 3rpm 씩 따라가고,
  진동은 회전수 비율의 세제곱, 전류는 부하에 비례해 바뀐다. 회전수를 낮추면 진동이 내려간다.
- TANK-02 temp_sp (온도 설정값, C): 탱크 온도가 이 값으로 수렴한다 (재킷 가열 PID 를 단순화).

인터록은 PLC 안의 마지막 안전장치다. AI·백엔드가 무엇을 보내든 여기서 다시 막는다.
- 허용 범위 밖 값, 한 번에 너무 큰 변경 → BadOutOfRange
- 위험 조건에서 위험을 키우는 방향의 변경(진동 위험 중 증속, 온도 경고 중 설정값 상향) → BadInvalidState
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from sensors.virtual_sensors import SCENARIOS, AnomalyInjector, build_line

MIXER_ID = "MIXER-01"
NOMINAL_MIXER_RPM = 60.0
MIXER_RPM_PER_SCAN = 3.0  # 실제 회전수가 설정값을 따라가는 속도 (인버터 가감속)


@dataclass(frozen=True)
class SetpointTag:
    equipment_id: str
    tag: str
    unit: str
    label: str
    lo: float            # 설비 보호를 위한 하드 리밋 (백엔드 운전 범위보다 넓다)
    hi: float
    max_step: float      # 한 번에 바꿀 수 있는 최대 변경폭
    initial: float
    watch_metric: str    # 증가 방향 쓰기를 막을 때 보는 공정값
    block_raise_at: float
    block_reason: str


SETPOINT_TAGS: dict[tuple[str, str], SetpointTag] = {
    (MIXER_ID, "speed_sp"): SetpointTag(
        MIXER_ID, "speed_sp", "rpm", "교반 회전수 설정값", 30.0, 72.0, 20.0, NOMINAL_MIXER_RPM,
        "vibration", 7.1, "진동 위험(7.1mm/s 이상) 중에는 회전수를 올릴 수 없습니다"),
    ("TANK-02", "temp_sp"): SetpointTag(
        "TANK-02", "temp_sp", "C", "온도 설정값", 20.0, 60.0, 20.0, 40.0,
        "temperature", 50.0, "온도 경고(50C 이상) 중에는 설정값을 올릴 수 없습니다"),
}

# PLC 에만 있는 시나리오 (설정값이 있어야 의미가 있다): 이름 → (설비, 태그, 강제로 넣을 값)
PLC_SCENARIOS = {
    # 현장 HMI 에서 온도 설정값을 40 대신 55 로 잘못 입력 → 약 10초 뒤 온도 경고
    "tank_sp_misentry": ("TANK-02", "temp_sp", 55.0),
}


class InterlockError(Exception):
    """인터록이 쓰기를 거부했다. code 는 OPC UA 상태 코드 이름."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _fmt(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".")


class LineProcess:
    def __init__(self):
        self.line = build_line()
        self.by_id = {e.equipment_id: e for e in self.line}
        self.injector = AnomalyInjector(self.line)
        self.setpoints = {key: spec.initial for key, spec in SETPOINT_TAGS.items()}
        self.mixer_speed = NOMINAL_MIXER_RPM
        self.last: dict[str, dict[str, float]] = {}

    def units(self, equipment_id: str) -> dict[str, str]:
        units = {name: m.unit for name, m in self.by_id[equipment_id].metrics.items()}
        if equipment_id == MIXER_ID:
            units["speed"] = "rpm"
        for (eq, tag), spec in SETPOINT_TAGS.items():
            if eq == equipment_id:
                units[tag] = spec.unit
        return units

    def check_write(self, equipment_id: str, tag: str, value: float) -> None:
        """쓰기 전에 인터록을 검사한다. 통과하지 못하면 InterlockError."""
        spec = SETPOINT_TAGS.get((equipment_id, tag))
        if spec is None:
            raise InterlockError("BadNotWritable", f"{equipment_id}.{tag} 는 쓰기 가능한 설정값이 아닙니다")
        if not math.isfinite(value):
            raise InterlockError("BadOutOfRange", f"{spec.label} 값이 올바르지 않습니다 ({value})")
        if not spec.lo <= value <= spec.hi:
            raise InterlockError("BadOutOfRange", f"{spec.label} 허용 범위 {_fmt(spec.lo)}~{_fmt(spec.hi)}{spec.unit}"
                                                  f" 밖입니다 (요청 {_fmt(value)}{spec.unit})")
        current = self.setpoints[(equipment_id, tag)]
        if abs(value - current) > spec.max_step:
            raise InterlockError("BadOutOfRange", f"{spec.label}은 한 번에 {_fmt(spec.max_step)}{spec.unit}까지만"
                                                  f" 바꿀 수 있습니다 (현재 {_fmt(current)} → 요청 {_fmt(value)})")
        watched = self.last.get(equipment_id, {}).get(spec.watch_metric)
        if value > current and watched is not None and watched >= spec.block_raise_at:
            raise InterlockError("BadInvalidState", f"{spec.block_reason} (현재 {_fmt(watched)})")

    def write_setpoint(self, equipment_id: str, tag: str, value: float) -> float:
        """인터록 검사 후 설정값을 바꾸고 이전 값을 돌려준다."""
        self.check_write(equipment_id, tag, value)
        previous = self.setpoints[(equipment_id, tag)]
        self.setpoints[(equipment_id, tag)] = float(value)
        return previous

    def force_setpoint(self, equipment_id: str, tag: str, value: float) -> None:
        """현장 HMI 직접 입력 시뮬레이션 (시나리오용). 원격 쓰기가 아니라 인터록 검사를 거치지 않는다."""
        self.setpoints[(equipment_id, tag)] = float(value)

    def inject(self, name: str) -> bool:
        """이상 시나리오 시작. 알 수 없는 이름이면 False."""
        if name in SCENARIOS:
            self.injector.start(name)
            return True
        if name in PLC_SCENARIOS:
            eq, tag, value = PLC_SCENARIOS[name]
            self.force_setpoint(eq, tag, value)
            print(f"[ANOMALY] start {name}: {eq}.{tag} = {value} (HMI 오입력)", flush=True)
            return True
        return False

    def scan(self) -> dict[str, dict[str, float]]:
        """PLC 스캔 1회: 설정값을 공정에 반영하고 설비별 현재값(PV + SP)을 돌려준다."""
        tank2_sp = self.setpoints[("TANK-02", "temp_sp")]
        self.by_id["TANK-02"].metrics["temperature"].target = tank2_sp

        speed_sp = self.setpoints[(MIXER_ID, "speed_sp")]
        step = max(-MIXER_RPM_PER_SCAN, min(MIXER_RPM_PER_SCAN, speed_sp - self.mixer_speed))
        self.mixer_speed += step
        ratio = self.mixer_speed / NOMINAL_MIXER_RPM

        out: dict[str, dict[str, float]] = {}
        for eq in self.line:
            values = eq.read()
            if eq.equipment_id == MIXER_ID:
                values["vibration"] = round(values["vibration"] * ratio ** 3, 2)
                values["current"] = round(values["current"] * (0.3 + 0.7 * ratio), 2)
                values["speed"] = round(self.mixer_speed, 1)
                values["speed_sp"] = speed_sp
            elif eq.equipment_id == "TANK-02":
                values["temp_sp"] = tank2_sp
            out[eq.equipment_id] = values
        self.injector.tick()
        self.last = out
        return out
