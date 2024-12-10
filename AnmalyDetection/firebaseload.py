from datetime import datetime
from firebase_admin import db

def get_new_data(last_timestamp):
    ref = db.reference('power_consumption')
    if last_timestamp:
        data_snapshot = ref.order_by_child('Timestamp').start_at(last_timestamp + 0.000001).get()
    else:
        data_snapshot = ref.order_by_child('Timestamp').get()

    if data_snapshot is None:
        data_snapshot = {}

    new_data = {}
    for key in data_snapshot:
        data_point = data_snapshot[key]
        timestamp = data_point.get('Timestamp')
        if timestamp is not None:
            try:
                timestamp = float(timestamp)
            except (ValueError, TypeError):
                print(f"Invalid timestamp value for key {key}: {timestamp}")
                continue  # 해당 데이터 건너뜀
            if last_timestamp is None or timestamp > last_timestamp:
                data_point['Timestamp'] = timestamp  # 변환된 timestamp로 업데이트
                new_data[key] = data_point

    if new_data:
        new_last_timestamp = max(data_point['Timestamp'] for data_point in new_data.values())
    else:
        new_last_timestamp = last_timestamp

    return new_data, new_last_timestamp

def process_data(data):
    keys = []
    timestamps = []
    power_values = []
    for key, val in data.items():
        if 'Timestamp' in val and 'PowerConsumption' in val:
            try:
                timestamp = float(val['Timestamp'])
                power_value = float(val['PowerConsumption'])
                timestamp_dt = datetime.fromtimestamp(timestamp)
                timestamps.append(timestamp_dt)
                power_values.append(power_value)
                keys.append(key)
            except (ValueError, TypeError) as e:
                print(f"Error processing data for key {key}: {e}")
                continue
        else:
            print(f"Data with key {key} is missing 'Timestamp' or 'PowerConsumption'")
    return keys, timestamps, power_values
