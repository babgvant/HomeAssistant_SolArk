"""TOU protocol regression tests using synthetic, credential-free settings."""
import asyncio
from copy import deepcopy
import importlib.util
from pathlib import Path
import sys
import types
from unittest.mock import patch

import pytest

ROOT = Path(__file__).parents[1] / "custom_components" / "solark"


def load_api():
    # Load without executing the integration entry point (HA runtime is unnecessary).
    package = types.ModuleType("solark_tou_test")
    package.__path__ = [str(ROOT)]
    with patch.dict(sys.modules, {"solark_tou_test": package}):
        spec = importlib.util.spec_from_file_location("solark_tou_test.api", ROOT / "api.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        tou_module = sys.modules["solark_tou_test.tou"]
    return module, tou_module


API, tou = load_api()


def settings():
    data = {key: 0 for key in tou.TOU_FORM_FIELDS}
    data.update({key: False for key in tou.BOOLEAN_FIELDS})
    data.update({key: 0 for key in tou.BATTERY_FORM_FIELDS if key not in data})
    data.update({f"sellTime{i}": f"{(i-1)*4:02}:00" for i in range(1, 7)})
    data.update({f"cap{i}": 40 for i in range(1, 7)})
    data.update({f"sellTime{i}Pac": 18000 for i in range(1, 7)})
    data.update({f"sellTime{i}Volt": 49 for i in range(1, 7)})
    data.update({"modbusSn": 1, "peakAndVallery": 1, "cap2": 100, "cap3": 100,
                 "cap4": 80, "pvMaxLimit": 19950, "solarMaxSellPower": 23400,
                 "batteryShutdownVolt": 46, "reset": 0})
    data.update({"batteryMaxCurrentCharge": 250, "sdBatteryCurrent": 190,
                 "sdStartCap": 50})
    return data


def api_with_cloud(cloud=None, response=None, secondary=None):
    api = API.SolArkCloudAPI("user", "password", "123", "https://portal.example",
                            "https://api.example", None)
    api.tou_master_serial = "TEST-SERIAL"
    cloud = settings() if cloud is None else cloud
    secondary = {**settings(), "modbusSn": 3} if secondary is None else secondary
    writes = []

    async def request(method, endpoint, data=None):
        target = "SECONDARY" if "/SECONDARY/" in endpoint else "TEST-SERIAL"
        assert endpoint == f"/api/v1/common/setting/{target}/{'read' if method == 'GET' else 'set'}"
        await asyncio.sleep(0)  # Exercise concurrent edits and per-device serialization.
        if method == "GET":
            return {"code": 0, "success": True, "data": deepcopy(secondary if target == "SECONDARY" else cloud)}
        assert target == "TEST-SERIAL"
        writes.append(deepcopy(data))
        return response if response is not None else {"code": 0, "success": True, "data": None}

    api._request = request
    return api, cloud, writes


def test_captured_soc_changes_preserve_work_mode_form():
    async def run():
        api, cloud, writes = api_with_cloud()
        await api.async_set_tou_settings("TEST-SERIAL", {"cap2": 80, "cap3": 85, "cap4": 100})
        await api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85, "cap3": 80})
        assert [body["cap2"] for body in writes] == ["80", "85"]
        assert [body["cap3"] for body in writes] == ["85", "80"]
        assert all(body["cap4"] == "100" for body in writes)
        assert set(writes[0]) == {"sn", *tou.TOU_FORM_FIELDS}
        for key in tou.TOU_FORM_FIELDS:
            if key not in ("cap2", "cap3", "cap4"):
                expected = cloud[key] if key in tou.BOOLEAN_FIELDS else str(cloud[key])
                assert writes[-1][key] == expected
        assert cloud["cap2"] == 100  # Simulated cloud has not caught up.
    asyncio.run(run())


def test_concurrent_edits_do_not_overwrite_each_other():
    async def run():
        api, _, writes = api_with_cloud()
        await asyncio.gather(
            api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85}),
            api.async_set_tou_settings("TEST-SERIAL", {"cap3": 80}),
        )
        assert writes[-1]["cap2"] == "85"
        assert writes[-1]["cap3"] == "80"
    asyncio.run(run())


def test_pending_values_confirm_or_expire():
    async def run():
        api, cloud, _ = api_with_cloud()
        await api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85})
        assert (await api.async_get_tou_settings("TEST-SERIAL"))["cap2"] == "85"
        cloud["cap2"] = 85
        await api.async_get_tou_settings("TEST-SERIAL")
        assert not api._pending_tou
        await api.async_set_tou_settings("TEST-SERIAL", {"cap2": 90})
        api._pending_tou["TEST-SERIAL"] = (0, {"cap2": "90"})
        assert (await api.async_get_tou_settings("TEST-SERIAL"))["cap2"] == 85
        assert not api._pending_tou
    asyncio.run(run())


