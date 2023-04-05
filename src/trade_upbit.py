from pyupbit import get_ohlcv, get_tickers, Upbit
from loguru import logger as log
import asyncio
import os
import json
import time
import websockets
from websockets.exceptions import ConnectionClosedError
from datetime import datetime
from pandas import Series
from pandas import DataFrame
from pymongo import MongoClient

client = MongoClient("mongodb://root:tiger12@127.0.0.1:27017/?authSource=admin")
coin_db = client['coin']
target_coll = coin_db['target']
signal_coll = coin_db['signal']

# TEST용
ACCESS_KEY = ''
SECRET_KEY = ''

def get_tickers_by(currency: str) -> list:
    tickers = get_tickers(fiat=f'{currency}')
    return tickers


# this executable is a decision function for the algorithm
def make_signal(target:dict, price_data:dict, krw_balance:dict, coin_balance:dict, capital=300_000, maximum_long=3, maximum_short=3):
    """
    target = turtle로 그한 변동성
    price_data = 현재 시가에 대한 데이터
    capital = 내가 처음 시작한 금액 30만원
    maximum_long = the maximum quantity that can be purchased in any one action
    maximum_short = maximum quantity that can be sold in any one action (note the shortselling restriction)
    """

    # target 데이터의 long_top, short_top이 price_data['trade_price']가 넘었을 때 매수
    # long인지, short인지 구분해야함 -> 탈출 가격이 있기 때문에!
    # type이 buy, sell을 나눠서 저장해주기.

    long_top = target['long_top'] if 'long_top' in target else 0
    short_top = target['short_top'] if 'short_top' in target else 0
    trade_price = price_data['trade_price'] if 'trade_price' in price_data else 0
    result_buy = {'_id':f'{target["name"]}-buy', 'target_date':target['date'], 'ATR':target['ATR'], 'trade':'buy'}
    result_sell = {'_id':f'{target["name"]}-sell', 'target_date':target['date'], 'ATR':target['ATR'], 'trade':'sell'}

    """
    target = {
        "name": "KRW-BTC",
        "date": 1618151291,
        "close": 77778000,
        "volume": 104.49281076,
        "TR1": 245000,
        "TR2": 134000,
        "TR3": 111000,
        "TR": 134000,
        "ATR": 426250,
        "short_top": 79320000,
        "short_bottom": 77184000,
        "long_top": 79337000,
        "long_bottom": 77184000
    }
    """
    # buy!!
    if long_top > trade_price:
        result_buy['price'] = target['long_top']
        result_buy['type'] = 'long'
        result_sell['price'] = target['long_bottom']
        result_sell['type'] = 'long'
        maximum_trade = maximum_long
    if short_top > trade_price:
        result_buy['price'] = target['short_top']
        result_buy['type'] = 'short'
        result_sell['price'] = target['short_bottom']
        result_sell['type'] = 'short'
        maximum_trade = maximum_short

    for idx in range(1, maximum_trade+1):
        # NOTE 2ATR을 사용한다. 나중에 수정해야한다면 이 부분을 수정.
        result_buy[f'{idx}_ATR'] = result_buy['price'] + (target['ATR'] * idx * 2)
        
    return result_buy, result_sell


def read_target(ticker:str):
    ''' target에서 10분전에 저장한 ticker를 읽어다가 그 중 제일 최신 target price를 가지고 온다.
    '''
    current_time = int(datetime.today().timestamp())
    log.info(f'ticker:{ticker}, current_time: {current_time}')
    # TODO test
    rows = list(target_coll.find({ 'name':f'{ticker}', 'date': {'$gte': current_time-(60*60*3+60), '$lte':current_time} }))
    rows.sort(key=lambda x: x['date'], reverse=True) # date가 큰 수로 정렬
    return rows[0] if len(rows) > 0 else {} # 제일 큰 수


def get_balance():
    upbit = Upbit(ACCESS_KEY, SECRET_KEY)
    return upbit.get_balances()



async def upbit_ws_client(tickers:list):
    uri = "wss://api.upbit.com/websocket/v1"

    async with websockets.connect(uri) as websocket:
        subscribe_fmt = [ 
            {"ticket":"test"},
            {
                "type": "ticker",
                "codes": tickers,
                "isOnlyRealtime": True
            }
        ]
        subscribe_data = json.dumps(subscribe_fmt)
        await websocket.send(subscribe_data)
        
        pingpong_count = 0
        while True:
            try:
                log.info(f'pingpong_count: {pingpong_count}')
                tp_data = await websocket.recv()
                # log.info() # tp -> trade_price (현재가) 추출하기..
                ws_data = json.loads(tp_data)
                log.info(f'ws_data: {ws_data}')
                log.info(f'acc_trade_price_24h: {ws_data["acc_trade_price_24h"]}')

                target = read_target(ws_data['code'])
                log.info(f'target: {target}')

                # 24시간 누적 거래대금
                ACC_TRADE_PRICE = 1000.0 # NOTE 100,000백만 거래량
                if target and ws_data['acc_trade_price_24h'] > ACC_TRADE_PRICE:
                    # 타겟, 현재 가격, 계좌 잔액
                    balance_all = get_balance()
                    log.info(f'balance_all: {balance_all}')
                    curr_coin = ws_data['code'].split('-')[-1]

                    krw_balance = [ bal for bal in balance_all if bal['currency'] == 'KRW' ][0]
                    coin_balance = [ bal for bal in balance_all if bal['currency'] == curr_coin ]

                    # 현재 실시간으로 받은 데이터의 코인.
                    coin_balance = coin_balance[0] if len(coin_balance) >= 1 else {}

                    log.info(f'KRW balance: {krw_balance["balance"]}')
                    log.info(f'{curr_coin} balance: {coin_balance}')

                    # NOTE filter by vol "candle_acc_trade_volume" -> "volume" (거래량) 비트코인 기준 150~200 이상이면 거래 가능할것 같음.
                    buy_signal, sell_signal = make_signal(target=target, price_data=ws_data, krw_balance=krw_balance, coin_balance=coin_balance)
                    
                    # signal에 해당 코인이 있는지 확인
                    _signal = list(signal_coll.find({ '_id':f'{ws_data["code"]}-buy' }))
                    if len(_signal) > 0:
                        signal_coll.replace_one({'_id':f'{ws_data["code"]}-buy', 'trade':'buy'}, buy_signal)
                        signal_coll.replace_one({'_id':f'{ws_data["code"]}-sell', 'trade':'sell'}, sell_signal)
                    else:
                        signal_coll.insert_one(buy_signal)
                        signal_coll.insert_one(sell_signal)
                
                # websocket의 반복은 0.2초 마다
                time.sleep(0.2)
                pingpong_count +=1
                if pingpong_count >= 120:
                    log.info('PING~ PONG~ toss')
                    pingpong_count = 0
                    await websocket.send(subscribe_data)
            except ConnectionClosedError as e:
                log.info('ConnectionClosedError retry..!!')
                await websocket.send(subscribe_data)
                continue
            
        return data


if __name__ == '__main__':
    tickers = get_tickers_by('KRW')
    # Get target tickers...
    turtle_list = ['KRW-ATOM', 'KRW-BTC'] if False else tickers
    log.info(f'tickers: {turtle_list}')

    # loop
    asyncio.run(upbit_ws_client(turtle_list))

