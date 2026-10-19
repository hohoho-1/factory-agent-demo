import json
import unittest

from asyncua import Client

from plc.edge_gateway import browse_line, build_telemetry, parse_command, write_setpoint
from plc.process import InterlockError, LineProcess
from plc.virtual_plc import VirtualPlc


def run_scans(process: LineProcess, n: int) -> dict:
    values = {}
    for _ in range(n):
        values = process.scan()
    return values


class LineProcessTest(unittest.TestCase):
    def test_lower_speed_setpoint_reduces_vibration(self):
        p = LineProcess()
        p.inject("mixer_resonance")
        high = run_scans(p, 40)["MIXER-01"]["vibration"]
        self.assertGreater(high, 4.5)  # 공진으로 경고 수준

        p.write_setpoint("MIXER-01", "speed_sp", 51.0)
        after = run_scans(p, 10)["MIXER-01"]
        self.assertEqual(after["speed"], 51.0)  # 실제 회전수가 설정값을 따라감
        self.assertLess(after["vibration"], 4.275)  # 알람 해제 기준(4.5 의 95%) 아래

    def test_tank_temperature_follows_setpoint(self):
        p = LineProcess()
        p.inject("tank_sp_misentry")
        self.assertGreater(run_scans(p, 40)["TANK-02"]["temperature"], 50)
        p.write_setpoint("TANK-02", "temp_sp", 40.0)
        self.assertLess(run_scans(p, 40)["TANK-02"]["temperature"], 45)

    def test_interlock_rejects_out_of_range_and_large_steps(self):
        p = LineProcess()
        p.scan()
        with self.assertRaises(InterlockError) as e:
            p.write_setpoint("MIXER-01", "speed_sp", 95.0)
        self.assertEqual(e.exception.code, "BadOutOfRange")
        with self.assertRaises(InterlockError) as e:
            p.write_setpoint("MIXER-01", "speed_sp", 35.0)  # 60 → 35 는 한 번에 20rpm 초과
        self.assertIn("한 번에", e.exception.message)
        with self.assertRaises(InterlockError):
            p.write_setpoint("MIXER-01", "vibration", 1.0)  # 공정값은 쓸 수 없다
        self.assertEqual(p.setpoints[("MIXER-01", "speed_sp")], 60.0)

    def test_interlock_blocks_raise_in_dangerous_condition(self):
        p = LineProcess()
        p.write_setpoint("MIXER-01", "speed_sp", 50.0)
        p.scan()
        p.last["MIXER-01"]["vibration"] = 8.0  # 진동 위험
        with self.assertRaises(InterlockError) as e:
            p.write_setpoint("MIXER-01", "speed_sp", 55.0)
        self.assertEqual(e.exception.code, "BadInvalidState")
        p.write_setpoint("MIXER-01", "speed_sp", 45.0)  # 낮추는 방향은 허용
        self.assertEqual(p.setpoints[("MIXER-01", "speed_sp")], 45.0)


class GatewayMessageTest(unittest.TestCase):
    def test_parse_command(self):
        cmd = parse_command(json.dumps({"requestId": 3, "equipmentId": "MIXER-01", "tag": "speed_sp",
                                        "value": "50"}).encode())
        self.assertEqual(cmd["value"], 50.0)
        with self.assertRaises(ValueError):
            parse_command(b'{"equipmentId": "MIXER-01"}')


class OpcUaRoundTripTest(unittest.IsolatedAsyncioTestCase):
    """가상 PLC 서버를 띄우고 게이트웨이 함수로 browse · 쓰기 · 인터록 거부를 확인한다."""

    URL = "opc.tcp://127.0.0.1:48410/factory/line1/"

    async def asyncSetUp(self):
        self.plc = VirtualPlc(endpoint=self.URL)
        await self.plc.start()

    async def asyncTearDown(self):
        await self.plc.stop()

    async def test_browse_write_and_interlock(self):
        async with Client(self.URL) as client:
            line = await browse_line(client)
            mixer = line["MIXER-01"]
            self.assertEqual(mixer.type, "MIXER")
            self.assertEqual(mixer.tags["speed_sp"].role, "SP")
            self.assertEqual(mixer.tags["vibration"].unit, "mm/s")
            self.assertEqual(set(line), {"TANK-01", "TANK-02", "MIXER-01", "FILLER-01"})

            telemetry = build_telemetry(mixer, {"vibration": 2.512, "speed_sp": 60.0}, None)
            self.assertEqual(telemetry["metrics"], {"vibration": 2.51, "speed_sp": 60.0})
            self.assertEqual(telemetry["units"]["speed_sp"], "rpm")

            ok = await write_setpoint(mixer, {"requestId": 1, "equipmentId": "MIXER-01", "tag": "speed_sp",
                                              "value": 50.0})
            self.assertEqual(ok["status"], "APPLIED")
            self.assertEqual((ok["before"], ok["after"]), (60.0, 50.0))
            self.assertEqual(self.plc.process.setpoints[("MIXER-01", "speed_sp")], 50.0)

            rejected = await write_setpoint(mixer, {"requestId": 2, "equipmentId": "MIXER-01", "tag": "speed_sp",
                                                    "value": 95.0})
            self.assertEqual(rejected["status"], "INTERLOCKED")
            self.assertEqual(rejected["code"], "BadOutOfRange")
            self.assertIn("허용 범위", rejected["message"])
            self.assertEqual(rejected["after"], 50.0)

            not_sp = await write_setpoint(mixer, {"equipmentId": "MIXER-01", "tag": "vibration", "value": 1.0})
            self.assertEqual(not_sp["code"], "BadNotWritable")


if __name__ == "__main__":
    unittest.main()