@pytest.mark.parametrize("changes", [
    {"cap2": -1}, {"cap3": 101}, {"cap1": 1.5}, {"cap1": True},
    {"cap1": float("nan")}, {"cap1": float("inf")}, {"cap7": 50},
    {"sellTime2": "24:00"}, {"sellTime2": "8:00"}, {"sellTime3": "11:60"},
    {"reset": 1}, {"peakAndVallery": "2"}, {},
])
def test_invalid_changes_never_send_a_request(changes):
    api, _, writes = api_with_cloud()
    with pytest.raises(ValueError):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", changes))
    assert writes == []


def test_incomplete_read_never_writes_defaults():
    api, _, writes = api_with_cloud({"cap2": 100})
    with pytest.raises(ValueError, match="Incomplete"):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85}))
    assert writes == []


@pytest.mark.parametrize("response", [{"code": 0, "success": False}, {}, {"code": 1, "success": True}])
def test_rejected_write_does_not_publish_a_success(response):
    api, _, _ = api_with_cloud(response=response)
    with pytest.raises(API.SolArkCloudAPIError):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85}))
    assert not api._pending_tou


def test_time_and_enable_write_preserves_soc():
    async def run():
        api, _, writes = api_with_cloud()
        await api.async_set_tou_settings("TEST-SERIAL", {"sellTime2": "08:30", "peakAndVallery": "0"})
        assert writes[0]["sellTime2"] == "08:30"
        assert writes[0]["peakAndVallery"] == "0"
        assert writes[0]["cap2"] == "100"
    asyncio.run(run())


