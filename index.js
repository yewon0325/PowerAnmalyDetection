const admin = require('firebase-admin');
const XLSX = require('xlsx');
const path = require('path');
const fs = require('fs');

// Firebase Admin SDK 초기화
const serviceAccount = require('./anomaly-detection-9939e-firebase-adminsdk-l9emo-0138e39dc1.json');
admin.initializeApp({
  credential: admin.credential.cert(serviceAccount),
  databaseURL: 'https://anomaly-detection-9939e-default-rtdb.asia-southeast1.firebasedatabase.app/'
});

const db = admin.database();

// CSV 파일 읽기
const csvFilePath = path.join(__dirname, './weekly_household_energy_consumption_with_date.csv');
const csvData = fs.readFileSync(csvFilePath, 'utf8');

// CSV 데이터를 JSON으로 변환
const rows = csvData.split('\n');
const headers = rows.shift().split(',');
const jsonData = rows.map(row => {
  const values = row.split(',');
  let obj = {};
  headers.forEach((header, index) => {
    let value = values[index]?.trim();
    obj[header.trim()] = value; // 변환 없이 그대로 사용
  });
  return obj;
});

// 데이터 삽입 함수
let index = 0;
const insertData = () => {
  if (index >= jsonData.length) {
    console.log('모든 데이터가 업로드되었습니다.');
    clearInterval(intervalId); // 모든 데이터 업로드 후 타이머 종료
    return;
  }
  
  const data = jsonData[index];
  // Firebase에 데이터 삽입
  db.ref('power_consumption').push(data, (error) => { 
    if (error) {
      console.error('데이터 삽입 실패:', error);
    } else {
      console.log(`데이터 삽입 성공: ${JSON.stringify(data)}`);
    }
  });

  index++;
};

// 1초마다 데이터 삽입
const intervalId = setInterval(insertData, 1000);
