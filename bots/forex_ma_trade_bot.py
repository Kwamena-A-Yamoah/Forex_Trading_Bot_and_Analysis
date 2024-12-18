import MetaTrader5 as mt5
import pandas as pd
import talib
import time
import logging
from datetime import datetime

# MetaTrader 5 login credentials
MT5_LOGIN = "192659358"
MT5_PASSWORD = "K1w2a3m4e5n6a7."
MT5_SERVER = "Exness-MT5Trial"

# Initialize MT5 connection
if not mt5.initialize(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER):
    print(f"MT5 initialization failed: {mt5.last_error()}")
    quit()

# Configure logging
logging.basicConfig(
    filename="trade_bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

logging.info("Trading bot started and logged in successfully.")

def fetch_data(symbol, timeframe, num_candles=500):
    """ 
    Fetches recent market data for the specified symbol and timeframe.
    """
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_candles)
    data = pd.DataFrame(rates)
    data['time'] = pd.to_datetime(data['time'], unit='s')
    return data

def execute_trade(symbol, action, lot_size):
    """ 
    Executes a trade on MT5, accounting for spread.
    """
    symbol_info = mt5.symbol_info(symbol)
    if not symbol_info:
        logging.error(f"Symbol {symbol} not found.")
        return

    if not symbol_info.visible:
        logging.warning(f"Symbol {symbol} is not visible. Attempting to make it visible...")
        if not mt5.symbol_select(symbol, True):
            logging.error(f"Failed to select symbol {symbol}.")
            return

    point = symbol_info.point
    spread = symbol_info.spread * point  # Calculate the spread in price terms
    price = mt5.symbol_info_tick(symbol).ask if action == "buy" else mt5.symbol_info_tick(symbol).bid
    half_spread = spread / 2  # Half spread for adjustment

    if action == "buy":
        entry_price = price + half_spread
        sl = entry_price - 0.0001  # Example: 1 pip below entry price
        tp = entry_price + 0.0005  # Example: 5 pips above entry price
    else:  # sell
        entry_price = price - half_spread
        sl = entry_price + 0.0001  # Example: 1 pip above entry price
        tp = entry_price - 0.0005  # Example: 5 pips below entry price

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": mt5.ORDER_BUY if action == "buy" else mt5.ORDER_SELL,
        "price": entry_price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 234000,
        "comment": "MA Crossover Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        logging.error(f"Trade execution failed: {result.comment}")
    else:
        logging.info(f"{action.capitalize()} trade executed at {entry_price}. SL: {sl}, TP: {tp}")

def trade_logic(symbol, lot_size, num1=12, num2=13):
    """ 
    Implements the moving average crossover strategy.
    """
    # Fetch data
    data = fetch_data(symbol, mt5.TIMEFRAME_H2)

    # Calculate moving averages
    data['MA_12'] = talib.SMA(data['close'], timeperiod=num1)
    data['MA_13'] = talib.SMA(data['close'], timeperiod=num2)

    # Check for crossover signals
    if data['MA_12'].iloc[-1] > data['MA_13'].iloc[-1] and data['MA_12'].iloc[-2] <= data['MA_13'].iloc[-2]:
        logging.info(f"Buy signal detected for {symbol}.")
        execute_trade(symbol, "buy", lot_size)
    elif data['MA_12'].iloc[-1] < data['MA_13'].iloc[-1] and data['MA_12'].iloc[-2] >= data['MA_13'].iloc[-2]:
        logging.info(f"Sell signal detected for {symbol}.")
        execute_trade(symbol, "sell", lot_size)
    else:
        logging.info("No trade signal detected.")

# Controlled Execution with While Loop
symbol = "EURUSDm"  # Replace with your trading symbol
lot_size = 0.1  # Adjust based on your risk management

try:
    while True:
        trade_logic(symbol, lot_size)
        logging.info(f"Checked at {datetime.now()} - Waiting for the next cycle...")
        time.sleep(3600)  # Wait for 1 hour (H2 timeframe) before checking again
except KeyboardInterrupt:
    logging.info("Bot stopped by user.")
except Exception as e:
    logging.error(f"An unexpected error occurred: {e}")
finally:
    mt5.shutdown()
    logging.info("MT5 connection closed.")
