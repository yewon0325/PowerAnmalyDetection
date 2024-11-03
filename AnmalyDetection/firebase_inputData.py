import firebase_admin
from firebase_admin import credentials, db
import csv
import time
import os

# Firebase Admin SDK 초기화
cred = credentials.Certificate('json파일명')
firebase_admin.initialize_app(cred, {
    'databaseURL': '인증키'
})

# CSV 파일 읽기
csv_file_path = os.path.join(os.path.dirname(__file__), './weekly_household_energy_data.csv')
json_data = []

with open(csv_file_path, newline='', encoding='utf-8') as csvfile:
    reader = csv.DictReader(csvfile)
    for row in reader:
        json_data.append(row)

# 데이터 삽입 함수
index = 0

def insert_data():
    global index
    if index >= len(json_data):
        print('모든 데이터가 업로드되었습니다.')
        return False  # 타이머 종료를 위해 False 반환

    data = json_data[index]
    # Firebase에 데이터 삽입
    ref = db.reference('power_consumption')
    try:
        ref.push(data)
        print(f'데이터 삽입 성공: {data}')
    except Exception as err:
        print('데이터 삽입 실패:', err)

    index += 1
    return True  # 다음 데이터 삽입을 위해 True 반환

# 1초마다 데이터 삽입
while insert_data():
    time.sleep(1)
