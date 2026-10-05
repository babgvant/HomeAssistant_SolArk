"""Download diagnostics must not reintroduce aggregation serial numbers."""
import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch


class DiagnosticsPrivacyTests(unittest.TestCase):
    def test_aggregation_contributors_are_positional_labels(self):
        root = Path(__file__).parents[1] / "custom_components/solark"
        package = types.ModuleType("custom_components.solark")
        package.__path__ = [str(root)]
        redaction = types.ModuleType("homeassistant.components.diagnostics")
        redaction.async_redact_data = lambda data, keys: {k: "REDACTED" if k in keys else v for k, v in data.items()}
        entries = types.ModuleType("homeassistant.config_entries")
        entries.ConfigEntry = object
        core = types.ModuleType("homeassistant.core")
        core.HomeAssistant = object
        modules = {"custom_components.solark": package,
                   "homeassistant.components.diagnostics": redaction,
                   "homeassistant.config_entries": entries, "homeassistant.core": core}
        with patch.dict(sys.modules, modules):
            spec = importlib.util.spec_from_file_location("custom_components.solark.diagnostics", root / "diagnostics.py")
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
        data = {"inverters": {"private_serial": {}}, "aggregation": {
            "pv_power": {"contributing_inverters": ["private_serial"]}}}
        coordinator = types.SimpleNamespace(data=data, last_update_success=True,
                                            power_capture=types.SimpleNamespace(export=lambda: {"enabled": False}))
        entry = types.SimpleNamespace(data={"username": "private_user", "password": "private_password"},
                                      options={}, entry_id="test")
        hass = types.SimpleNamespace(data={"solark": {"test": {"coordinator": coordinator}}})
        result = asyncio.run(module.async_get_config_entry_diagnostics(hass, entry))
        self.assertNotIn("private_", str(result))
        self.assertEqual(result["coordinator"]["aggregation"]["pv_power"]["contributing_inverters"], ["inverter_1"])
        self.assertEqual(data["aggregation"]["pv_power"]["contributing_inverters"], ["private_serial"])
