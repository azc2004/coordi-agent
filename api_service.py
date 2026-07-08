import requests

def fetch_product_list():
    url = "https://hapix.halfclub.com/searches/prdList/?selAcntCd=A6082&limit=0,40&sortSeq=12&siteCd=1&device=pc&icnSet="
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("result", {}).get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"Error fetching product list: {e}")
        return []

def fetch_product_info(prd_no):
    url = f"https://hapix.halfclub.com/product/products/withoutPrice/{prd_no}?countryCd=001&langCd=001&siteCd=1&deviceCd=001"
    try:
        response = requests.get(url)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        print(f"Error fetching product info for {prd_no}: {e}")
        return None

def search_products(keyword, gnd_cd=None, brand_cd=None, cat_level=None, cat_code=None):
    url = f"https://hapix.halfclub.com/searches/prdList/?keyword={keyword}&device=pc&limit=0,20&sortSeq=12"
    if gnd_cd:
        url += f"&gndCd={gnd_cd}"
    if brand_cd:
        url += f"&brandCd={brand_cd}"
    if cat_level and cat_code:
        url += f"&{cat_level}={cat_code}"
        
    try:
        response = requests.get(url)
        response.raise_for_status()
        data = response.json()
        return data.get("data", {}).get("result", {}).get("hits", {}).get("hits", [])
    except Exception as e:
        print(f"Error searching products: {e}")
        return []

def fetch_daily_weather_forecast_seoul():
    url = "https://api.open-meteo.com/v1/forecast?latitude=37.566&longitude=126.978&daily=weathercode,temperature_2m_max,temperature_2m_min&timezone=Asia%2FSeoul&past_days=3&forecast_days=14"
    try:
        response = requests.get(url, timeout=5)
        response.raise_for_status()
        data = response.json()
        daily = data.get("daily", {})
        times = daily.get("time", [])
        codes = daily.get("weathercode", [])
        temps_max = daily.get("temperature_2m_max", [])
        temps_min = daily.get("temperature_2m_min", [])
        
        forecast_dict = {}
        for i, date_str in enumerate(times):
            code = codes[i] if i < len(codes) else 0
            temp_max = temps_max[i] if i < len(temps_max) else 20.0
            temp_min = temps_min[i] if i < len(temps_min) else 10.0
            avg_temp = (temp_max + temp_min) / 2.0
            
            # WMO Weather interpretation codes
            if code in [0, 1]:
                weather_str = "맑음 ☀️"
            elif code in [2, 3, 45, 48]:
                weather_str = "흐림 ☁️"
            elif code in [51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82, 95, 96, 99]:
                weather_str = "비 🌧️"
            elif code in [71, 73, 75, 77, 85, 86]:
                weather_str = "눈 ❄️"
            else:
                weather_str = "맑음 ☀️"
                
            if avg_temp < 5.0 and weather_str == "맑음 ☀️":
                weather_str = "바람/추움 🌬️"
                
            forecast_dict[date_str] = {"weather_str": weather_str, "temp_max": temp_max, "temp_min": temp_min}
            
        return forecast_dict
    except Exception as e:
        print(f"Error fetching daily weather forecast: {e}")
        return {}
