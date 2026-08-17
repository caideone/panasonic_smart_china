"""Profile for Panasonic 0820 TB30KL1 bathroom heater devices."""

from __future__ import annotations

from homeassistant.components.climate.const import HVACMode

from ..models import (
    ENTITY_KIND_BATHROOM_HEATER,
    PLATFORM_SELECT,
    PROTOCOL_BATHROOM_HEATER,
    PanasonicEndpoint,
    PanasonicProfile,
)

TB30KL1_PROFILE_ID = "bathroom_heater_0820_tb30kl1"

TB30KL1_HVAC_MAPPING = {
    HVACMode.OFF: 0,
    HVACMode.FAN_ONLY: 6,
}

BATHROOM_HEATER_0820_TB30KL1_PROFILE = PanasonicProfile(
    profile_id=TB30KL1_PROFILE_ID,
    controller_model="TB30KL1",
    name="松下风暖浴霸 (TB30KL1)",
    category_ids=frozenset({"0820"}),
    model_ids=frozenset({"TB30KL1"}),
    ha_platforms=(PLATFORM_SELECT,),
    entity_kind=ENTITY_KIND_BATHROOM_HEATER,
    protocol=PROTOCOL_BATHROOM_HEATER,
    status_endpoint=PanasonicEndpoint(
        path="ADevGetStatusInfoFV54BA1C",
        request_id=52,
        require_results=False,
        required_result_keys=frozenset({"runningMode"}),
        request_params={},
    ),
    set_endpoint=PanasonicEndpoint(
        path="ADevSetStatusInfoFV54BA1C",
        request_id=52,
        require_results=False,
        allow_non_json_response=True,
    ),
    default_hvac_mode=HVACMode.FAN_ONLY,
    hvac_mapping=TB30KL1_HVAC_MAPPING,
    cookie_required=True,
    referer_template=(
        "https://app.psmartcloud.com/ca/cn/0820/{referer_model_path}/index.html"
        "?deviceId={device_id}&devType={referer_dev_type}"
    ),
)
