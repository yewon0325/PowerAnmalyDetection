#%%
import time
from datetime import datetime
from firebaseload import get_new_data, process_data
from statsmodels.tsa.statespace.sarimax import SARIMAX
import requests
import warnings
import numpy as np
import pandas as pd

import time
import calendar
from datetime import datetime
from firebaseload import get_new_data, process_data
from statsmodels.tsa.statespace.sarimax import SARIMAX
import requests
import warnings
import matplotlib.pyplot as plt


# 설정 상수
TARGET_MONTHLY_COST = 9300 # (경고알람?을 줄)요금 한도 설정 

RATE_PER_KWH1 = 120.0  # 전력량 요금 (원/kWh) 1구간
RATE_PER_KWH2 = 214.6  # 전력량 요금 (원/kWh) 2구간
RATE_PER_KWH3 = 307.3  # 전력량 요금 (원/kWh) 3구간

BASE_RATE_TIER1 = 910 # 전력량 기본 요금 1구간 
BASE_RATE_TIER2 = 1600 # 전력량 기본 요금 2구간 
BASE_RATE_TIER3 = 7300 # 전력량 기본 요금 3구간 

HOURS_IN_DAY = 24


total_power_consumption = 0.0 # 누적 전력 소비량 (kWh)
total_cost = 0.0 # 누적 금액
adjusted_powers_kw = [] # 실시간 전력 소비량 (kW) 리스트
adjusted_powers_kwh = [] # 변환된 전력 소비량 (kWh) 리스트

# 마지막으로 처리한 데이터의 키 (firebase 키)
last_key = None

# 이상치와 정상치를 저장할 리스트
outliers = []
normal = []

# 60초마다 그래프를 업데이트하는 타이머
graph_update_interval = 1  # 1초마다 업데이트
last_graph_update_time = time.time()

#--------------------- 초기 예측 요금 계산 함수 -----------------
def predict_power_stage(month, last_month_cost):
    # 각 단계의 중간값 계산
    summer_boundary_1_2 = (36910.0 + 66194.6) / 2
    non_summer_boundary_1_2 = (24910.0 + 44734.6) / 2

    if month in [7, 8]:  # 하계 (7월, 8월)
        if 910 <= last_month_cost <= 36910:
            return RATE_PER_KWH1
        elif 66194.6 <= last_month_cost <= 98170:
            return RATE_PER_KWH2
        elif last_month_cost > 98170:
            return RATE_PER_KWH3
        elif 36910 < last_month_cost < 66194.6:
            return RATE_PER_KWH1 if last_month_cost < summer_boundary_1_2 else RATE_PER_KWH2
    else:  # 기타 계절 (1~6월, 9~12월)
        if 910 <= last_month_cost <= 24910:
            return RATE_PER_KWH1
        elif 44734.6 <= last_month_cost <= 87440:
            return RATE_PER_KWH2
        elif last_month_cost > 87440:
            return RATE_PER_KWH3
        elif 24910 < last_month_cost < 44734.6:
            return RATE_PER_KWH1 if last_month_cost < non_summer_boundary_1_2 else RATE_PER_KWH2


#---------------------- 구간별 누진세 요금 계산 -------------------
def update_total_consumption_and_cost(adjusted_powers_kwh, month): 
    total_power_consumption = sum(adjusted_powers_kwh) # kWh로 누적 전력 계산
    if month in [7, 8]:  # 하계
        if total_power_consumption <= 300:
            total_cost = total_power_consumption * RATE_PER_KWH1 + BASE_RATE_TIER1
        elif 300 < total_power_consumption <= 450:
            total_cost = total_power_consumption * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption * RATE_PER_KWH3 + BASE_RATE_TIER3
    else:  # 기타 계절
        if total_power_consumption <= 200:
            total_cost = total_power_consumption * RATE_PER_KWH1 + BASE_RATE_TIER1
        elif 200 < total_power_consumption <= 400:
            total_cost = total_power_consumption * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption * RATE_PER_KWH3 + BASE_RATE_TIER3
    return total_power_consumption, total_cost


# 초기의 금액 예측(초기 예측값)을 위한 함수
def initial_predict(last_month_cost, month):
    rate_per_kwh = predict_power_stage(month, last_month_cost)
    last_month_usage_kwh = last_month_cost / rate_per_kwh
    days_in_month = calendar.monthrange(datetime.now().year, month)[1]
    daily_avg_kwh = last_month_usage_kwh / days_in_month
    hourly_avg_kwh = daily_avg_kwh / HOURS_IN_DAY
    return hourly_avg_kwh


