from pyupbit import get_ohlcv
from pyupbit import get_tickers
from loguru import logger as log
import asyncio
import os
import json
import time
from datetime import datetime
from pandas import Series
from pandas import DataFrame
from pymongo import MongoClient

client = MongoClient("mongodb://root:tiger12@127.0.0.1:27017/?authSource=admin")
coin_db = client['coin']
target_coll = coin_db['target']

def get_tickers_by(currency: str) -> list:
    tickers = get_tickers(fiat=f'{currency}')
    return tickers


def get_hour_price(ticker:list) -> dict:
    return ticker, get_ohlcv(ticker=ticker, interval='minute240', count=60)


def calculate_target_price(dataset: DataFrame, length=100) -> dict:
    """ default length: 100
    
    dataset:
                           open        high         low       close      volume
    2021-03-26 16:00:00  64350000.0  65050000.0  64198000.0  65050000.0  775.357399
    2021-03-26 17:00:00  65050000.0  65210000.0  64600000.0  64830000.0  580.670101
    2021-03-26 18:00:00  64830000.0  65020000.0  64550000.0  64557000.0  480.497441
    2021-03-26 19:00:00  64567000.0  64742000.0  64310000.0  64594000.0  319.459206
    2021-03-26 20:00:00  64604000.0  64628000.0  63601000.0  63710000.0  546.593272

    """

    action = DataFrame(index=dataset.index)

    action['close'] = dataset['close']
    action['volume'] = dataset['volume']
    action['TR1'] = abs(dataset['low']-dataset['high'])
    action['TR2'] = abs(dataset.shift(1)['close']-dataset['high'])
    action['TR3'] = abs(dataset.shift(1)['close']-dataset['low'])

    action.loc[action['TR1'] > action['TR2'], 'TR'] = action['TR1']
    action.loc[action['TR2'] > action['TR3'], 'TR'] = action['TR2']
    action.loc[action['TR3'] > action['TR1'], 'TR'] = action['TR3']

    # drop NaN row
    action = action.dropna(axis=0)

    # ATR (변동성 평균)
    action['ATR'] = action['TR3'].rolling(20).mean()

    # 터틀 규칙
    action['short_top'] = action['close'].rolling(20).max() # S1. 보통의 추세 - 4주간 (20일) 최고점을 돌파하면 매수
    action['short_bottom'] = action['close'].rolling(10).min() # 2주간(10일) 최저점 밑으로 돌파 시 매도
    action['long_top'] = action['close'].rolling(55).max() # S2. 큰 추세 - 11주간 (55일) 최고점을 돌파하면 매수
    action['long_bottom'] = action['close'].rolling(20).min() # 4주간(20일) 최저점 밑으로 돌파 시 매도

    # drop NaN row
    action = action.dropna(axis=0)
    log.info(f'action: \n{action.tail(1)}')
    
    return action[-1:] # 제일 최신의 row만 사용한다.


if __name__ == '__main__':
    # 원하는 코인의 매수 매매 가격을 계산한다.
    # python cal_target.py 
    tickers = get_tickers_by('KRW')
    
    # Get target tickers...
    turtle_list = ['KRW-BTC', 'KRW-ATOM'] if False else tickers
    log.info(f'tickers: {turtle_list}')
    cal_signal = {}
    while True:
        # get dataset with coins
        hour_bars = ( get_hour_price(ticker) for ticker in turtle_list )

        for ticker, hour_bar in hour_bars:
            log.info(f'ticker: {ticker}')
            body_row = calculate_target_price(hour_bar).to_dict('records')

            if len(body_row) > 0:
                current_time = int(datetime.today().timestamp())
                body = body_row[0] 

                coin_row = {'name':f'{ticker}', 'date':current_time, **body}
                log.info(f'coin_row: {coin_row}')
                
                coin_pk = target_coll.insert_one(coin_row).inserted_id
                log.info(f'coin_pk: {coin_pk}')
            # 약 120개의 코인을 0.5초 단위로 탐색
            time.sleep(0.2)
        
        # 모든 코인의 스캔을 마쳤으면 1시간 단위 가격 크롤링이기 때문에 10분 단위로 탐색
        log.info('Finished coin scan!!')
        time.sleep(60*10)


    






    