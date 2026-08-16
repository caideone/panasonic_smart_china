"""Select entities for Panasonic Smart China."""

from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.select import SelectEntity
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.device_registry import DeviceInfo

from .api import PanasonicApiAuthError, PanasonicApiClient, PanasonicApiError
from .const import (
    CONF_CATEGORY,
    CONF_CONTROLLER_MODEL,
    CONF_DEVICE_ID,
    CONF_DEVICE_MODEL,
    CONF_DEVICE_NAME,
    CONF_DEVICES,
    CONF_ENABLED,
    CONF_PROFILE_ID,
    CONF_SSID,
    CONF_TOKEN,
    CONF_USR_ID,
    DOMAIN,
)
from .models import ENTITY_KIND_BATHROOM_HEATER, PLATFORM_SELECT
from .profiles import find_profile_for_device_config
from .token import DeviceTokenError, generate_device_token

_LOGGER = logging.getLogger(__name__)
SCAN_INTERVAL = timedelta(seconds=3)

OPTION_OFF = "待机"
OPTION_HEAT = "取暖"
OPTION_FAN = "换气"
OPTION_COOL_DRY = "凉干燥"
OPTION_HEAT_DRY = "热干燥"
OPTION_LIGHT_OFF = "关闭"
OPTION_LIGHT_WARM = "暖光"
OPTION_LIGHT_COOL = "冷光"
OPTION_TIMER_CONTINUOUS = "连续"
OPTION_TIMER_15_MIN = "15分钟"
OPTION_TIMER_30_MIN = "30分钟"
OPTION_TIMER_1_HOUR = "1小时"
OPTION_TIMER_3_HOUR = "3小时"
OPTION_TIMER_6_HOUR = "6小时"

MODE_BY_OPTION = {
    OPTION_OFF: 32,
    OPTION_HEAT: 37,
    OPTION_FAN: 38,
    OPTION_COOL_DRY: 40,
    OPTION_HEAT_DRY: 42,
}
OPTION_BY_MODE = {value: key for key, value in MODE_BY_OPTION.items()}
WRITABLE_MODE_BY_STATUS_MODE = {
    0x00: 32,
    0x20: 32,
    0x30: 32,
    0x15: 37,
    0x25: 37,
    0x35: 37,
    0x16: 38,
    0x26: 38,
    0x36: 38,
    0x17: 38,
    0x27: 38,
    0x37: 38,
    0x18: 40,
    0x28: 40,
    0x38: 40,
    0x19: 40,
    0x29: 40,
    0x39: 40,
    0x1A: 42,
    0x2A: 42,
    0x3A: 42,
    0x1B: 42,
    0x2B: 42,
    0x3B: 42,
}

LIGHT_BY_OPTION = {
    OPTION_LIGHT_OFF: 0,
    OPTION_LIGHT_WARM: 1,
    OPTION_LIGHT_COOL: 2,
}
OPTION_BY_LIGHT = {value: key for key, value in LIGHT_BY_OPTION.items()}

TIMER_BY_OPTION = {
    OPTION_TIMER_CONTINUOUS: 35,
    OPTION_TIMER_15_MIN: 3,
    OPTION_TIMER_30_MIN: 6,
    OPTION_TIMER_1_HOUR: 12,
    OPTION_TIMER_3_HOUR: 16,
    OPTION_TIMER_6_HOUR: 22,
}
OPTION_BY_TIMER = {value: key for key, value in TIMER_BY_OPTION.items()}
DEFAULT_TIMER_VALUE = TIMER_BY_OPTION[OPTION_TIMER_30_MIN]
LAST_TIMER_BY_DEVICE: dict[str, int] = {}


async def async_setup_entry(hass, entry, async_add_entities):
    """Create select entities for enabled devices under an account entry."""
    runtime = hass.data.get(DOMAIN, {}).get(entry.entry_id, {})
    client = runtime.get("client") or PanasonicApiClient(hass, entry.data.get(CONF_SSID))
    devices = entry.data.get(CONF_DEVICES, {})

    entities = []
    for device_id, device_config in devices.items():
        if not device_config.get(CONF_ENABLED, True):
            continue

        profile = find_profile_for_device_config(
            profile_id=device_config.get(CONF_PROFILE_ID),
            controller_model=device_config.get(CONF_CONTROLLER_MODEL),
            category_id=device_config.get(CONF_CATEGORY),
        )
        if (
            not profile
            or PLATFORM_SELECT not in profile.ha_platforms
            or profile.entity_kind != ENTITY_KIND_BATHROOM_HEATER
        ):
            continue

        entity_config = {
            **entry.data,
            **device_config,
            CONF_DEVICE_ID: device_id,
        }
        name = device_config.get(CONF_DEVICE_NAME, device_id)
        entities.extend(
            (
                PanasonicBathroomHeaterModeSelect(entity_config, name, profile, client),
                PanasonicBathroomHeaterLightSelect(entity_config, name, profile, client),
                PanasonicBathroomHeaterTimerSelect(entity_config, name, profile, client),
            )
        )

    async_add_entities(entities, update_before_add=True)


