from datetime import date
from types import SimpleNamespace

import pandas as pd

from tools.compare_radiation_sources import SATELLITE_URL, satellite_weather


def test_satellite_radiation_uses_official_endpoint_and_archival_weather(make_config):
    day = date(2026, 10, 13)
    temperature = pd.DataFrame(
        {"temp_air": [15.0], "wind_speed": [2.0]},
        index=pd.DatetimeIndex([pd.Timestamp(f"{day} 00:30", tz="Europe/Berlin")]),
    )
    payload = {
        "hourly": {
            "time": [int(pd.Timestamp(f"{day} 01:00", tz="Europe/Berlin").tz_convert("UTC").timestamp())],
            "shortwave_radiation": [100.0],
            "direct_normal_irradiance": [120.0],
            "diffuse_radiation": [20.0],
        },
    }
    calls = []

    def get(url, params, timeout):
        calls.append((url, params, timeout))
        return SimpleNamespace(status_code=200, json=lambda: payload)

    result = satellite_weather(make_config(), day, day, temperature, http_get=get)

    assert calls[0][0] == SATELLITE_URL
    assert calls[0][1]["models"] == "satellite_radiation_seamless"
    assert result.iloc[0].to_dict() == {
        "ghi": 100.0,
        "dni": 120.0,
        "dhi": 20.0,
        "temp_air": 15.0,
        "wind_speed": 2.0,
    }
