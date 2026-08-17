#!/usr/bin/env python3
"""Open-Meteo ERA5 archive wind lookup, averaged over the local race window."""
import urllib.request, urllib.parse, json, math, time

RACE_START_H, RACE_END_H = 12, 16  # local hours to average (typical 470 race window)
COMPASS16 = ["N","NNE","NE","ENE","E","ESE","SE","SSE",
             "S","SSW","SW","WSW","W","WNW","NW","NNW"]

def compass(deg):
    return COMPASS16[int((deg % 360) / 22.5 + 0.5) % 16]

def fetch_wind(lat, lon, tz, date, retries=3):
    """Return dict with mean speed (m/s), vector-mean direction (deg), compass, n_hours.
    date: 'YYYY-MM-DD'. Returns None on failure."""
    q = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon,
        "start_date": date, "end_date": date,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "wind_speed_unit": "ms", "timezone": tz,
    })
    url = "https://archive-api.open-meteo.com/v1/archive?" + q
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=30) as r:
                data = json.load(r)
            break
        except Exception as e:
            if attempt == retries - 1:
                return None
            time.sleep(2 * (attempt + 1))
    h = data.get("hourly", {})
    times = h.get("time", [])
    spd = h.get("wind_speed_10m", [])
    dr = h.get("wind_direction_10m", [])
    sx = sy = ssum = n = 0.0
    for t, s, d in zip(times, spd, dr):
        if s is None or d is None:
            continue
        hour = int(t[11:13])
        if RACE_START_H <= hour < RACE_END_H:
            ssum += s
            rad = math.radians(d)
            sx += math.sin(rad); sy += math.cos(rad)
            n += 1
    if n == 0:
        return None
    mean_spd = ssum / n
    mean_dir = (math.degrees(math.atan2(sx, sy))) % 360
    return {"speed_ms": round(mean_spd, 1), "dir_deg": int(round(mean_dir)),
            "compass": compass(mean_dir), "n_hours": int(n)}

if __name__ == "__main__":
    # test: Enoshima 2019-08-09 (Race Day 6, 2019 Worlds)
    print("Enoshima 2019-08-09:", fetch_wind(35.30, 139.48, "Asia/Tokyo", "2019-08-09"))
    print("Vilamoura 2021-03-13:", fetch_wind(37.07, -8.12, "Europe/Lisbon", "2021-03-13"))
    print("La Rochelle 2013-08-06:", fetch_wind(46.16, -1.15, "Europe/Paris", "2013-08-06"))
