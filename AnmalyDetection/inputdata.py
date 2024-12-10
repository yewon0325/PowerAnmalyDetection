import time
import random
import firebase_admin
from firebase_admin import credentials, db
from datetime import datetime

# Firebase Admin SDK 초기화
if not firebase_admin._apps:
    cred = credentials.Certificate('')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 
    })

# 데이터 추가 함수
# 데이터 추가 함수
def push_data_to_firebase():
    ref = db.reference('power_consumption')
    while True:
        try:
            # 임의의 전력 소비량 데이터를 생성
            power_consumption = round(random.uniform(0.2, 1.0), 6)  # 0.2 ~ 1.0 kW 범위의 임의의 값
            timestamp = datetime.now().timestamp()  # Unix 타임스탬프 사용

            # 데이터 구조 정의
            data = {
                'PowerConsumption': power_consumption,
                'Timestamp': timestamp
            }

            # Firebase에 데이터 푸시
            ref.push(data)
            print(f"Data pushed to Firebase: {data}")

            # 1초마다 데이터 추가
            time.sleep(1)
        except Exception as e:
            print(f"Error pushing data to Firebase: {e}")
            time.sleep(1)

if __name__ == "__main__":
    push_data_to_firebase()
