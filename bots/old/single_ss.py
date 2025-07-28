# === LOGGER SETUP ===
import logging
import csv
import os

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
import threading
from datetime import datetime, timedelta

# === CONSTANTS ===
SYMBOL = "BTCUSDm"
TIMEFRAME = mt5.TIMEFRAME_M15
timeframe_to_next_candle_minutes = 5
LOT_SIZE = 0.01
MAGIC_NUMBER = 10002
LOG_FILE = "trade_log.txt"
PROFIT_LOG_FILE = "profit_log.csv"  # CSV file for profit logging
PROFIT_TARGET = 300  # 💰 Target profit in USD
LOSS_TARGET = 100
INITIAL_BALANCE = None  # 🔒 Will be set after login
stop_trading = False  # Shared flag

# Define trading start and end times
start_time = datetime.strptime("22:10", "%H:%M").time()  
end_time = datetime.strptime("06:00", "%H:%M").time()

# === RETCODE MESSAGES ===
RETCODE_MESSAGES = {
    10004: "Requote",
    10006: "Request rejected",
    10007: "Request canceled by trader",
    10011: "Request processing error",
    10012: "Request canceled by timeout",
    10013: "Invalid request",
    10014: "Invalid volume in the request",
    10015: "Invalid price in the request",
    10016: "Invalid stops in the request",
    10017: "Trade is disabled",
    10018: "Market is closed",
    10019: "Not enough money to complete the request",
    10020: "Prices changed",
    10021: "No quotes to process the request",
    10022: "Invalid order expiration date",
    10023: "Order state changed",
    10024: "Too frequent requests",
    10025: "No changes in request",
    10026: "Autotrading disabled by server",
    10027: "Autotrading disabled by client terminal",
    10028: "Request locked for processing",
    10029: "Order or position frozen",
    10030: "Invalid order filling type",
    10031: "No connection with trade server",
    10032: "Only allowed for live accounts",
    10033: "Pending orders limit reached",
    10034: "Order/position volume limit reached for symbol",
    10035: "Incorrect or prohibited order type",
    10036: "Position already closed",
    10038: "Close volume exceeds position volume",
    10039: "Close order already exists for position",
    10040: "Open positions limit reached",
    10041: "Activation rejected, order canceled",
    10042: "Only long positions allowed",
    10043: "Only short positions allowed",
    10044: "Only position closing allowed",
    10045: "Only FIFO closing allowed",
    10046: "Opposite positions disabled (hedging prohibited)",
}

# === MT5 CONNECT ===
def connect_mt5():
    global INITIAL_BALANCE
    if not mt5.initialize(
        login=247267315,
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

# === WAIT FOR NEXT CANDLE ===
def wait_for_next_candle():
    now = datetime.now()
    seconds_in_timeframe = timeframe_to_next_candle_minutes * 60
    seconds_since_epoch = int(now.timestamp())
    seconds_to_next_candle = seconds_in_timeframe - (seconds_since_epoch % seconds_in_timeframe)
    time.sleep(seconds_to_next_candle)

# === IDENTIFY TRADE SIGNALS ===
def generate_signals(dataframe):
    signal = None
    entry_price = None
    stop_loss = None
    take_profit = None

    if dataframe.iloc[-1]['high'] > dataframe.iloc[-2]['high']:
        signal = "BUY"
        entry_price = dataframe.iloc[-1]['close']
    elif dataframe.iloc[-1]['low'] < dataframe.iloc[-2]['low']:
        signal = "SELL"
        entry_price = dataframe.iloc[-1]['close']

    if signal:
        stop_loss, take_profit = predict_sl_tp(dataframe, entry_price, signal)
        log_trade_signal(signal, entry_price, stop_loss, take_profit)

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
            error_message = RETCODE_MESSAGES.get(order.retcode, f"Unknown error (retcode: {order.retcode})")
            print(f"❌ Trade Failed: {error_message}")
    else:
        print("❌ Order send failed: order is None")

# === TRADING HOURS CHECK ===
def is_trading_hours():
    now = datetime.now().time()
    if start_time < end_time:
        return start_time <= now <= end_time
    else:  # Overnight session
        return now >= start_time or now <= end_time

# === SLEEP UNTIL TRADING HOURS ===
def sleep_until_trading_hours():
    now = datetime.now()
    today_start = now.replace(hour=start_time.hour, minute=start_time.minute, second=0, microsecond=0)

    if now >= today_start:
        sleep_until = today_start + timedelta(days=1)
    else:
        sleep_until = today_start

    sleep_seconds = (sleep_until - now).total_seconds()
    hours, remainder = divmod(int(sleep_seconds), 3600)
    minutes, seconds = divmod(remainder, 60)
    print(f"⏸️ Sleeping for {hours}h {minutes}m {seconds}s until {start_time.strftime('%H:%M')}...")
    time.sleep(sleep_seconds)

# === CLOSE ALL POSITIONS ===
def close_all_positions():
    positions = mt5.positions_get()
    if positions is None or len(positions) == 0:
        print("No open positions to close.")
        return

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
            "comment": "Closed at end time"
        }

        result = mt5.order_send(close_request)
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"✅ Position {ticket} closed successfully.")
        else:
            error_message = RETCODE_MESSAGES.get(result.retcode, f"Unknown error (retcode: {result.retcode})")
            print(f"❌ Failed to close position {ticket}: {error_message}")