class PanasonicBathroomHeaterModeSelect(SelectEntity):
    """Mode select for Panasonic 0820 bathroom heater devices."""

    _attr_options = list(MODE_BY_OPTION)

    def __init__(self, config, name, profile, client):
        self._usr_id = config[CONF_USR_ID]
        self._device_id = config[CONF_DEVICE_ID]
        try:
            self._token = generate_device_token(self._device_id)
        except DeviceTokenError as err:
            _LOGGER.warning(
                "Using stored token for %s because token regeneration failed: %s",
                self._device_id,
                err,
            )
            self._token = config[CONF_TOKEN]
        self._model = config.get(CONF_DEVICE_MODEL) or config.get(CONF_CONTROLLER_MODEL)
        self._profile = profile
        self._api = client
        self._attr_name = f"{name} 模式"
        self._attr_unique_id = f"panasonic_smart_china_{self._device_id}_mode"
        self._attr_current_option = OPTION_OFF
        self._attr_available = False

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name.removesuffix(" 模式"),
            manufacturer="Panasonic",
            model=self._model,
        )

    async def async_update(self):
        try:
            status = await self._api.get_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired for %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            self._attr_available = False
            _LOGGER.warning("Fetch status failed for %s: %s", self._device_id, err)
            return

        mode = _writable_running_mode(_as_int(status.get("runningMode"), 32))
        self._attr_current_option = OPTION_BY_MODE.get(mode, OPTION_OFF)
        self._attr_available = True

    async def async_select_option(self, option: str):
        if option not in MODE_BY_OPTION:
            _LOGGER.warning("Unsupported bathroom heater mode %s for %s", option, self._device_id)
            return

        running_mode = MODE_BY_OPTION[option]
        changes = {"runningMode": running_mode}
        if running_mode != 32:
            changes["timeSet"] = LAST_TIMER_BY_DEVICE.get(
                self._device_id,
                DEFAULT_TIMER_VALUE,
            )
        params = _build_bathroom_heater_payload(self._model, changes)
        self._attr_current_option = option
        self._attr_available = True
        self.async_write_ha_state()
        try:
            await self._api.set_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                params,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired while setting %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            _LOGGER.error("Set failed for %s: %s", self._device_id, err)
            return

        self.async_write_ha_state()

class PanasonicBathroomHeaterLightSelect(SelectEntity):
    """Light select for Panasonic 0820 bathroom heater devices."""

    _attr_options = list(LIGHT_BY_OPTION)

    def __init__(self, config, name, profile, client):
        self._usr_id = config[CONF_USR_ID]
        self._device_id = config[CONF_DEVICE_ID]
        try:
            self._token = generate_device_token(self._device_id)
        except DeviceTokenError as err:
            _LOGGER.warning(
                "Using stored token for %s because token regeneration failed: %s",
                self._device_id,
                err,
            )
            self._token = config[CONF_TOKEN]
        self._model = config.get(CONF_DEVICE_MODEL) or config.get(CONF_CONTROLLER_MODEL)
        self._profile = profile
        self._api = client
        self._attr_name = f"{name} 灯光"
        self._attr_unique_id = f"panasonic_smart_china_{self._device_id}_light"
        self._attr_current_option = OPTION_LIGHT_OFF
        self._attr_available = False

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name.removesuffix(" 灯光"),
            manufacturer="Panasonic",
            model=self._model,
        )

    async def async_update(self):
        try:
            status = await self._api.get_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired for %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            self._attr_available = False
            _LOGGER.warning("Fetch status failed for %s: %s", self._device_id, err)
            return

        light = _as_int(status.get("lightSet"), 0)
        self._attr_current_option = OPTION_BY_LIGHT.get(light, OPTION_LIGHT_OFF)
        self._attr_available = True

    async def async_select_option(self, option: str):
        if option not in LIGHT_BY_OPTION:
            _LOGGER.warning("Unsupported bathroom heater light %s for %s", option, self._device_id)
            return

        params = _build_bathroom_heater_payload(
            self._model,
            {
                "runningMode": 255,
                "lightSet": LIGHT_BY_OPTION[option],
            },
        )
        self._attr_current_option = option
        self._attr_available = True
        self.async_write_ha_state()
        try:
            await self._api.set_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                params,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired while setting %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            _LOGGER.error("Set failed for %s: %s", self._device_id, err)
            return

        self.async_write_ha_state()


