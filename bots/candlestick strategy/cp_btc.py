# === LOGGER SETUP ===
import logging

# Set up logging with UTF-8 encoding
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()])
logging.getLogger().handlers[0].setStream(open('CON', 'w', encoding='utf-8'))

logging.info("✅ MT5 initialized successfully.")

import MetaTrader5 as mt5
import pandas as pd
import time
import talib
import threading
from datetime import datetime, timedelta

# === CONSTANTS ===
SYMBOL = "BTCUSDm"
TIMEFRAME = mt5.TIMEFRAME_M5
timeframe_to_next_candle_minutes = 5
LOT_SIZE = 0.05
MAGIC_NUMBER = 10005
LOG_FILE = "trade_log.txt"
PROFIT_TARGET = 500  # 💰 Target profit in USD
INITIAL_BALANCE = None  # 🔒 Will be set after login

# Define trading start and end times
start_time = datetime.strptime("23:00", "%H:%M").time()  
end_time = datetime.strptime("6:00", "%H:%M").time()    

# === MT5 CONNECT ===
def connect_mt5():
    global INITIAL_BALANCE
    if not mt5.initialize(
        login=242864620,
        password="Password1234.",
        server="Exness-MT5Trial"
    ):
        print("❌ MT5 initialization/login failed!")
        quit()
        
    print("✅ MT5 initialized and logged in successfully.")
    account_info = mt5.account_info()
    INITIAL_BALANCE = account_info.balance
    print(f'✅ Initial Balance: {INITIAL_BALANCE}')
    if not account_info:
        print("❌ Unable to fetch account info.")
        quit()

# === (Rest of your existing code remains unchanged — insert check below into main loop) ===

def wait_for_next_candle():
    now = datetime.now()
    seconds_in_timeframe = timeframe_to_next_candle_minutes * 60
    seconds_since_epoch = int(now.timestamp())
    seconds_to_next_candle = seconds_in_timeframe - (seconds_since_epoch % seconds_in_timeframe)
    # print(f"⏳ Waiting {seconds_to_next_candle}s for next candle...")
    time.sleep(seconds_to_next_candle)

# === IDENTIFY TRADE SIGNALS === SHOOTING STAR, HAMMER, DOJI
def generate_signals(df):
    signal = None
    entry_price = None
    stop_loss = None
    take_profit = None

    if len(df) < 6:
        return signal, entry_price, stop_loss, take_profit

    # Candle pattern indicators
    df['hammer'] = talib.CDLHAMMER(df['open'], df['high'], df['low'], df['close'])
    df['inverted_hammer'] = talib.CDLINVERTEDHAMMER(df['open'], df['high'], df['low'], df['close'])
    df['hanging_man'] = talib.CDLHANGINGMAN(df['open'], df['high'], df['low'], df['close'])
    df['shooting_star'] = talib.CDLSHOOTINGSTAR(df['open'], df['high'], df['low'], df['close'])
    df['dragonfly_doji'] = talib.CDLDRAGONFLYDOJI(df['open'], df['high'], df['low'], df['close'])
    df['gravestone_doji'] = talib.CDLGRAVESTONEDOJI(df['open'], df['high'], df['low'], df['close'])
    df['long_legged_doji'] = talib.CDLLONGLEGGEDDOJI(df['open'], df['high'], df['low'], df['close'])
    df['marubozu'] = talib.CDLMARUBOZU(df['open'], df['high'], df['low'], df['close'])
    df['spinning_top'] = talib.CDLSPINNINGTOP(df['open'], df['high'], df['low'], df['close'])
    df['takuri'] = talib.CDLTAKURI(df['open'], df['high'], df['low'], df['close'])
    df['rickshawman'] = talib.CDLRICKSHAWMAN(df['open'], df['high'], df['low'], df['close'])
    df['engulfing'] = talib.CDLENGULFING(df['open'], df['high'], df['low'], df['close'])

    # Previous 3 candles
    prev_3 = df.iloc[-5]
    prev_2 = df.iloc[-4]
    prev_1 = df.iloc[-3]

    # Signal candle
    signal_candle = df.iloc[-2]

    # Trend setup
    three_bearish = all([c['close'] < c['open'] for c in [prev_3, prev_2, prev_1]])
    three_bullish = all([c['close'] > c['open'] for c in [prev_3, prev_2, prev_1]])

    # Define bullish signal conditions
    bullish_patterns = [
        signal_candle['spinning_top'],        # neutral
        signal_candle['long_legged_doji'],    # neutral
        signal_candle['dragonfly_doji'],      # bullish
        signal_candle['hammer'],              # bullish
        signal_candle['inverted_hammer'],     # bullish
        signal_candle['takuri'],           # bullish (if white)
        signal_candle['spinning_top'],        # neutral
        signal_candle['long_legged_doji']     # neutral
    ]


    # Define bearish signal conditions
    bearish_patterns = [
        signal_candle['spinning_top'],        # neutral
        signal_candle['long_legged_doji'],    # neutral
        signal_candle['gravestone_doji'],     # bearish
        signal_candle['shooting_star'],       # bearish
        signal_candle['hanging_man'],         # bearish (if black)
        signal_candle['spinning_top'],        # neutral
        signal_candle['long_legged_doji']     # neutral
    ]


    # BUY signal
    if three_bearish and any(p > 0 for p in bullish_patterns):
        signal = "BUY"
        entry_price = df.iloc[-1]['open']

    # SELL signal
    elif three_bullish and any(p < 0 for p in bearish_patterns):
        signal = "SELL"
        entry_price = df.iloc[-1]['open']

    if signal:
        stop_loss, take_profit = predict_sl_tp(df, entry_price, signal)

    return signal, entry_price, stop_loss, take_profit