# === LOG SESSION PROFIT ===
# === LOG SESSION PROFIT ===
def log_session_profit():
    global INITIAL_BALANCE
    now = datetime.now()
    # Retrieve account info
    account_info = mt5.account_info()
    if account_info:
        final_balance = account_info.balance
        account_name = account_info.name  # Get account name
        profit = final_balance - INITIAL_BALANCE
        print(f"📊 Session Profit/Loss for {account_name}: GHC{profit:.2f}")

        # Append to CSV
        csv_headers = ['Date', 'Account Name', 'Lot Size', 'Profit/Loss']  # Updated headers
        csv_data = [now.strftime('%Y-%m-%d %H:%M'), account_name, LOT_SIZE, profit]
        
        file_exists = os.path.isfile(PROFIT_LOG_FILE)
        with open(PROFIT_LOG_FILE, 'a', newline='') as csvfile:
            writer = csv.writer(csvfile)
            if not file_exists:
                writer.writerow(csv_headers)
            writer.writerow(csv_data)
        
        # Reset INITIAL_BALANCE for the next session
        INITIAL_BALANCE = final_balance
    else:
        print(f"❌ Unable to retrieve account info for profit calculation. Error: {mt5.last_error()}")
        
# === EQUITY CHECK AND CLOSE TRADES ===
def equity_check_and_close_trades():
    global INITIAL_BALANCE, PROFIT_TARGET, LOSS_TARGET, stop_trading
    account_info = mt5.account_info()
    if account_info is None:
        print(f"❌ Unable to retrieve account info. Error: {mt5.last_error()}")
        return

    target_equity = INITIAL_BALANCE + PROFIT_TARGET
    loss_equity = INITIAL_BALANCE - LOSS_TARGET
    print(f"🎯 Monitoring equity: Target ${target_equity:.2f}, Max-loss ${loss_equity:.2f}...")

    while True:
        account_info = mt5.account_info()
        if account_info is None:
            print(f"⚠️ account_info() returned None — error: {mt5.last_error()}")
            wait_for_next_candle()
            continue

        equity = account_info.equity

        if equity >= target_equity:
            print("🚀 Equity profit target reached! Closing all open positions...")
            close_all_positions()
            stop_trading = True
            break

        elif equity <= loss_equity:
            print("🛑 Equity loss limit reached! Closing all open positions...")
            close_all_positions()
            stop_trading = True
            break

        time.sleep(10)

# === TRAILING STOP LOSS ===
def trailing_stop_loss(symbol):
    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return

    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print("❌ Failed to fetch current price tick.")
        return

    for pos in positions:
        entry = pos.price_open
        current_sl = pos.sl
        sl_distance = abs(entry - current_sl)

        if pos.type == mt5.ORDER_TYPE_BUY:
            current_price = tick.ask
            new_sl = round(current_price - sl_distance, 2)
            if current_price > entry and new_sl > current_sl:
                modify_request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                result = mt5.order_send(modify_request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"✅ BUY SL updated for position {pos.ticket} → {new_sl}")
                else:
                    error_message = RETCODE_MESSAGES.get(result.retcode, f"Unknown error (retcode: {result.retcode})")
                    print(f"❌ Failed to update BUY SL: {error_message}")

        elif pos.type == mt5.ORDER_TYPE_SELL:
            current_price = tick.bid
            new_sl = round(current_price + sl_distance, 2)
            if current_price < entry and new_sl < current_sl:
                modify_request = {
                    "action": mt5.TRADE_ACTION_SLTP,
                    "position": pos.ticket,
                    "sl": new_sl,
                    "tp": pos.tp
                }
                result = mt5.order_send(modify_request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"✅ SELL SL updated for position {pos.ticket} → {new_sl}")
                else:
                    error_message = RETCODE_MESSAGES.get(result.retcode, f"Unknown error (retcode: {result.retcode})")
                    print(f"❌ Failed to update SELL SL: {error_message}")

# === TRADE ON SIGNAL ===
def trade_on_signal(signal, entry_price, stop_loss, take_profit, symbol):
    if signal:
        positions = mt5.positions_get(symbol=symbol)
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
        else:
            pass
    else:
        pass

# === RUN THE BOT ===
def run_bot():
    global stop_trading
    connect_mt5()
    
    if not is_trading_hours():
        print("🕒 Trading paused — market is currently outside the active hours window")
        sleep_until_trading_hours()

    threading.Thread(target=equity_check_and_close_trades, daemon=True).start()

    while True:
        if stop_trading:
            log_session_profit()
            sleep_until_trading_hours()
            stop_trading = False  # Reset for next session
            continue
        
        if not is_trading_hours():
            print("🛑 Trading hours ended. Closing all positions...")
            close_all_positions()
            log_session_profit()
            sleep_until_trading_hours()
            continue
        
        df = get_data(SYMBOL, TIMEFRAME, 100)
        if df is None or df.empty:
            print("❌ No data received, retrying...")
            wait_for_next_candle()
            continue

        df = calculate_atr(df)
        signal, entry_price, stop_loss, take_profit = generate_signals(df)

        trailing_stop_loss(SYMBOL)
                
        trade_on_signal(signal, entry_price, stop_loss, take_profit, SYMBOL)
        
        wait_for_next_candle()

# Start the trading bot
run_bot()