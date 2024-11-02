import time
from datetime import datetime
from firebaseload import get_new_data, process_data
from statsmodels.tsa.statespace.sarimax import SARIMAX
import requests
import warnings

TARGET_MONTHLY_COST = 30000  # (경고알람?을 줄)요금 한도 설정 
RATE_PER_KWH = 60  # 전력량 요금 (원/kWh)
HOURS_IN_DAY = 24
DAYS_IN_MONTH = 30

total_power_consumption = 0.0 #누적 전력
total_cost = 0.0 #누적 금액
adjusted_powers = [] #전력 소비량 리스트 (초기화)

# 마지막으로 처리한 데이터의 키 (firebase 키)
last_key = None


#초기의 금액 예측(초기 예측값)을 위한 함수
def initial_predict(last_month_cost): 
    last_month_usage_kwh = last_month_cost / RATE_PER_KWH
    daily_avg_kwh = last_month_usage_kwh / DAYS_IN_MONTH
    hourly_avg_kwh = daily_avg_kwh / HOURS_IN_DAY 
    return hourly_avg_kwh #시간당 평균 전력 소비량 반환


def update_total_consumption_and_cost(adjusted_powers):
    total_power_consumption = sum(adjusted_powers) 
    total_cost = total_power_consumption * RATE_PER_KWH 
    return total_power_consumption, total_cost #총 전력 소비량, 총 요금 반환

 
def predict_and_detect_anomaly(adjusted_powers, total_cost, hourly_avg_kwh):
    now = datetime.now()
    # 초기 데이터가 100개 이하일 경우 초기 예측값 사용
    if len(adjusted_powers) < 100:
        #print("데이터 부족으로 인해 초기 예측값을 사용합니다.")  
        # 현재 시간
        
        hours_passed_today = now.hour + (now.minute / 60)  # 시간을 기준으로 누적
        hours_ratio = hours_passed_today / HOURS_IN_DAY  # 하루 중 지난 시간의 비율
        

        estimated_daily_cost = hourly_avg_kwh * HOURS_IN_DAY * RATE_PER_KWH  # 하루 예상 요금
        adjusted_daily_cost = estimated_daily_cost * hours_ratio  # 시간에 따른 일일 요금 조정

        # 월 예상 요금 계산
        days_passed = now.day #지난 일자 (요금 예측할 때 사용)
        predicted_monthly_cost = (total_cost + adjusted_daily_cost) * (DAYS_IN_MONTH / days_passed) 
   
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # SARIMA 모델은 최근 100개 데이터만 사용
                model = SARIMAX(adjusted_powers[-100:], order=(1, 1, 1), seasonal_order=(1, 1, 1, 24)) 
                model_fit = model.fit(disp=False) #모델 데이터 학습

                #예측
                forecast = model_fit.forecast(steps=1) # 다음 1시간동안의 전력 소비량 예측
                predicted_power = forecast[0] #다음 시간 예상 소비량

                #예측 월별 금액
                predicted_monthly_cost = (total_cost + (predicted_power * RATE_PER_KWH)) * (DAYS_IN_MONTH / now.day)
                
        except Exception as e:
            print("SARIMA 모델 학습 중 오류가 발생했습니다:", str(e))
            predicted_monthly_cost = None

    if predicted_monthly_cost and predicted_monthly_cost > TARGET_MONTHLY_COST:
        print(f"경고: 예측 월 요금({predicted_monthly_cost:.2f}원)이 설정된 월 요금 한도({TARGET_MONTHLY_COST}원)를 초과할 것으로 예상됩니다!")
    elif predicted_monthly_cost:
        print(f"현재 누적 요금: {total_cost:.2f}원, 예상 월 요금: {predicted_monthly_cost:.2f}원 (사용자가 설정한 한도 금액): {TARGET_MONTHLY_COST}원)")
    else:
        print("예측을 수행할 수 없습니다.")

    return predicted_monthly_cost

# 사용자가 입력한 지난달 총 요금 (예: 270000원)
last_month_cost = 270000
hourly_avg_kwh = initial_predict(last_month_cost)

# 실시간 데이터 수집 및 예측 루프
while True:
    try:
        new_data, last_key = get_new_data(last_key)  # Firebase에서 가장 최신 데이터 하나씩 가져오기
        if new_data:
            _, new_timestamps, new_powers = process_data(new_data)
            
            # 디버깅: 새로 감지된 데이터의 총합과 개수 출력
            # print(f"새로 추가된 데이터 개수: {len(new_powers)}, 총합: {sum(new_powers):.2f} kWh")

            # adjusted_powers에 새로운 데이터를 누적
            adjusted_powers.extend(new_powers)
            
            # 디버깅: adjusted_powers 리스트 확인
            # print(f"현재 adjusted_powers 길이: {len(adjusted_powers)}, 마지막 데이터 5개: {adjusted_powers[-5:]}")

            # 누적 전력 소비량 및 요금 계산
            total_power_consumption, total_cost = update_total_consumption_and_cost(adjusted_powers)

            # 예측된 월 요금 계산 및 이상치 탐지
            predicted_cost = predict_and_detect_anomaly(adjusted_powers, total_cost, hourly_avg_kwh)

            # 현재 전력 요금 및 예측되는 월 요금 출력
            print(f"현재 누적 전력 소비량: {total_power_consumption:.2f} kWh")
            print(f"현재 누적 전력 요금: {total_cost:.2f} 원")
            if predicted_cost is not None:
                print(f"이번달 전력 요금 예측: {predicted_cost:.2f} 원")
            else:
                print("예측이 실패하여 현재 요금을 출력할 수 없습니다.")

        # 20초마다 업데이트
        time.sleep(20)

    except requests.exceptions.RequestException as e:
        print("데이터를 가져오는 중 오류 발생:", e)
        time.sleep(20)
