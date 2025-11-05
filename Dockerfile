FROM python:3.10.19-trixie

WORKDIR /app

RUN pip install --no-cache-dir requests flask yfinance apscheduler

EXPOSE 81

CMD ["python", "app/app.py"]
