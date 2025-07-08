import subprocess
import time
import requests
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
import sys
import os
import warnings
import firebase_admin
from firebase_admin import credentials, db
from sklearn.metrics import mean_squared_error, mean_absolute_error
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, Span, Div, HoverTool, TextInput, Button
from bokeh.layouts import column, row
from bokeh.server.server import Server
from bokeh.application import Application
from bokeh.application.handlers import FunctionHandler
from statsmodels.tsa.arima.model import ARIMA

# 사용자 정의 모듈 가져오기 (사용자의 환경에 맞게 수정)
from firebaseload import get_new_data, process_data

# inputdata.py를 백그라운드에서 실행
if sys.platform == "win32":
    # Windows의 경우
    subprocess.Popen(['python', 'inputdata.py'], creationflags=subprocess.CREATE_NEW_CONSOLE)
else:
    # Unix/Linux/MacOS의 경우
    subprocess.Popen(['python', 'inputdata.py'], stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)

# Firebase Admin SDK 초기화
if not firebase_admin._apps:
    cred = credentials.Certificate('')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 
    })

# 초기 설정: 초기 임계값
TARGET_MONTHLY_COST = 915  # 변경 가능, 사용자 입력에 따라 동적으로 업데이트 예정

RATE_PER_KWH1 = 120.0  # 전력량 요금 (원/kWh) 1구간
RATE_PER_KWH2 = 214.6  # 전력량 요금 (원/kWh) 2구간
RATE_PER_KWH3 = 307.3  # 전력량 요금 (원/kWh) 3구간
BASE_RATE_TIER1 = 910   # 전력량 기본 요금 1구간
BASE_RATE_TIER2 = 1600  # 전력량 기본 요금 2구간
BASE_RATE_TIER3 = 7300  # 전력량 기본 요금 3구간

# 데이터 저장용 리스트
adjusted_powers_kw = []  # 실시간 전력 소비량 (kW) 리스트
timestamps = []          # 타임스탬프 리스트
cumulative_actual_power_kwh = []  # 누적 전력 소비량 (kWh)
cumulative_actual_cost = []       # 누적 비용 (원)
cumulative_predicted_power_kwh = []
cumulative_predicted_cost = []

# 마지막으로 처리한 데이터의 타임스탬프
last_timestamp = None

# Bokeh 데이터 소스
source_actual_power = ColumnDataSource(data=dict(time=[], actual=[]))
source_predicted_power = ColumnDataSource(data=dict(time=[], predicted=[]))
source_actual_cost = ColumnDataSource(data=dict(time=[], actual_cost=[]))
source_predicted_cost = ColumnDataSource(data=dict(time=[], predicted_cost=[]))
source_anomaly = ColumnDataSource(data=dict(time=[], anomaly=[]))

# 예측 결과 패널
prediction_panel = Div(
    text="""
    <div style='border: 1px solid #bdc3c7; padding: 15px; text-align: center; width: 800px; height: 50px; margin: auto; background-color: #ecf0f1;'>
        <h3 id="predicted-cost" style='margin: 0; font-size: 16px; color: #2c3e50;'>예측 결과를 기다리는 중...</h3>
    </div>
    """,
    styles={"margin-top": "20px"}
)

# 구간별 누진세 요금 계산 함수
def calculate_total_cost(total_power_consumption_kwh, month):
    if month in [7, 8]:  # 하계
        if total_power_consumption_kwh <= 300:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH1 + BASE_RATE_TIER1
        elif 300 < total_power_consumption_kwh <= 450:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH3 + BASE_RATE_TIER3
    else:  # 기타 계절
        if total_power_consumption_kwh <= 200:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH1 + BASE_RATE_TIER1
        elif 200 < total_power_consumption_kwh <= 400:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH2 + BASE_RATE_TIER2
        else:
            total_cost = total_power_consumption_kwh * RATE_PER_KWH3 + BASE_RATE_TIER3
    return total_cost