class PanasonicBathroomHeaterTimerSelect(SelectEntity):
    """Timer select for Panasonic 0820 bathroom heater devices."""

    _attr_options = list(TIMER_BY_OPTION)

    def __init__(self, config, name, profile, client):
        self._usr_id = config[CONF_USR_ID]
        self._device_id = config[CONF_DEVICE_ID]
        try:
            self._token = generate_device_token(self._device_id)
        except DeviceTokenError as err:
            _LOGGER.warning(
                "Using stored token for %s because token regeneration failed: %s",
                self._device_id,
                err,
            )
            self._token = config[CONF_TOKEN]
        self._model = config.get(CONF_DEVICE_MODEL) or config.get(CONF_CONTROLLER_MODEL)
        self._profile = profile
        self._api = client
        self._attr_name = f"{name} 定时"
        self._attr_unique_id = f"panasonic_smart_china_{self._device_id}_timer"
        self._attr_current_option = OPTION_TIMER_CONTINUOUS
        self._attr_extra_state_attributes = {}
        self._attr_available = False

    @property
    def device_info(self):
        return DeviceInfo(
            identifiers={(DOMAIN, self._device_id)},
            name=self._attr_name.removesuffix(" 定时"),
            manufacturer="Panasonic",
            model=self._model,
        )

    async def async_update(self):
        try:
            status = await self._api.get_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired for %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            self._attr_available = False
            _LOGGER.warning("Fetch status failed for %s: %s", self._device_id, err)
            return

        timer = _as_int(status.get("timeSet"), 0)
        if timer in OPTION_BY_TIMER:
            LAST_TIMER_BY_DEVICE[self._device_id] = timer
        self._attr_current_option = OPTION_BY_TIMER.get(timer, f"未知({timer})")
        self._attr_extra_state_attributes = {
            "raw_time_set": status.get("timeSet"),
            "raw_running_mode": status.get("runningMode"),
            "raw_status": status,
        }
        self._attr_available = True

    async def async_select_option(self, option: str):
        if option not in TIMER_BY_OPTION:
            _LOGGER.warning("Unsupported bathroom heater timer %s for %s", option, self._device_id)
            return

        try:
            status = await self._api.get_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired for %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            self._attr_available = False
            _LOGGER.warning("Fetch status failed for %s: %s", self._device_id, err)
            return

        running_mode = _writable_running_mode(_as_int(status.get("runningMode"), 32))
        params = _build_bathroom_heater_payload(
            self._model,
            {
                "runningMode": running_mode,
                "timeSet": TIMER_BY_OPTION[option],
            },
        )
        self._attr_current_option = option
        LAST_TIMER_BY_DEVICE[self._device_id] = TIMER_BY_OPTION[option]
        self._attr_available = True
        self.async_write_ha_state()
        try:
            await self._api.set_device_status(
                self._profile,
                self._usr_id,
                self._device_id,
                self._token,
                params,
                self._model,
            )
        except PanasonicApiAuthError as err:
            self._attr_available = False
            _LOGGER.error("Panasonic session expired while setting %s: %s", self._device_id, err)
            raise ConfigEntryAuthFailed("Panasonic Smart China session expired") from err
        except PanasonicApiError as err:
            _LOGGER.error("Set failed for %s: %s", self._device_id, err)
            return

        self.async_write_ha_state()


def _build_bathroom_heater_payload(model, changes):
    diy_next_step_no = 5 if model and model.upper() == "RB20VD1" else 2
    params = {
        "runningMode": 32,
        "warmTempset": 255,
        "windDirectionSet": 255,
        "windKindSet": 255,
        "timeSet": 255,
        "lightSet": 255,
        "gasCheckSet": 255,
        "DIYnextRunningMode": 255,
        "DIYnextWarmTempset": 255,
        "DIYnextwindDirectionSet": 255,
        "DIYnextwindKindSet": 255,
        "DIYnextTimeSet": 255,
        "DIYnextStepNo": diy_next_step_no,
    }
    params.update(changes)
    return params


def _writable_running_mode(mode):
    return WRITABLE_MODE_BY_STATUS_MODE.get(mode, mode)


def _as_int(value, default=None):
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
