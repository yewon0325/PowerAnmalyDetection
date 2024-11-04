import requests
import json
from datetime import datetime, timedelta

# Firebase 설정 정보
database_url = 

# 데이터 읽기 함수
def get_data():
    url = f'{database_url}/power_consumption.json'
    response = requests.get(url)
    
    if response.status_code == 200:
        return response.json()
    else:
        print(f"Error: {response.status_code}")
        return None

# 데이터 처리 함수
def process_data(data, period="hour"):
    if data is None:
        print("No data found.")
        return [], [], []

    processed_data = {}  # 누적 데이터 저장 딕셔너리
    timestamps = []  # 누적된 Timestamp 저장
    adjusted_powers = []  # 누적된 Adjusted Power Consumption 저장
    cumulative_power = 0  # 누적된 전력 소비량 저장 변수

    for key, value in data.items():
        # 'Power Consumption (kW)' 필드가 없는 경우 건너뛰기
        if 'Power Consumption (kW)' not in value:
            continue
        
        timestamp = value['Timestamp']
        adjusted_power = float(value['Power Consumption (kW)']) * 1.1  # 전력 소비량을 1.1배로 증가
        
        # 1시간 단위로 누적 시간까지만 반영
        dt = datetime.strptime(timestamp, "%Y-%m-%d %H:%M")
        period_key = dt.strftime("%Y-%m-%d %H:00")

        # period_key가 이미 존재하면 누적, 없으면 새로 생성
        if period_key in processed_data:
            processed_data[period_key] += adjusted_power
        else:
            processed_data[period_key] = adjusted_power

    # 누적 값을 계산 후 adjusted_powers에 추가
    for period_key in sorted(processed_data.keys()):
        cumulative_power += processed_data[period_key]
        adjusted_powers.append(cumulative_power)  # 누적된 값 추가
        timestamps.append(period_key)

    # 리스트로 변환
    result = [{"Timestamp": period_key, "Total Adjusted Power Consumption (kW)": cumulative} for period_key, cumulative in zip(timestamps, adjusted_powers)]
    
    return result, timestamps, adjusted_powers

# 데이터 읽기 및 처리
data = get_data()

result, timestamps, adjusted_powers = process_data(data, period="hour")

# 처리된 데이터 출력
print("Processed Data:", json.dumps(result, indent=2))
print("Timestamps (Hourly):", timestamps)
print("Adjusted Power Consumptions (Cumulative):", adjusted_powers)
