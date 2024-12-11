FROM python:3.10-slim


# 작업 디렉토리 설정
WORKDIR /app

# 리눅스 패키지 업데이트 및 필요한 빌드 도구 설치
RUN apt-get update && apt-get install -y \
    build-essential \
    gcc \
    make \
    libffi-dev \
    libssl-dev \
    libxml2-dev \
    libxslt1-dev \
    zlib1g-dev \
    libcurl4-openssl-dev \
    libstdc++6 \
    libgcc-12-dev \
    && apt-get clean

# requirements.txt 복사
COPY requirements.txt /app/

# Python 패키지 설치
RUN pip install --upgrade pip
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . /app/

# Bokeh 서버 포트 오픈 (필요한 경우)
EXPOSE 5006

# 컨테이너 실행 시 detect.py 실행
CMD ["python", "detect.py"]
