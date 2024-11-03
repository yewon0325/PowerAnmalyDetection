import time
from datetime import datetime
from firebaseload import get_new_data, process_data
from statsmodels.tsa.statespace.sarimax import SARIMAX
import requests
import warnings

TARGET_MONTHLY_COST = 9300  # (경고알람?을 줄)요금 한도 설정 
RATE_PER_KWH1 = 120.0  # 전력량 요금 (원/kWh) 1구간
RATE_PER_KWH2 = 214.6  # 전력량 요금 (원/kWh) 2구간
RATE_PER_KWH3 = 307.3  # 전력량 요금 (원/kWh) 3구간

BASE_RATE_TIER1 = 910 # 전력량 기본 요금 1구간 
BASE_RATE_TIER2 = 1600 # 전력량 기본 요금 2구간 
BASE_RATE_TIER3 = 7300 # 전력량 기본 요금 3구간 



HOURS_IN_DAY = 24
DAYS_IN_MONTH = 30

total_power_consumption = 0.0 #누적 전력
total_cost = 0.0 #누적 금액
adjusted_powers = [] #전력 소비량 리스트 (초기화)

# 마지막으로 처리한 데이터의 키 (firebase 키)
last_key = None

#---------------------초기 금액으로 구간 예측-----------------
def predict_powerStage(month, last_month_cost):
    # 각 단계의 중간값 계산
    summer_boundary_1_2 = (36910.0 + 66194.6) / 2
    non_summer_boundary_1_2 = (24910.0 + 44734.6) / 2

    if month == 7 or month == 8:  # 하계 (7월, 8월)
        if 910.0 <= last_month_cost <= 36910.0:
            return RATE_PER_KWH1
        elif 66194.6 <= last_month_cost <= 98170.0:
            return RATE_PER_KWH2
        elif last_month_cost > 98170.0:
            return RATE_PER_KWH3
        elif 36910.0 < last_month_cost < 66194.6:  # 1단계와 2단계 사이
            return RATE_PER_KWH1 if last_month_cost < summer_boundary_1_2 else RATE_PER_KWH2
        
    else:  # 기타 계절 (1~6월, 9~12월)
        if 910.0 <= last_month_cost <= 24910.0:
            return RATE_PER_KWH1
        elif 44734.6 <= last_month_cost <= 87440.0:
            return RATE_PER_KWH2
        elif last_month_cost > 87440.0:
            return RATE_PER_KWH3
        elif 24910.0 < last_month_cost < 44734.6:  # 1단계와 2단계 사이
            return RATE_PER_KWH1 if last_month_cost < non_summer_boundary_1_2 else RATE_PER_KWH2
       

#---------------------- 구간별 누진세 젹용 요금---------------
def update_total_consumption_and_cost(adjusted_powers, month): # 매개변수: 전력, month 
    total_power_consumption = sum(adjusted_powers) #총 전력 계산: total_power_consumption
    if month == 7 or month == 8:
        if total_power_consumption <= 300:
            total_cost = total_power_consumption * RATE_PER_KWH1 + BASE_RATE_TIER1

        elif total_power_consumption > 300 and total_power_consumption <=450:
            total_cost = total_power_consumption * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption * RATE_PER_KWH3 + BASE_RATE_TIER3
    else:
        if total_power_consumption <= 200:
            total_cost = total_power_consumption * RATE_PER_KWH1 + BASE_RATE_TIER1

        elif total_power_consumption > 200 and total_power_consumption <=400:
            total_cost = total_power_consumption * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption * RATE_PER_KWH3 + BASE_RATE_TIER3
    return total_power_consumption, total_cost #총 전력 소비량, 총 요금 반환


#초기의 금액 예측(초기 예측값)을 위한 함수
def initial_predict(last_month_cost, month): 
    RATE_PER_KWH = predict_powerStage(month, last_month_cost)
    last_month_usage_kwh = last_month_cost / RATE_PER_KWH
    daily_avg_kwh = last_month_usage_kwh / DAYS_IN_MONTH
    hourly_avg_kwh = daily_avg_kwh / HOURS_IN_DAY 
    return hourly_avg_kwh #시간당 평균 전력 소비량 반환


 # 다음 달로 바뀔 때 이전 달 데이터를 더 많이 반영하도록 가중치 조절 필요 -------------------------------------------------------->