# 예측값 갱신 함수
def update_prediction(predicted_cost):
    global prediction_panel, TARGET_MONTHLY_COST
    if predicted_cost is None:
        prediction_panel.text = """
        <div style='border: 1px solid #bdc3c7; padding: 15px; text-align: center; width: 800px; height: 50px; margin: auto; background-color: #ecf0f1;'>
            <h3 id="predicted-cost" style='margin: 0; font-size: 16px; color: #2c3e50;'>예측 결과를 기다리는 중...</h3>
        </div>
        """
    elif predicted_cost > TARGET_MONTHLY_COST:
        prediction_panel.text = f"""
        <div style='border: 1px solid #e74c3c; padding: 15px; text-align: center; width: 800px; height: 50px; margin: auto; background-color: #fcecec;'>
            <h3 id="predicted-cost" style='margin: 0; font-size: 16px; color: #e74c3c;'>경고: 예측된 비용이 임계값을 초과했습니다! 예측 비용: {predicted_cost:,.2f} 원</h3>
        </div>
        """
    else:
        prediction_panel.text = f"""
        <div style='border: 1px solid #27ae60; padding: 15px; text-align: center; width: 800px; height: 50px; margin: auto; background-color: #eafaf1;'>
            <h3 id="predicted-cost" style='margin: 0; font-size: 16px; color: #27ae60;'>예측 비용이 임계값 이내입니다. 예측 비용: {predicted_cost:,.2f} 원</h3>
        </div>
        """

def data_collection_loop():
    global last_timestamp, adjusted_powers_kw, timestamps
    global cumulative_actual_power_kwh, cumulative_actual_cost
    global cumulative_predicted_power_kwh, cumulative_predicted_cost
    global TARGET_MONTHLY_COST

    try:
        # Firebase에서 새로운 데이터 가져오기
        new_data, last_timestamp_update = get_new_data(last_timestamp)
        if last_timestamp_update is not None:
            last_timestamp = last_timestamp_update

        if new_data:
            keys, new_timestamps, new_powers_kw = process_data(new_data)

            # 데이터 정렬 및 중복 제거
            combined_data = list(zip(new_timestamps, new_powers_kw))
            combined_data = sorted(set(combined_data), key=lambda x: x[0])
            new_timestamps, new_powers_kw = zip(*combined_data)

            adjusted_powers_kw.extend(new_powers_kw)
            timestamps.extend(new_timestamps)

            # Bokeh에 실제 전력 소비량 추가
            new_source_data_power = dict(time=new_timestamps, actual=new_powers_kw)
            source_actual_power.stream(new_source_data_power, rollover=200)

            # 누적 전력 소비량 및 비용 계산
            for i in range(len(new_powers_kw)):
                if len(cumulative_actual_power_kwh) == 0:
                    delta_time = 0  # 첫 번째 데이터 포인트의 경우
                    cumulative_energy = 0
                else:
                    delta_time = (new_timestamps[i] - timestamps[-len(new_powers_kw)+i-1]).total_seconds() / 3600
                    cumulative_energy = cumulative_actual_power_kwh[-1]
                energy = new_powers_kw[i] * delta_time  # kWh 계산
                cumulative_energy += energy
                cumulative_actual_power_kwh.append(cumulative_energy)
                # 비용 계산
                total_cost = calculate_total_cost(cumulative_energy, new_timestamps[i].month)
                cumulative_actual_cost.append(total_cost)
                # Bokeh에 실제 비용 추가
                source_actual_cost.stream({'time': [new_timestamps[i]], 'actual_cost': [total_cost]}, rollover=200)

            # 데이터가 충분히 모이면 모델 학습 및 예측
            if len(adjusted_powers_kw) >= 30:
                # 데이터 프레임 생성
                df = pd.DataFrame({'ds': pd.to_datetime(timestamps), 'y': adjusted_powers_kw})
                df = df.sort_values('ds')
                df = df.reset_index(drop=True)

                # ARIMA 모델 훈련
                y = df['y'].values
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    model = ARIMA(y, order=(5,1,0)).fit()

                # 모델의 in-sample MSE 계산 및 출력
                # ARIMA fittedvalues는 1번째 관측부터 시작하므로 y[1:]와 aligned 비교
                fitted_values = model.fittedvalues
                mse = mean_squared_error(y[1:], fitted_values[1:])
                print(f"MSE of ARIMA model: {mse}")

                # 향후 10초 예측
                last_time = df['ds'].iloc[-1]
                future_times = [last_time + timedelta(seconds=i) for i in range(1, 11)]
                forecast = model.forecast(steps=10)
                # forecast는 이미 numpy array 반환, values 속성 필요 없음
                predicted_values = forecast

                # 예측 데이터가 있을 경우에만 추가
                if future_times:
                    new_predicted_data_power = dict(time=future_times, predicted=predicted_values)
                    source_predicted_power.stream(new_predicted_data_power, rollover=200)

                    # 누적 예측 전력 소비량 및 비용 계산
                    cumulative_energy = cumulative_actual_power_kwh[-1] if cumulative_actual_power_kwh else 0
                    for i in range(len(future_times)):
                        if i == 0:
                            delta_time = (future_times[i] - df['ds'].max()).total_seconds() / 3600
                        else:
                            delta_time = (future_times[i] - future_times[i-1]).total_seconds() / 3600
                        energy = predicted_values[i] * delta_time
                        cumulative_energy += energy
                        cumulative_predicted_power_kwh.append(cumulative_energy)
                        # 비용 계산
                        total_cost = calculate_total_cost(cumulative_energy, future_times[i].month)
                        cumulative_predicted_cost.append(total_cost)
                        # Bokeh에 예측 비용 추가
                        source_predicted_cost.stream({'time': [future_times[i]], 'predicted_cost': [total_cost]}, rollover=200)

                        # 임계값 비교 및 이상치 표시
                        if total_cost > TARGET_MONTHLY_COST:
                            source_anomaly.stream({'time': [future_times[i]], 'anomaly': [total_cost]}, rollover=200)
                            update_prediction(total_cost)
                        else:
                            update_prediction(total_cost)
                else:
                    update_prediction(None)

                # 리스트 조정 (메모리 관리)
                adjusted_powers_kw = adjusted_powers_kw[-100:]
                timestamps = timestamps[-100:]
                cumulative_actual_power_kwh = cumulative_actual_power_kwh[-100:]
                cumulative_actual_cost = cumulative_actual_cost[-100:]
                cumulative_predicted_power_kwh = cumulative_predicted_power_kwh[-100:]
                cumulative_predicted_cost = cumulative_predicted_cost[-100:]
            else:
                update_prediction(None)
        else:
            # 새로운 데이터가 없을 경우
            update_prediction(None)

    except Exception as e:
        print("오류 발생:", e)
        import traceback
        traceback.print_exc()


