"""
fetch_data.py
개인용 증시 데일리 브리핑 - 데이터 수집 스크립트

하는 일:
  1) 지수(KOSPI, KOSDAQ, S&P500, NASDAQ)와 환율(USD/KRW)을 가져온다
  2) 고정 관심종목 3개(삼성전자/SK하이닉스/삼성전기)의 가격·전일종가·7일추세를 가져온다
  3) 미국 반도체 후보 중 '오늘 거래량' 상위 3개를 고른다
  4) 코스피 전체 종목 중 '오늘 거래량' 상위 3개를 고른다
  5) 위 결과를 화면(React)이 읽을 data.json 파일로 저장한다

뉴스/호재·악재/등락키워드는 LLM이 필요해서 3단계에서 추가한다(지금은 빈 값).
"""

import json
from datetime import datetime, timedelta

import FinanceDataReader as fdr   # 한국 지수·개별종목·환율
import yfinance as yf             # 미국 종목
from pykrx import stock as krx    # 코스피 거래량 순위

# ── 설정 ─────────────────────────────────────────────
FIXED = [                         # 항상 보여줄 고정 종목 (코드, 표시이름, 로고텍스트)
    ("005930", "삼성전자", "삼전"),
    ("000660", "SK하이닉스", "SK"),
    ("009150", "삼성전기", "전기"),
]
US_SEMI = [                       # 미국 반도체 후보 (이 중 거래량 상위 3개만 노출)
    ("NVDA", "NVIDIA", "NV"),
    ("AMD", "AMD", "AMD"),
    ("MU", "Micron", "MU"),
    ("AVGO", "Broadcom", "AVGO"),
    ("INTC", "Intel", "INTC"),
]
TREND_DAYS = 7                    # 미니 선그래프에 쓸 최근 거래일 수


def pct(today, prev):
    """전일 대비 등락률(%) 계산"""
    if prev in (0, None):
        return 0.0
    return round((today - prev) / prev * 100, 2)


def get_indices_and_fx():
    """지수 4개 + 환율 1개"""
    today = datetime.now()
    start = (today - timedelta(days=10)).strftime("%Y-%m-%d")

    def last_two(symbol):
        df = fdr.DataReader(symbol, start)
        closes = df["Close"].dropna()
        return float(closes.iloc[-1]), float(closes.iloc[-2])

    specs = [
        ("KOSPI", "KS11"),
        ("KOSDAQ", "KQ11"),
        ("S&P 500", "US500"),
        ("NASDAQ", "IXIC"),
    ]
    indices = []
    for name, sym in specs:
        cur, prev = last_two(sym)
        indices.append({"name": name, "value": round(cur, 2), "change": pct(cur, prev)})

    usdkrw_cur, usdkrw_prev = last_two("USD/KRW")
    fx = {"name": "USD/KRW", "value": round(usdkrw_cur, 2), "change": pct(usdkrw_cur, usdkrw_prev)}
    return indices, fx


def get_kr_stock(code):
    """한국 개별종목: 현재가, 전일종가, 7일 추세, 거래량"""
    start = (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d")
    df = fdr.DataReader(code, start).dropna()
    closes = df["Close"].astype(float)
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    trend = [round(v / price, 4) for v in closes.tail(TREND_DAYS)]  # 마지막=1.0 기준 비율
    volume = int(df["Volume"].iloc[-1])
    return {"price": round(price, 2), "change": pct(price, prev),
            "prevClose": round(prev, 2), "trend": trend, "volume": volume}


def get_us_stock(ticker):
    """미국 개별종목: 현재가, 전일종가, 7일 추세, 거래량"""
    df = yf.Ticker(ticker).history(period="1mo").dropna()
    closes = df["Close"].astype(float)
    price = float(closes.iloc[-1])
    prev = float(closes.iloc[-2])
    trend = [round(v / price, 4) for v in closes.tail(TREND_DAYS)]
    volume = int(df["Volume"].iloc[-1])
    return {"price": round(price, 2), "change": pct(price, prev),
            "prevClose": round(prev, 2), "trend": trend, "volume": volume}


def build_stock(group, code, name, logo, data):
    return {"group": group, "name": name, "code": code, "logo": logo,
            "price": data["price"], "change": data["change"],
            "prevClose": data["prevClose"], "trend": data["trend"],
            "volume": data["volume"], "reasons": []}  # reasons는 3단계에서 채움


def get_kospi_volume_top3():
    """코스피 전체 종목 중 오늘 거래량 상위 3개"""
    # 최근 영업일 찾기 (주말/휴일 대비 며칠 역으로 시도)
    for back in range(0, 7):
        day = (datetime.now() - timedelta(days=back)).strftime("%Y%m%d")
        try:
            df = krx.get_market_ohlcv(day, market="KOSPI")
            if df is not None and not df.empty and df["거래량"].sum() > 0:
                break
        except Exception:
            continue
    top = df.sort_values("거래량", ascending=False).head(3)
    result = []
    for code, row in top.iterrows():
        name = krx.get_market_ticker_name(code)
        result.append(build_stock("kospi_top", code, name, name[:2], {
            "price": round(float(row["종가"]), 2),
            "change": round(float(row["등락률"]), 2),
            "prevClose": round(float(row["종가"]) - float(row["변동폭"]), 2)
                          if "변동폭" in row else round(float(row["종가"]), 2),
            "trend": [1.0] * TREND_DAYS,   # 순위 종목 추세는 간략화(원하면 개별 조회로 확장)
            "volume": int(row["거래량"]),
        }))
    return result


def main():
    indices, fx = get_indices_and_fx()

    stocks = []
    # 1~3 고정
    for code, name, logo in FIXED:
        stocks.append(build_stock("fixed", code, name, logo, get_kr_stock(code)))

    # 4~6 미국 반도체 거래량 TOP3
    us = []
    for ticker, name, logo in US_SEMI:
        d = get_us_stock(ticker)
        us.append((d["volume"], build_stock("us_semi", ticker, name, logo, d)))
    us.sort(key=lambda x: x[0], reverse=True)
    stocks.extend([s for _, s in us[:3]])

    # 7~9 코스피 거래량 TOP3
    stocks.extend(get_kospi_volume_top3())

    payload = {
        "updatedAt": datetime.now().isoformat(timespec="seconds"),
        "indices": indices,
        "fx": fx,
        "stocks": stocks,
        "news": [],     # 3단계에서 채움
        "summary": "",  # 3단계에서 채움
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"data.json 저장 완료 · 종목 {len(stocks)}개 · {payload['updatedAt']}")


if __name__ == "__main__":
    main()