# === FETCH MARKET DATA ===
def get_data(symbol, timeframe, count=100):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None:
        print(f"❌ No data for {symbol}. Check symbol name!")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# === CALCULATE ATR (Average True Range) ===
def calculate_atr(dataframe, period=14):
    dataframe['high-low'] = dataframe['high'] - dataframe['low']
    dataframe['high-close'] = abs(dataframe['high'] - dataframe['close'].shift(1))
    dataframe['low-close'] = abs(dataframe['low'] - dataframe['close'].shift(1))
    dataframe['true_range'] = dataframe[['high-low', 'high-close', 'low-close']].max(axis=1)
    dataframe['ATR'] = dataframe['true_range'].rolling(period).mean()
    return dataframe

# === AI-BASED SL/TP CALCULATION ===
def predict_sl_tp(dataframe, entry_price, signal):
    atr = dataframe.iloc[-1]['ATR']
    support = dataframe['low'].rolling(10).min().iloc[-1]
    resistance = dataframe['high'].rolling(10).max().iloc[-1]

    if signal == "BUY":
        stop_loss = max(support, entry_price - (atr * 1.5))
        take_profit = entry_price + ((entry_price - stop_loss) * 2)
    else:
        stop_loss = min(resistance, entry_price + (atr * 1.5))
        take_profit = entry_price - ((stop_loss - entry_price) * 2)

    return stop_loss, take_profit

# === LOG TRADE SIGNAL ===
def log_trade_signal(signal, entry_price, stop_loss, take_profit):
    with open(LOG_FILE, "a") as file:
        file.write(f"{datetime.now()} | {SYMBOL} | {signal} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit}\n")

# === PLACE TRADE ===
def place_trade(signal, entry_price, stop_loss, take_profit):
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": entry_price,
        "sl": stop_loss,
        "tp": take_profit,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": f"SMC {signal}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }

    order = mt5.order_send(request)

    if order is not None:
        if order.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"✅ {signal} Order Placed: Entry={entry_price}, SL={stop_loss}, TP={take_profit}")
        else:
            print(f"❌ Trade Failed: {order.retcode}")
    else:
        print("❌ Order send failed: order is None")
        
def is_trading_hours():
    now = datetime.now().time()
    if start_time < end_time:
        return start_time <= now <= end_time
    else:  # Overnight session
        return now >= start_time or now <= end_time

def sleep_until_trading_hours():
    now = datetime.now()
    today_start = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)

    # If it's already past today's start_time, schedule for next day's start_time
    if now >= today_start:
        sleep_until = today_start + timedelta(days=1)
    else:
        sleep_until = today_start

    sleep_seconds = (sleep_until - now).total_seconds()
    hours, remainder = divmod(int(sleep_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"⏸️ Sleeping for {hours}h {minutes}m {seconds}s until {start_time.strftime('%H:%M')}...")
    time.sleep(sleep_seconds)

def equity_check_and_close_trades():
    global INITIAL_BALANCE, PROFIT_TARGET
    account_info = mt5.account_info()
    if account_info is None:
        print(f"❌ Unable to retrieve account info. Error: {mt5.last_error()}")
        return

    target_equity = INITIAL_BALANCE + PROFIT_TARGET
    print(f"🎯 Monitoring for equity to reach ${target_equity:.2f}...")

    while True:
        account_info = mt5.account_info()
        if account_info is None:
            print(f"⚠️ account_info() returned None — error: {mt5.last_error()}")
            wait_for_next_candle()
            continue

        equity = account_info.equity

        if equity >= target_equity:
            print("🚀 Equity target reached! Closing all open positions...")
            positions = mt5.positions_get()
            if positions is None or len(positions) == 0:
                print("No open positions to close.")
            else:
                for pos in positions:
                    symbol = pos.symbol
                    volume = pos.volume
                    ticket = pos.ticket
                    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

                    close_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "position": ticket,
                        "symbol": symbol,
                        "volume": volume,
                        "type": order_type,
                        "price": price,
                        "deviation": 10,
                        "magic": 123456,
                        "comment": "Auto close on equity profit"
                    }

                    result = mt5.order_send(close_request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"✅ Position {ticket} closed successfully.")
                    else:
                        print(f"❌ Failed to close position {ticket}: {result.retcode}")

            # Instead of stopping, sleep until next trading window
            sleep_until_trading_hours()
            print("🟢 Resuming trading...")
            break

        time.sleep(10)