def predict_and_detect_anomaly(adjusted_powers, total_cost, hourly_avg_kwh,month): # 매개변수 => 전력리스트 , 총 요금, 시간당 평균 전력 소비량 반환
    now = datetime.now()
   
    if len(adjusted_powers) < 3600: # 측정이 한시간 미만인 경우 
        #print("데이터 부족으로 인해 초기 예측값을 사용합니다.")  
        total_power_consumption,total_cost = update_total_consumption_and_cost(adjusted_powers,month)
        # 현재 시간
        hours_passed_today = now.hour + (now.minute / 60)  # 시간을 기준으로 누적
        hours_ratio = hours_passed_today / HOURS_IN_DAY  # 하루 중 지난 시간의 비율

        estimated_daily_cost = hourly_avg_kwh * HOURS_IN_DAY * float(total_cost)  # 하루 예상 요금
        adjusted_daily_cost = estimated_daily_cost * hours_ratio  # 시간에 따른 일일 요금 조정

        # 월 예상 요금 계산
        days_passed = now.day #지난 일자 (요금 예측할 때 사용)
        predicted_monthly_cost = (total_cost + adjusted_daily_cost) * (DAYS_IN_MONTH / days_passed) 
   
    else:
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # SARIMA 모델은 최근 100개 데이터만 사용 ----------------------------------------------------------------> 과적합 문제 발생 우려.

                model = SARIMAX(adjusted_powers[-3600:], order=(1, 1, 1), seasonal_order=(1, 1, 1, 24)) 
                model_fit = model.fit(disp=False) #모델 데이터 학습

                #예측
                forecast = model_fit.forecast(steps=1) # 다음 1시간동안의 전력 소비량 예측
                predicted_power = forecast[0] #다음 시간 예상 소비량

                #예측 월별 금액
                #predicted_monthly_cost = (total_cost + (predicted_power * RATE_PER_KWH)) * (DAYS_IN_MONTH / now.day)
                
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

# 사용자가 입력한 지난달 총 요금 (예: 27000원)
last_month_cost = 27000
pre_month = 6
hourly_avg_kwh = initial_predict(last_month_cost,pre_month)

# 실시간 데이터 수집 및 예측 루프
while True:
    try:
        new_data, last_key = get_new_data(last_key)  # Firebase에서 가장 최신 데이터 하나씩 가져오기 
        
        
        #print(f"새로운 데이터: {new_data}, 마지막 키: {last_key}")
        if new_data:
            _, new_timestamps, new_powers = process_data(new_data)

            # adjusted_powers에 새로운 데이터를 누적
            adjusted_powers.extend(new_powers)

            months = [entry['Timestamp'].split('-')[1] for entry in new_data.values()]
            
            # 디버깅: adjusted_powers 리스트 확인
            #print(f"현재 adjusted_powers 길이: {len(adjusted_powers)}, 마지막 데이터 5개: {adjusted_powers[-5:]}")

            # 누적 전력 소비량 및 요금 계산
            total_power_consumption, total_cost = update_total_consumption_and_cost(adjusted_powers,months[-1]) # months[-1] 최신 데이터의 달을 가지고 옵니다
         
            # 예측된 월 요금 계산 및 이상치 탐지
            predicted_cost = predict_and_detect_anomaly(adjusted_powers, total_cost, hourly_avg_kwh,months[-1])

            # 현재 전력 요금 및 예측되는 월 요금 출력
            print(f"현재 누적 전력 소비량: {total_power_consumption:.3f} kWh")
            print(f"현재 누적 전력 요금: {total_cost:.2f} 원")
            if predicted_cost is not None:
                print(f"이번달 전력 요금 예측: {predicted_cost:.2f} 원", end="\n\n")
            else:
                print("예측이 실패하여 현재 요금을 출력할 수 없습니다.")

        # 20초마다 업데이트
        time.sleep(5)

    except requests.exceptions.RequestException as e:
        print("데이터를 가져오는 중 오류 발생:", e)
        time.sleep(5)
