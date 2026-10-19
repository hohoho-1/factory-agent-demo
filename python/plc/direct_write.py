"""
백엔드 승인을 거치지 않은 설정값 명령을 게이트웨이에 직접 보낸다 (인터록 시연용).

상위 시스템이 잘못된 값을 보내도 PLC 인터록이 막는다는 것을 보여 준다.
결과는 게이트웨이가 factory/line1/commands/results 로 보고하고, 백엔드가 '외부 명령'으로 기록한다.

실행 (python 폴더에서):
  python -m plc.direct_write MIXER-01 speed_sp 95
"""
from __future__ import annotations

import argparse
import json
import sys

import paho.mqtt.client as mqtt
import paho.mqtt.publish as publish

from .edge_gateway import COMMAND_TOPIC


def main() -> int:
    p = argparse.ArgumentParser(description="Send a setpoint command directly to the edge gateway")
    p.add_argument("equipment_id")
    p.add_argument("tag")
    p.add_argument("value", type=float)
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=1883)
    args = p.parse_args()
    payload = {"requestId": None, "equipmentId": args.equipment_id, "tag": args.tag, "value": args.value,
               "source": "direct"}
    publish.single(COMMAND_TOPIC, json.dumps(payload), qos=1, hostname=args.host, port=args.port,
                   protocol=mqtt.MQTTv311)
    print(f"sent to {COMMAND_TOPIC}: {payload}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
