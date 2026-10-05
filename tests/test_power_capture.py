"""Unattended capture limits, sign handling and snapshot isolation."""
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("capture", Path(__file__).parents[1] / "custom_components/solark/capture.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def sample(pv=10000, battery=-5000):
    return {"plant": {"values": {"pv_power": pv, "battery_power": battery}},
            "aggregation": {"pv_power": {"aggregation_method": "sum_per_inverter",
                            "expected_inverters": 1, "contributing_inverters": ["private_serial"]}}}


class CaptureTests(unittest.TestCase):
    def test_raw_plant_dip_is_captured_while_selected_pv_is_cached(self):
        capture = module.PowerCapture({"diagnostic_capture": True})
        data = sample()
        data["debug_diagnostics"] = {"plant": {"plant_flow": {"raw_pv_power": 10000}}}
        capture.record(data, {})
        data["debug_diagnostics"]["plant"]["plant_flow"]["raw_pv_power"] = 5000
        capture.record(data, {})
        self.assertIn("candidate_plant_flow_dip:pv_power", capture.events[0]["triggers"][0]["reasons"])
        self.assertEqual(capture.events[0]["samples"][0]["plant_flow_powers"]["pv_power"], 10000)

    def test_disabled_and_bounded_with_before_after(self):
        off = module.PowerCapture({})
        off.record(sample(), {})
        self.assertEqual(off.export()["rolling_samples"], [])
        capture = module.PowerCapture({"diagnostic_capture": True, "diagnostic_pre_samples": 2,
                                       "diagnostic_post_samples": 2, "diagnostic_event_limit": 2})
        for _ in range(4): capture.record(sample(), {})
        capture.record(sample(5000, -2000), {})
        capture.record(sample(), {})
        capture.record(sample(), {})
        exported = capture.export()
        self.assertTrue(exported["events"][0]["complete"])
        self.assertEqual(len(exported["events"][0]["samples"]), 5)
        self.assertIn("candidate_dip:battery_power", exported["events"][0]["triggers"][0]["reasons"])
        for _ in range(20): capture.record(sample(0), {})
        self.assertLessEqual(len(capture.export()["events"]), 2)
        self.assertNotIn("private_serial", str(exported))
        exported["events"].clear()
        self.assertTrue(capture.export()["events"])

    def test_persistent_failures_never_extend_event_forever(self):
        capture = module.PowerCapture({"diagnostic_capture": True, "diagnostic_post_samples": 2})
        data = sample()
        data["endpoint_errors"] = {"inverters": "SolArkCloudAPIError"}
        for _ in range(100): capture.record(data, {})
        self.assertTrue(capture.export()["events"][0]["complete"])
        self.assertLessEqual(max(len(e["samples"]) for e in capture.events), 13)
