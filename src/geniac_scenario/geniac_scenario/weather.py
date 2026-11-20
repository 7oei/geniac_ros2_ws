"""Dated online weather for Sakimui, Shibetsu; no network in playback."""
from datetime import datetime
from zoneinfo import ZoneInfo
import math
import requests

JST=ZoneInfo('Asia/Tokyo')
LATITUDE=43.828328
LONGITUDE=145.090059
URL='https://api.open-meteo.com/v1/forecast'


def surface_for(code,rain,snow):
    if snow>0 or code in (71,73,75,77,85,86):return 'snow'
    if rain>0 or code in (51,53,55,56,57,61,63,65,66,67,80,81,82,95,96,99):return 'rain'
    if code in (0,1,2,3,45,48):return 'grass'  # dry/cloudy/fog: explicit dry-ground fallback
    raise ValueError('Unrecognized weather code')


def fetch_weather(now=None,http=requests):
    now=now or datetime.now(JST)
    try:
        r=http.get(URL,params={'latitude':LATITUDE,'longitude':LONGITUDE,'timezone':'Asia/Tokyo',
            'current':'weather_code,rain,snowfall','forecast_days':1},timeout=20,allow_redirects=False)
        if r.status_code!=200:raise RuntimeError('Weather HTTP '+str(r.status_code))
        data=r.json()['current'];observed=datetime.fromisoformat(data['time']).replace(tzinfo=JST)
        if observed.date()!=now.astimezone(JST).date() or abs((now-observed).total_seconds())>10800:
            raise ValueError('Weather is not current for today')
        code=int(data['weather_code']);rain=float(data['rain']);snow=float(data['snowfall'])
        if not all(math.isfinite(v) and v>=0 for v in (rain,snow)):raise ValueError('Invalid precipitation')
        return {'location':'北海道標津町崎無異','latitude':LATITUDE,'longitude':LONGITUDE,
                'date':observed.date().isoformat(),'observed_at':observed.isoformat(),'fetched_at':now.isoformat(),
                'weather_code':code,'rain_mm':rain,'snowfall_cm':snow,'surface':surface_for(code,rain,snow),
                'source':URL,'attribution':'Weather data by Open-Meteo (CC BY 4.0)',
                'basis':'current model weather; ground cover is not directly observed'}
    except requests.RequestException:raise RuntimeError('Weather network error') from None
