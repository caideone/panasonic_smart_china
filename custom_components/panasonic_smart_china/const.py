from .profiles import (
    SUPPORTED_CONTROLLERS,
    find_profiles_for_category,
    find_profiles_for_device,
)
from .profiles.ducted_ac_0900 import FAN_MAX, FAN_MIN, FAN_MUTE

DOMAIN = "panasonic_smart_china"

CONF_USR_ID = "usrId"
CONF_USERNAME = "username"
CONF_DEVICE_ID = "deviceId"
CONF_TOKEN = "token"
CONF_SSID = "SSID"
CONF_SENSOR_ID = "sensor_entity_id"
CONF_CONTROLLER_MODEL = "controller_model"
CONF_FAMILY_ID = "familyId"
CONF_REAL_FAMILY_ID = "realFamilyId"
CONF_FAMILY_NAME = "familyName"
CONF_DEVICES = "devices"
CONF_DEVICE_NAME = "deviceName"
CONF_DEVICE_MODEL = "device_model"
CONF_CATEGORY = "category"
CONF_ENABLED = "enabled"
CONF_PROFILE_ID = "profile_id"
CONF_HA_PLATFORMS = "ha_platforms"
CONF_ENTITY_KIND = "entity_kind"


def find_controllers_for_category(category_id):
    """根据设备 ID 中的 category_id 查找匹配的控制器列表"""
    profiles = find_profiles_for_category(category_id)
    return {
        profile.controller_model: profile
        for profile in profiles.values()
    }


def find_controllers_for_device(category_id, model_values=None):
    """根据 category_id 和设备型号候选值查找匹配的控制器列表"""
    profiles = find_profiles_for_device(category_id, model_values)
    return {
        profile.controller_model: profile
        for profile in profiles.values()
    }


def extract_category_from_device_id(device_id):
    """从 deviceId (格式: MAC_CATEGORY_SUFFIX) 中提取 category_id"""
    parts = device_id.split('_', 2)
    if len(parts) >= 2:
        return parts[1]
    return None