def modify_doc(doc):
    global prediction_panel, TARGET_MONTHLY_COST

    # Div 생성: 대시보드 제목
    title_div = Div(
        text="<h1>🔮나의 전기요금 예언자🔮</h1>",
        styles={"text-align": "center", "font-size": "30px", "color": "#2c3e50", "margin-bottom": "25px", "font-family": "Arial, Helvetica, sans-serif"}
    )

    # 사용자 임계값 입력 위젯
    cost_input = TextInput(value=str(TARGET_MONTHLY_COST), title="월간 비용 한도(원):")
    update_button = Button(label="한도 업데이트", button_type="success")

    # 한도 업데이트 시 호출할 함수
    def update_threshold():
        global TARGET_MONTHLY_COST
        try:
            new_threshold = float(cost_input.value)
            TARGET_MONTHLY_COST = new_threshold
            # threshold_line_cost 업데이트
            threshold_line_cost.location = TARGET_MONTHLY_COST
            # 예측 패널 업데이트
            update_prediction(None)
        except ValueError:
            pass

    update_button.on_click(update_threshold)

    # 임계값 정보 패널
    threshold_info_panel = Div(
        text=f"""
        <div style='border: 1px solid #bdc3c7; padding: 15px; text-align: center; width: 400px; margin: 0 auto; background-color: #ecf0f1;'>
            <ul style='margin: 0; padding: 0; font-size: 16px; line-height: 2; list-style: none; color: #2c3e50;'>
                <li><b>1구간 요금:</b> {RATE_PER_KWH1} 원/kWh</li>
                <li><b>2구간 요금:</b> {RATE_PER_KWH2} 원/kWh</li>
                <li><b>3구간 요금:</b> {RATE_PER_KWH3} 원/kWh</li>
                <li><b>1구간 기본 요금:</b> {BASE_RATE_TIER1} 원</li>
                <li><b>2구간 기본 요금:</b> {BASE_RATE_TIER2} 원</li>
                <li><b>3구간 기본 요금:</b> {BASE_RATE_TIER3} 원</li>
            </ul>
        </div>
        """,
        styles={"margin-top": "0px"}
    )

    # 전력 소비량 그래프
    tools = "pan,wheel_zoom,box_zoom,reset,save"
    tooltips_power = [
        ("시간", "@time{%F %T}"),
        ("실제 전력", "@actual{0.000} kW"),
    ]
    hover_tool_power = HoverTool(tooltips=tooltips_power, formatters={'@time': 'datetime'})

    plot_power = figure(title="전력 소비량", x_axis_type='datetime', x_axis_label='시간', y_axis_label='전력 소비량 (kW)', width=800, height=400, tools=[tools, hover_tool_power], background_fill_color="#ecf0f1")

    plot_power.line('time', 'actual', source=source_actual_power, line_width=2, legend_label='실제 전력 소비량', color='#2980b9')
    plot_power.legend.location = 'top_left'
    plot_power.legend.click_policy = 'hide'

    # x축 자동 조정 설정 해제
    plot_power.x_range.follow = None
    plot_power.x_range.range_padding = 0

    # 비용 그래프
    tooltips_cost = [
        ("시간", "@time{%F %T}"),
        ("실제 비용", "@actual_cost{0,0} 원"),
        ("예측 비용", "@predicted_cost{0,0} 원"),
        ("임계값 초과", "@anomaly{0,0} 원"),
    ]
    hover_tool_cost = HoverTool(tooltips=tooltips_cost, formatters={'@time': 'datetime'})

    plot_cost = figure(title="누적 비용 (실제 vs 예측)", x_axis_type='datetime', x_axis_label='시간', y_axis_label='비용 (원)', width=800, height=400, tools=[tools, hover_tool_cost], background_fill_color="#ecf0f1")
    plot_cost.line('time', 'actual_cost', source=source_actual_cost, line_width=2, legend_label='실제 비용', color='#2980b9')
    plot_cost.line('time', 'predicted_cost', source=source_predicted_cost, line_width=2, legend_label='예측 비용', color='#e74c3c')

    # 임계값 라인
    threshold_line_cost = Span(location=TARGET_MONTHLY_COST, dimension='width', line_color='#e74c3c', line_dash='dashed', line_width=2)
    plot_cost.add_layout(threshold_line_cost)

    # 이상치 표시
    plot_cost.circle('time', 'anomaly', source=source_anomaly, size=10, color='#e74c3c', legend_label='임계값 초과')
    plot_cost.legend.location = 'top_left'
    plot_cost.legend.click_policy = 'hide'

    # 비용 그래프의 x축을 전력 소비량 그래프와 동기화
    plot_cost.x_range = plot_power.x_range

    # 레이아웃 구성
    layout = column(
        title_div,
        row(
            column(
                row(cost_input, update_button),
                plot_power,
                plot_cost,
                sizing_mode="stretch_width"
            ),
            column(
                Div(text="<h2 style='text-align: center; font-size: 20px; color: #2c3e50;'>현재 전기요금 정보</h2>", styles={"margin-bottom": "10px"}),
                threshold_info_panel,
                width=400,
            )
        ),
        Div(text="<h2 style='text-align: center; font-size: 20px; color: #2c3e50;'>예측 결과</h2>", styles={"margin-top": "20px"}),
        prediction_panel,
    )

    doc.add_root(layout)
    doc.add_periodic_callback(data_collection_loop, 5000)  # 데이터 수집 주기를 5초로 설정
    doc.title = "Power Consumption Prediction"


app = Application(FunctionHandler(modify_doc))

def run_server():
    server = Server({'/': app}, port=5006)
    server.start()
    print("Bokeh 서버가 실행 중입니다. http://localhost:5006/ 에서 확인하세요.")
    server.io_loop.add_callback(server.show, "/")
    server.io_loop.start()

if __name__ == "__main__":
    run_server()
