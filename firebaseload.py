import requests
import json
from datetime import datetime

# Firebase 설정 정보
database_url = 

# 새로운 데이터만 읽어오는 함수
def get_new_data(last_key=None):
    url = f'{database_url}/power_consumption.json'
    response = requests.get(url)
    
    if response.status_code != 200:
        print(f"Error fetching data: {response.status_code}")
        return None, last_key  # 오류 발생 시, last_key도 반환

    data = response.json()
    
    new_data = {}

    for key, value in data.items():
        # last_key 이후의 데이터만 추가
        if last_key is None or key > last_key:
            new_data[key] = value

    # 새로운 데이터가 있으면 가장 최신 key로 last_key 업데이트
    if new_data:
        last_key = max(new_data.keys())  # 가장 최신 key로 last_key 설정
        print(f"새로 감지된 데이터 개수: {len(new_data)} | 업데이트된 last_key: {last_key}")  # 디버깅 정보

    return new_data, last_key

# 데이터 처리 함수
def process_data(data):
    if data is None:
        print("No new data to process.")
        return [], [], []

    processed_data = []
    timestamps = []
    adjusted_powers_kw = []

    for key, value in data.items():
        if 'Instant Power Consumption (kW)' not in value:
            continue
        
        # 데이터 처리
        timestamp = value['Timestamp']
        power_kw = float(value['Instant Power Consumption (kW)'])  # kW 단위로 가져옴

        # kW 단위로 저장
        processed_data.append({
            'Timestamp': timestamp,
            'Instant Power Consumption (kW)': power_kw,          
        })
        
        timestamps.append(timestamp)
        adjusted_powers_kw.append(power_kw)  # kW 값 저장

    return processed_data, timestamps, adjusted_powers_kw
