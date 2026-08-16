"""Panasonic Smart China cloud API client."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any

import async_timeout
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .models import PanasonicEndpoint, PanasonicProfile

BASE_URL = "https://app.psmartcloud.com/App"
URL_LOGIN = f"{BASE_URL}/UsrLogin"
URL_GET_DEV = f"{BASE_URL}/UsrGetBindDevInfo"
URL_GET_TOKEN = f"{BASE_URL}/UsrGetToken"

AUTH_ERROR_CODES = {"3003", "3004", "403", "4102"}
SUCCESS_ERROR_CODES = {None, "", 0, "0", "0000"}


class PanasonicApiError(Exception):
    """Base exception for Panasonic cloud API failures."""


class PanasonicApiAuthError(PanasonicApiError):
    """Raised when the Panasonic session is expired or invalid."""


class PanasonicApiResponseError(PanasonicApiError):
    """Raised when the Panasonic cloud returns an invalid response."""


@dataclass(frozen=True)
class FamilyInfo:
    """Panasonic account family/home information."""

    family_id: str
    real_family_id: str
    name: str | None = None


@dataclass(frozen=True)
class LoginResult:
    """Successful login result."""

    usr_id: str
    ssid: str
    family_id: str
    real_family_id: str
    family_name: str | None
    families: tuple[FamilyInfo, ...]
    devices: dict[str, dict[str, Any]]


class PanasonicApiClient:
    """Small async client for the reverse engineered Panasonic cloud API."""

    def __init__(self, hass: HomeAssistant, ssid: str | None = None) -> None:
        self._hass = hass
        self.ssid = ssid

    async def authenticate(self, username: str, password: str) -> LoginResult:
        """Run the full login flow and return the account devices."""
        token_res = await self._post(
            URL_GET_TOKEN,
            {
                "id": 1,
                "uiVersion": 4.0,
                "params": {"usrId": username},
            },
            headers=self._app_headers(),
            require_results=True,
        )
        token_start = token_res["results"].get("token")
        if not token_start:
            raise PanasonicApiResponseError("GetToken response did not include token")

        pwd_md5 = hashlib.md5(password.encode()).hexdigest().upper()
        inter_md5 = hashlib.md5(f"{pwd_md5}{username}".encode()).hexdigest().upper()
        final_token = hashlib.md5(f"{inter_md5}{token_start}".encode()).hexdigest().upper()

        login_res = await self._post(
            URL_LOGIN,
            {
                "id": 2,
                "uiVersion": 4.0,
                "params": {
                    "telId": "00:00:00:00:00:00",
                    "checkFailCount": 0,
                    "usrId": username,
                    "pwd": final_token,
                },
            },
            headers=self._app_headers(),
            require_results=True,
        )
        results = login_res["results"]
        usr_id = results["usrId"]
        ssid = results["ssId"]
        family_id = results["familyId"]
        real_family_id = results["realFamilyId"]
        families = _extract_family_infos(results, family_id, real_family_id)
        family_name = _family_name_for(families, family_id, real_family_id)

        self.ssid = ssid
        devices = await self.get_devices(usr_id, family_id, real_family_id)
        return LoginResult(
            usr_id=usr_id,
            ssid=ssid,
            family_id=family_id,
            real_family_id=real_family_id,
            family_name=family_name,
            families=families,
            devices=devices,
        )

    async def get_devices(
        self, usr_id: str, family_id: str, real_family_id: str
    ) -> dict[str, dict[str, Any]]:
        """Return all bound devices for the current account session."""
        res = await self._post(
            URL_GET_DEV,
            {
                "id": 3,
                "uiVersion": 4.0,
                "params": {
                    "realFamilyId": real_family_id,
                    "familyId": family_id,
                    "usrId": usr_id,
                },
            },
            headers=self._app_headers(include_cookie=True),
            require_results=True,
        )

        devices = {}
        for dev in res["results"].get("devList", []):
            device_id = dev.get("deviceId")
            params = dev.get("params")
            if device_id and isinstance(params, dict):
                devices[device_id] = params
        return devices

    async def get_device_status(
        self,
        profile: PanasonicProfile,
        usr_id: str,
        device_id: str,
        token: str,
        device_model: str | None = None,
    ) -> dict[str, Any]:
        """Fetch the latest status for a supported device profile."""
        endpoint = profile.status_endpoint
        identity_params = {
            "usrId": usr_id,
            "deviceId": device_id,
            "token": token,
        }
        payload = {"id": endpoint.request_id, **identity_params}
        if endpoint.wrap_request_params:
            payload = {
                "id": endpoint.request_id,
                "params": identity_params,
            }
        elif endpoint.request_params is not None:
            payload["params"] = dict(endpoint.request_params)
        res = await self._post(
            self._endpoint_url(endpoint),
            payload,
            headers=self._control_headers(profile, device_id, device_model),
            require_results=endpoint.require_results,
            allow_non_json_response=endpoint.allow_non_json_response,
        )

        results = res.get("results") if endpoint.require_results else res.get("results", res)
        if not isinstance(results, dict):
            raise PanasonicApiResponseError(
                f"Status response results must be an object: {res}"
            )
        results = _select_status_results(results, endpoint.required_result_keys)
        missing_keys = endpoint.required_result_keys - results.keys()
        if missing_keys:
            raise PanasonicApiResponseError(
                f"Status response did not include required keys: {sorted(missing_keys)}; "
                f"response: {res}"
            )
        return results

    async def set_device_status(
        self,
        profile: PanasonicProfile,
        usr_id: str,
        device_id: str,
        token: str,
        params: dict[str, Any],
        device_model: str | None = None,
    ) -> dict[str, Any]:
        """Send status/control params for a supported device profile."""
        endpoint = profile.set_endpoint
        return await self._post(
            self._endpoint_url(endpoint),
            {
                "id": endpoint.request_id,
                "usrId": usr_id,
                "deviceId": device_id,
                "token": token,
                "params": params,
            },
            headers=self._control_headers(profile, device_id, device_model),
            require_results=endpoint.require_results,
            allow_non_json_response=endpoint.allow_non_json_response,
        )

    async def _post(
        self,
        url: str,
        payload: dict[str, Any],
        *,
        headers: dict[str, str],
        require_results: bool,
        allow_non_json_response: bool = False,
    ) -> dict[str, Any]:
        session = async_get_clientsession(self._hass)
        try:
            async with async_timeout.timeout(10):
                response = await session.post(url, json=payload, headers=headers, ssl=False)
                if response.status != 200:
                    text = await response.text()
                    raise PanasonicApiResponseError(
                        f"HTTP {response.status} from {url}: {text[:200]}"
                    )

                try:
                    data = await response.json()
                except Exception as err:
                    text = await response.text()
                    if allow_non_json_response:
                        for auth_code in AUTH_ERROR_CODES:
                            if auth_code in text:
                                raise PanasonicApiAuthError(
                                    f"Panasonic session expired (errorCode: {auth_code})"
                                ) from err
                        return {}
                    raise PanasonicApiResponseError(
                        f"Invalid JSON from {url}: {text[:200]}"
                    ) from err
        except PanasonicApiError:
            raise
        except TimeoutError as err:
            raise PanasonicApiResponseError(f"Request timed out: {url}") from err
        except Exception as err:
            raise PanasonicApiResponseError(f"Request failed: {url}: {err}") from err

        if not isinstance(data, dict):
            raise PanasonicApiResponseError(f"Unexpected JSON response from {url}")

        self._raise_for_business_error(data)
        if require_results and "results" not in data:
            raise PanasonicApiResponseError(f"Missing results in response from {url}")
        return data

    def _raise_for_business_error(self, data: dict[str, Any]) -> None:
        nested_error = data.get("error")
        nested_error = nested_error if isinstance(nested_error, dict) else {}
        error_code = data.get("errorCode", nested_error.get("code"))
        if error_code in SUCCESS_ERROR_CODES:
            return

        error_code_text = str(error_code)
        message = (
            data.get("errorMessage")
            or data.get("msg")
            or nested_error.get("message")
            or "Panasonic API error"
        )
        if error_code_text in AUTH_ERROR_CODES:
            raise PanasonicApiAuthError(f"{message} (errorCode: {error_code_text})")
        raise PanasonicApiResponseError(f"{message} (errorCode: {error_code_text})")

    def _app_headers(self, include_cookie: bool = False) -> dict[str, str]:
        headers = {
            "User-Agent": "SmartApp",
            "Content-Type": "application/json",
        }
        if include_cookie and self.ssid:
            headers["Cookie"] = f"SSID={self.ssid}"
        return headers

    def _endpoint_url(self, endpoint: PanasonicEndpoint) -> str:
        return f"{BASE_URL}/{endpoint.path}"

    def _control_headers(
        self,
        profile: PanasonicProfile | None = None,
        device_id: str | None = None,
        device_model: str | None = None,
    ) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X)",
            "xtoken": f"SSID={self.ssid}",
            "DNT": "1",
            "Origin": "https://app.psmartcloud.com",
            "X-Requested-With": "XMLHttpRequest",
        }
        if profile and profile.cookie_required and self.ssid:
            headers["Cookie"] = f"SSID={self.ssid}"
        if profile and profile.referer_template:
            referer_dev_type = _referer_dev_type(profile, device_model)
            headers["Referer"] = profile.referer_template.format(
                device_id=device_id or "",
                controller_model=profile.controller_model,
                referer_dev_type=referer_dev_type,
                referer_model_path=_referer_model_path(referer_dev_type),
                profile_id=profile.profile_id,
            )
        if profile:
            headers.update(profile.extra_control_headers)
        return headers


def _select_status_results(
    results: dict[str, Any],
    required_keys: frozenset[str],
) -> dict[str, Any]:
    """Return the object containing status fields from common Panasonic wrappers."""
    if not required_keys or required_keys <= results.keys():
        return results

    for key in ("params", "statusInfo", "status", "data"):
        nested = results.get(key)
        if isinstance(nested, dict) and required_keys <= nested.keys():
            return nested

    return results


def _extract_family_infos(
    results: dict[str, Any],
    default_family_id: str,
    default_real_family_id: str,
) -> tuple[FamilyInfo, ...]:
    """Extract family list from known and nested Panasonic login response shapes."""
    families: list[FamilyInfo] = []
    seen: set[tuple[str, str]] = set()

    def add_family(candidate: dict[str, Any]) -> None:
        family_id = candidate.get("familyId") or candidate.get("id")
        real_family_id = candidate.get("realFamilyId") or candidate.get("realId")
        if not family_id or not real_family_id:
            return

        key = (str(family_id), str(real_family_id))
        if key in seen:
            return

        seen.add(key)
        name = (
            candidate.get("familyName")
            or candidate.get("name")
            or candidate.get("homeName")
            or candidate.get("houseName")
        )
        families.append(
            FamilyInfo(
                family_id=str(family_id),
                real_family_id=str(real_family_id),
                name=str(name) if name else None,
            )
        )

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            add_family(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for key in (
        "familyList",
        "families",
        "realFamilyList",
        "usrFamilyList",
        "homeList",
        "houseList",
    ):
        walk(results.get(key))

    add_family(results)
    if not families:
        families.append(
            FamilyInfo(
                family_id=str(default_family_id),
                real_family_id=str(default_real_family_id),
            )
        )
    return tuple(families)


def _family_name_for(
    families: tuple[FamilyInfo, ...],
    family_id: str,
    real_family_id: str,
) -> str | None:
    for family in families:
        if family.family_id == family_id and family.real_family_id == real_family_id:
            return family.name
    return None


def _referer_dev_type(profile: PanasonicProfile, device_model: str | None) -> str:
    """Return the model value to present to Panasonic's web control page."""
    model = (device_model or "").strip()
    if model and model.upper() not in {"AIRCLE-05-02"}:
        return model
    return profile.controller_model


def _referer_model_path(dev_type: str) -> str:
    """Return the path segment used by Panasonic's web control page."""
    if dev_type.upper().startswith("FV-"):
        return dev_type[3:]
    return dev_type