#------------------- 예측 및 이상치 탐지 함수 -------------------
def predict_and_detect_anomaly(adjusted_powers_kwh, total_cost, hourly_avg_kwh, today, days_passed):
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_remaining = days_in_month - days_passed

    # 일별 평균 요금을 기반으로 월 예측
    # if days_passed == 1 or len(adjusted_powers_kwh) < 1800:  # 하루 이하의 데이터만 있는 경우
    if len(adjusted_powers_kwh) < 1800:  # 측정이 30분 미만인 경우  
        daily_cost = total_cost / days_passed if days_passed > 0 else total_cost
        predicted_monthly_cost = daily_cost * days_in_month  # 하루치 평균 요금으로 월간 요금 예측
    else:
        # SARIMA 모델을 사용하여 예측
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                model = SARIMAX(adjusted_powers_kwh[-3600:], order=(1, 1, 1), seasonal_order=(1, 1, 1, 24))
                model_fit = model.fit(disp=False)
                forecast = model_fit.forecast(steps=1)
                
                # SARIMA 예측값을 일별 소비량으로 계산하고 남은 일수 반영
                estimated_daily_cost = forecast[0] * HOURS_IN_DAY
                predicted_monthly_cost = total_cost + (estimated_daily_cost * days_remaining)
                
        except Exception as e:
            print("SARIMA 모델 학습 오류:", str(e))
            predicted_monthly_cost = None

    # 예측 결과 출력
    if predicted_monthly_cost and predicted_monthly_cost > TARGET_MONTHLY_COST:
        print(f"경고: 예상 월 요금({predicted_monthly_cost:.2f}원)이 한도({TARGET_MONTHLY_COST}원)를 초과!")
        outliers.append(predicted_monthly_cost)
    elif predicted_monthly_cost:
        print(f"현재 누적 요금: {total_cost:.2f}원, 예상 월 요금: {predicted_monthly_cost:.2f}원")
        normal.append(predicted_monthly_cost)
    else:
        print("예측 불가.")
    return predicted_monthly_cost

# 초기 설정
last_month_cost = 8000
pre_month = 5
hourly_avg_kwh = initial_predict(last_month_cost, pre_month)

# normal과 outliers 리스트를 DataFrame으로 변환
def save_to_dataframe(normal, outliers):
    # 두 리스트의 최대 길이를 기준으로 DataFrame 생성
    max_length = max(len(normal), len(outliers))
    index = list(range(max_length))
    
    # 길이가 짧은 리스트는 NaN으로 채우기
    normal_extended = normal + [None] * (max_length - len(normal))
    outliers_extended = outliers + [None] * (max_length - len(outliers))
    
    # DataFrame 생성
    df = pd.DataFrame({
        'Index' : index,
        'Normal': normal_extended,
        'Outliers': outliers_extended
    })
    
    return df

# # 예제 DataFrame 생성
df = save_to_dataframe(normal, outliers)
df.to_csv("power_anomaly_detection.csv", index=False)

#-------------------- 데이터 수집 및 예측 루프 -------------------
while True:
    try:
        new_data, last_key = get_new_data(last_key) # Firebase에서 가장 최신 데이터 하나씩 가져오기 
        
        if new_data:
            _, new_timestamps, new_powers_kw = process_data(new_data)

            # 실시간 전력 사용량 출력
            for kw in new_powers_kw:
                print(f"실시간 전력 소비량 (kW): {kw:.3f} kW")

            # kW 데이터를 adjusted_powers_kw 리스트에 추가
            adjusted_powers_kw.extend(new_powers_kw)

            # kW 데이터를 kWh로 변환하여 adjusted_powers_kwh 리스트에 추가
            new_powers_kwh = [kw / 3600 for kw in new_powers_kw]
            adjusted_powers_kwh.extend(new_powers_kwh)

            # 현재 날짜를 추출하여 예측에 사용
            today_str = list(new_data.values())[0]['Timestamp']
            try:
                today = datetime.strptime(today_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                # 초 부분이 없는 경우의 형식을 사용
                today = datetime.strptime(today_str, "%Y-%m-%d %H:%M")


            # 지난 일수 계산
            days_passed = today.day

            # 누적 전력 소비량 및 요금 계산
            total_power_consumption, total_cost = update_total_consumption_and_cost(adjusted_powers_kwh, today.month)
            predicted_cost = predict_and_detect_anomaly(adjusted_powers_kwh, total_cost, hourly_avg_kwh, today, days_passed)

            print(f"현재 누적 전력 소비량: {total_power_consumption:.3f} kWh")
            print(f"현재 누적 전력 요금: {total_cost:.2f} 원")
            if predicted_cost is not None:
                print(f"이번달 전력 요금 예측: {predicted_cost:.2f} 원\n")
            else:
                print("예측이 실패하여 현재 요금을 출력할 수 없습니다.")
                
             # 주기적으로 DataFrame으로 저장
            if len(normal) > 0 or len(outliers) > 0:
                df = save_to_dataframe(normal, outliers)
                # print(df)
                df.to_csv("power_anomaly_detection.csv", index=False)
                
                
             # 주기적으로 그래프 업데이트 
            if time.time() - last_graph_update_time >= graph_update_interval:
                df = save_to_dataframe(normal, outliers)
            
                outliers_data = df[['Index', 'Outliers']].dropna()
                normal_data = df[['Index', 'Normal']].dropna()
                
                # 그래프 생성
                plt.figure(figsize=(10, 5))
                plt.plot(outliers_data['Index'], outliers_data['Outliers'], 'ro', label='Outlier')
                plt.plot(normal_data['Index'], normal_data['Normal'], 'b-', label='Inlier')
                
                # 그래프 제목 및 레이블
                plt.title('Anomaly Detection')
                plt.xlabel('Index')
                plt.ylabel('Predicted Power Consumption Value')
                plt.legend()
                plt.show()
                
                # 그래프 업데이트 시간을 현재 시간으로 갱신
                last_graph_update_time = time.time()
        time.sleep(5)

    except requests.exceptions.RequestException as e:
        print("데이터 오류:", e)
        time.sleep(5)
    