def stop_at_time_gmt():
    while True:
        now = datetime.utcnow()
        current_time = now.time()

        # Calculate 5 minutes before end_time
        threshold_dt = (datetime.combine(now.date(), end_time) - timedelta(minutes=5)).time()

        if current_time >= threshold_dt:
            print(f"🛑 It's 5 minutes to {end_time.strftime('%H:%M')}! Closing all trades and sleeping until {start_time.strftime('%H:%M')}...")

            positions = mt5.positions_get()
            if positions:
                for pos in positions:
                    symbol = pos.symbol
                    volume = pos.volume
                    ticket = pos.ticket
                    order_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(symbol).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(symbol).ask

                    close_request = {
                        "action": mt5.TRADE_ACTION_DEAL,
                        "position": ticket,
                        "symbol": symbol,
                        "volume": volume,
                        "type": order_type,
                        "price": price,
                        "deviation": 10,
                        "magic": MAGIC_NUMBER,
                        "comment": "Auto close 5 mins before end time"
                    }

                    result = mt5.order_send(close_request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"✅ Position {ticket} closed successfully.")
                    else:
                        print(f"❌ Failed to close position {ticket}: {result.retcode}")

            sleep_until_trading_hours()
        
        time.sleep(30)

# === RUN THE BOT ===
def run_bot():
    connect_mt5()
    
    # Pause the bot if it's outside the 23:00–06:00 trading window
    if not is_trading_hours():
        sleep_until_trading_hours()

    # Start Threads
    threading.Thread(target=equity_check_and_close_trades, daemon=True).start()     # Equity check to monitor account equity and close trades if needed
    threading.Thread(target=stop_at_time_gmt, daemon=True).start()                   # To stop trading and close opened trades at 6 AM GMT 
    
    # Main trading loop runs until stop condition is triggered
    while True:
        
        df = get_data(SYMBOL, TIMEFRAME, 100)
        if df is None or df.empty:
            print("❌ No data received, retrying...")
            wait_for_next_candle()
            continue

        df = calculate_atr(df)
        signal, entry_price, stop_loss, take_profit = generate_signals(df)

        # ✅ Always check and update SL to breakeven for open positions
        positions = mt5.positions_get(symbol=SYMBOL)
        if positions:
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick:
                for pos in positions:
                    entry = pos.price_open
                    current_sl = pos.sl
                    current_tp = pos.tp
                    sl_distance = abs(entry - current_sl)
                    
                    if pos.type == mt5.ORDER_TYPE_BUY:
                        current_price = tick.ask
                        if current_price > entry and current_sl < entry:
                            modify_request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "sl": round(entry, 5),
                                "tp": current_tp
                            }
                            result = mt5.order_send(modify_request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"✅ BUY SL moved to breakeven for position {pos.ticket}")
                            else:
                                print(f"❌ Failed to update BUY SL: {result.retcode}")

                    elif pos.type == mt5.ORDER_TYPE_SELL:
                        current_price = tick.bid
                        if current_price <= entry - 1.5 * sl_distance and current_sl > entry:
                            modify_request = {
                                "action": mt5.TRADE_ACTION_SLTP,
                                "position": pos.ticket,
                                "sl": round(entry, 5),
                                "tp": current_tp
                            }
                            result = mt5.order_send(modify_request)
                            if result.retcode == mt5.TRADE_RETCODE_DONE:
                                print(f"✅ SELL SL moved to breakeven for position {pos.ticket}")
                            else:
                                print(f"❌ Failed to update SELL SL: {result.retcode}")
            else:
                print("❌ Failed to fetch current price tick.")
                
        # ✅ Trade only if signal exists and allowed
        if signal:
            allow_trade = True
            if positions:
                for pos in positions:
                    if pos.type == mt5.ORDER_TYPE_BUY and signal == "BUY":
                        print("⚠️ Trade skipped: Already in a BUY position.")
                        allow_trade = False
                        break
                    elif pos.type == mt5.ORDER_TYPE_SELL and signal == "SELL":
                        print("⚠️ Trade skipped: Already in a SELL position.")
                        allow_trade = False
                        break

            if allow_trade:
                print(f"📢 Trade Signal: {signal} | Entry: {entry_price} | SL: {stop_loss} | TP: {take_profit}")
                place_trade(signal, entry_price, stop_loss, take_profit)
            # else:
            #     print("⏳ Waiting for new opposite signal...")
        # else:
        #     print("⏳ No trade opportunity found.")
    
        wait_for_next_candle()
    
    print("🛑 Trading bot stopped")

# Start the trading bot
run_bot()