def test_control_platforms_poll_write_and_handle_unavailable_settings():
    """Exercise TOU and battery entity bindings and read failure isolation."""
    from datetime import time
    from types import SimpleNamespace

    class Coordinator:
        def __init__(self, *args, **kwargs):
            self.data = None
            self.last_update_success = True
            self.listeners = []

        def async_add_listener(self, listener):
            self.listeners.append(listener)
            return lambda: self.listeners.remove(listener)

        def async_set_updated_data(self, data):
            self.data = data
            for listener in list(self.listeners):
                listener()

    class CoordinatorEntity:
        def __init__(self, coordinator):
            self.coordinator = coordinator

        @property
        def available(self):
            return self.coordinator.last_update_success

    def stub(name, **attrs):
        module = types.ModuleType(name)
        module.__dict__.update(attrs)
        return module

    package = stub("solark_tou_test")
    package.__path__ = [str(ROOT)]
    modules = {
        "solark_tou_test": package, "solark_tou_test.api": API,
        "homeassistant.config_entries": stub("config_entries", ConfigEntryAuthFailed=type("AuthFailed", (Exception,), {})),
        "homeassistant.const": stub("const", EntityCategory=SimpleNamespace(CONFIG="config")),
        "homeassistant.exceptions": stub("exceptions", HomeAssistantError=type("HAError", (Exception,), {})),
        "homeassistant.helpers.update_coordinator": stub("update", DataUpdateCoordinator=Coordinator, CoordinatorEntity=CoordinatorEntity),
        "homeassistant.components.number": stub("number", NumberEntity=type("NumberEntity", (), {}), NumberMode=SimpleNamespace(BOX="box")),
        "homeassistant.components.time": stub("time", TimeEntity=type("TimeEntity", (), {})),
        "homeassistant.components.switch": stub("switch", SwitchEntity=type("SwitchEntity", (), {})),
    }
    with patch.dict(sys.modules, modules):
        loaded = {}
        for name in ("tou_entity", "number", "time", "switch"):
            spec = importlib.util.spec_from_file_location(f"solark_tou_test.{name}", ROOT / f"{name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            loaded[name] = module

    async def run():
        secondary = {**settings(), "modbusSn": 3}
        api, cloud, writes = api_with_cloud(secondary=secondary)
        entry = SimpleNamespace(entry_id="test-entry", options={"tou_master_serial": "SECONDARY"},
                                async_on_unload=lambda callback: None)
        # Discovery order must not select the target.
        telemetry = SimpleNamespace(api=api, data={"inverters": {"SECONDARY": {}, "TEST-SERIAL": {}}})
        coordinator = loaded["tou_entity"].SolArkTOUCoordinator(None, entry, telemetry)
        coordinator.data = await coordinator._async_update_data()
        hass = SimpleNamespace(data={"solark": {entry.entry_id: {
            "coordinator": telemetry, "tou_coordinator": coordinator}}})
        entities = []
        for name in ("number", "time", "switch"):
            await loaded[name].async_setup_entry(hass, entry, entities.extend)
        assert len(entities) == 22
        by_key = {entity.key: entity for entity in entities}
        assert all(entity.serial == "TEST-SERIAL" for entity in entities)
        assert set(coordinator.data) == {"TEST-SERIAL"}
        assert len({entity._attr_unique_id for entity in entities}) == 22
        assert all(entity.available for entity in entities)
        assert entities[0]._attr_device_info["identifiers"] == {("solark", "inverter:TEST-SERIAL")}
        await entities[1].async_set_native_value(85)
        assert entities[1].native_value == 85
        await by_key['sellTime2'].async_set_value(time(8, 30))
        assert by_key['sellTime2'].native_value == time(8, 30)
        await by_key['peakAndVallery'].async_turn_off()
        assert by_key['peakAndVallery'].is_on is False
        await by_key['peakAndVallery'].async_turn_on()
        assert by_key['peakAndVallery'].is_on is True
        for slot in range(1, 7):
            entity = by_key[f'time{slot}on']
            await entity.async_turn_on()
            assert entity.is_on is True
            assert writes[-1][f'time{slot}on'] is True
            await entity.async_turn_off()
            assert entity.is_on is False
        assert writes[-1]['cap2'] == '85'
        await by_key['sdChargeOn'].async_turn_on()
        assert by_key['sdChargeOn'].is_on is True
        await by_key['sdStartCap'].async_set_native_value(40)
        await by_key['sdBatteryCurrent'].async_set_native_value(100)
        assert by_key['sdBatteryCurrent'].native_max_value == 250
        assert writes[-1]['sdChargeOn'] == '1'
        assert writes[-1]['sdStartCap'] == '40'
        assert writes[-1]['sdBatteryCurrent'] == '100'
        before = len(writes)
        with pytest.raises(modules["homeassistant.exceptions"].HomeAssistantError):
            await coordinator.async_write("SECONDARY", {"cap2": 50})
        assert len(writes) == before
        with pytest.raises(modules["homeassistant.exceptions"].HomeAssistantError):
            await by_key['sellTime2'].async_set_value(time(8, 30, 15))

        del cloud['batteryEfficiency']
        coordinator.data = await coordinator._async_update_data()
        assert not by_key['sdChargeOn'].available
        assert not by_key['sdStartCap'].available
        assert by_key['cap2'].available
        cloud['batteryEfficiency'] = 99

        # No master, duplicate masters, and unknown roles must not pick the first device.
        cloud["modbusSn"] = 2
        coordinator.data = await coordinator._async_update_data()
        assert coordinator.master_inverters == {}
        assert api.tou_master_serial is None
        cloud["modbusSn"] = "1"
        secondary["modbusSn"] = 1
        assert await coordinator._async_update_data() == {}
        assert coordinator.master_inverters == {}
        secondary["modbusSn"] = 3
        coordinator.data = await coordinator._async_update_data()
        assert coordinator.master_serial == "TEST-SERIAL"
        assert all(entity.available for entity in entities)

        # Discovery can recover after platform setup, without a reload or duplicates.
        coordinator.master_serial = None
        late_entities = []
        await loaded["number"].async_setup_entry(hass, entry, late_entities.extend)
        assert late_entities == []
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        assert len(late_entities) == 8
        coordinator.async_set_updated_data(await coordinator._async_update_data())
        assert len(late_entities) == 8

        secondary["modbusSn"] = None
        assert await coordinator._async_update_data() == {}
        assert coordinator.master_serial is None
        secondary["modbusSn"] = 3
        original_read = api.async_get_tou_settings

        async def secondary_unreadable(serial):
            if serial == "SECONDARY":
                raise API.SolArkCloudAPIError("Forbidden")
            return await original_read(serial)

        api.async_get_tou_settings = secondary_unreadable
        assert await coordinator._async_update_data() == {}
        assert coordinator.master_serial is None
        api.async_get_tou_settings = original_read
        coordinator.data = await coordinator._async_update_data()
        assert coordinator.master_serial == "TEST-SERIAL"

        async def forbidden(serial):
            raise API.SolArkCloudAPIError("Forbidden")

        api.async_get_tou_settings = forbidden
        coordinator.data = await coordinator._async_update_data()
        assert all(not entity.available for entity in entities)
        assert coordinator.master_inverters == {}
        assert api.tou_master_serial is None
    asyncio.run(run())


@pytest.mark.parametrize("master,target", [(None, "TEST-SERIAL"), ("TEST-SERIAL", "SECONDARY")])
def test_api_rejects_nonmaster_before_any_request(master, target):
    api, _, writes = api_with_cloud()
    api.tou_master_serial = master
    with pytest.raises(API.SolArkCloudAPIError, match="master"):
        asyncio.run(api.async_set_tou_settings(target, {"cap2": 50}))
    assert writes == []


@pytest.mark.parametrize("position", [2, "3", None, True, 0, "unknown"])
def test_fresh_secondary_position_blocks_write(position):
    api, cloud, writes = api_with_cloud()
    cloud["modbusSn"] = position
    with pytest.raises(API.SolArkCloudAPIError, match="position 1"):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", {"cap2": 50}))
    assert writes == []
    assert api.tou_master_serial is None


@pytest.mark.parametrize("changes", [
    {"time0on": True}, {"time7on": True}, {"time3on": "true"},
    {"time4on": 2}, {"sdChargeOn": "yes"}, {"sdStartCap": 101},
    {"sdStartCap": True}, {"sdBatteryCurrent": -1},
    {"sdBatteryCurrent": 1.5}, {"sdBatteryCurrent": True},
    {"sdBatteryCurrent": float("nan")}, {"sdBatteryCurrent": float("inf")},
    {"sdChargeOn": 1, "time4on": True},
])
def test_invalid_grid_charge_changes(changes):
    api, _, writes = api_with_cloud()
    with pytest.raises(ValueError):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", changes))
    assert writes == []


def test_captured_grid_charge_sequence_and_boolean_readback():
    async def run():
        api, cloud, writes = api_with_cloud()
        cloud["time4on"] = True
        for changes in ({"time3on": True}, {"time3on": False, "time4on": False},
                        {"time4on": True}):
            await api.async_set_tou_settings("TEST-SERIAL", changes)
        assert [body["time3on"] for body in writes] == [True, False, False]
        assert [body["time4on"] for body in writes] == [True, False, True]
        assert all(body["genTime4on"] is False for body in writes)
        assert all("sdChargeOn" not in body for body in writes)
        cloud.update({"time3on": False, "time4on": True})
        await api.async_get_tou_settings("TEST-SERIAL")
        assert not api._pending_tou
    asyncio.run(run())


def test_battery_form_and_concurrent_tou_edits_are_isolated():
    async def run():
        api, cloud, writes = api_with_cloud()
        await asyncio.gather(
            api.async_set_tou_settings("TEST-SERIAL", {"sdChargeOn": True}),
            api.async_set_tou_settings("TEST-SERIAL", {"sdStartCap": 40}),
            api.async_set_tou_settings("TEST-SERIAL", {"sdBatteryCurrent": 100}),
            api.async_set_tou_settings("TEST-SERIAL", {"time4on": True}),
        )
        body = writes[2]
        assert set(body) == {"sn", *tou.BATTERY_FORM_FIELDS}
        assert body["sdChargeOn"] == "1"
        assert body["sdStartCap"] == "40"
        assert body["sdBatteryCurrent"] == "100"
        assert "sdStartVol" not in body
        for key in tou.BATTERY_FORM_FIELDS:
            if key not in tou.BATTERY_CONTROL_FIELDS:
                assert body[key] == str(cloud[key])
        assert writes[-1]["time4on"] is True
        assert set(writes[-1]) == {"sn", *tou.TOU_FORM_FIELDS}
        cloud.update({"sdChargeOn": 1, "sdStartCap": 40, "sdBatteryCurrent": 100,
                      "time4on": True})
        await api.async_get_tou_settings("TEST-SERIAL")
        assert not api._pending_tou
    asyncio.run(run())


def test_battery_write_requires_complete_form_and_current_limit():
    async def run():
        api, cloud, writes = api_with_cloud()
        with pytest.raises(ValueError, match="exceeds"):
            await api.async_set_tou_settings("TEST-SERIAL", {"sdBatteryCurrent": 251})
        del cloud["batteryEfficiency"]
        with pytest.raises(ValueError, match="battery settings form"):
            await api.async_set_tou_settings("TEST-SERIAL", {"sdChargeOn": True})
        assert writes == []
        await api.async_set_tou_settings("TEST-SERIAL", {"cap2": 85})
        assert writes[0]["cap2"] == "85"
    asyncio.run(run())


@pytest.mark.parametrize("changes", [{"sdChargeOn": True}, {"time4on": True}])
def test_grid_charge_rejects_secondary_writes(changes):
    api, cloud, writes = api_with_cloud()
    cloud["modbusSn"] = 2
    with pytest.raises(API.SolArkCloudAPIError, match="position 1"):
        asyncio.run(api.async_set_tou_settings("TEST-SERIAL", changes))
    assert writes == []
