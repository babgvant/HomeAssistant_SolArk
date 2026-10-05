"""Options-flow checks with HA's read-only config entry contract."""
from __future__ import annotations

import asyncio
import importlib.util
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch


ROOT = Path(__file__).parents[1] / "custom_components" / "solark"


class OptionsFlow:
    @property
    def config_entry(self):
        return self.hass.config_entries.async_get_known_entry(self.handler)

    def async_show_form(self, **kwargs):
        return {"type": "form", **kwargs}

    def async_create_entry(self, **kwargs):
        return {"type": "create_entry", **kwargs}


def load_flow():
    """Import production flow without the platform-specific HA runtime."""
    class ConfigFlow:
        def __init_subclass__(cls, **kwargs):
            pass

    modules = {}
    for name in (
        "homeassistant", "homeassistant.config_entries",
        "homeassistant.data_entry_flow", "homeassistant.helpers",
        "homeassistant.helpers.aiohttp_client", "custom_components",
        "custom_components.solark", "custom_components.solark.api",
        "custom_components.solark.discovery",
    ):
        modules[name] = types.ModuleType(name)
    modules["custom_components"].__path__ = [str(ROOT.parent)]
    modules["custom_components.solark"].__path__ = [str(ROOT)]
    entries = modules["homeassistant.config_entries"]
    entries.ConfigFlow = ConfigFlow
    entries.OptionsFlow = OptionsFlow
    modules["homeassistant"].config_entries = entries
    modules["homeassistant.data_entry_flow"].FlowResult = dict
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = Mock()
    api = modules["custom_components.solark.api"]
    api.SolArkCloudAPI = Mock()
    api.SolArkCloudAPIError = type("APIError", (Exception,), {})
    api.SolArkCloudAuthenticationError = type("AuthError", (Exception,), {})
    api._redact_secret_text = str
    modules["custom_components.solark.discovery"].discover_api_url = AsyncMock()
    with patch.dict(sys.modules, modules):
        spec = importlib.util.spec_from_file_location(
            "custom_components.solark.config_flow", ROOT / "config_flow.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


class OptionsFlowTests(unittest.TestCase):
    def make_flow(self):
        module = load_flow()
        entry = types.SimpleNamespace(
            data={"scan_interval": 30},
            options={"scan_interval": 60, "diagnostic_capture": True},
        )
        # Construction must succeed before HA binds hass and handler.
        flow = module.SolArkConfigFlow.async_get_options_flow(entry)
        flow.handler = "test_entry"
        flow.hass = types.SimpleNamespace(config_entries=types.SimpleNamespace(
            async_get_known_entry=Mock(return_value=entry),
            async_update_entry=Mock(),
        ))
        return module, entry, flow

    def test_options_open_with_read_only_entry_and_saved_defaults(self):
        _, entry, flow = self.make_flow()
        result = asyncio.run(flow.async_step_init())
        self.assertEqual(result["type"], "form")
        defaults = result["data_schema"]({})
        self.assertEqual(defaults["scan_interval"], 60)
        self.assertTrue(defaults["diagnostic_capture"])
        self.assertIs(flow.config_entry, entry)

    def test_options_save_updates_connection_and_capture_settings(self):
        module, entry, flow = self.make_flow()
        with patch.object(module, "_resolve_for_flow", AsyncMock(return_value=(
            "https://www.solarkcloud.com", "https://p2.api.solarkcloud.com", False
        ))):
            result = asyncio.run(flow.async_step_init({
                "scan_interval": 90, "diagnostic_capture": True,
                "diagnostic_drop_percent": 30, "auto_discover_api": False,
            }))
        self.assertEqual(result["type"], "create_entry")
        self.assertEqual(result["data"]["scan_interval"], 90)
        self.assertTrue(result["data"]["diagnostic_capture"])
        self.assertEqual(result["data"]["diagnostic_drop_percent"], 30)
        flow.hass.config_entries.async_update_entry.assert_called_once()
        self.assertIs(flow.hass.config_entries.async_update_entry.call_args.args[0], entry)
