import firebase_admin
from firebase_admin import credentials, db

# Firebase Admin SDK 초기화
cred = credentials.Certificate('json파일명')
firebase_admin.initialize_app(cred, {
    'databaseURL': '인증키'
})


# 데이터 삭제 (예: 'power_consumption' 경로의 전체 데이터 삭제)
ref = db.reference('power_consumption')
ref.delete()  # 전체 데이터 삭제
print("데이터가 삭제되었습니다.")