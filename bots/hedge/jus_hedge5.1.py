# ============ Justice's Advice, TP All ===============
# Closes losing trade as pending trade is activated using only LOTS SIZE
# Uses TP to close trades instead of equity close
# Added ATR check to prevent trading in high volatility zones
# Added Telegram chatbot to print messages
# consolidating TP/SL checks for initial trade and hedge into one function

import logging
import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
import uuid
import requests

# === LOGGER SETUP ===
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()])
logging.getLogger().handlers[0].setStream(open('CON', 'w', encoding='utf-8'))
logging.info("✅ MT5 initialized successfully.")

# === CONSTANTS ===
SYMBOL = "BTCUSDm"  # Bitcoin symbol
TIMEFRAME = mt5.TIMEFRAME_M1
timeframe_to_next_candle_minutes = 0.1
HEDGE_LOT_SIZES = [0.01, 0.02, 0.03, 0.04, 0.07, 0.1, 0.15, 0.23, 0.35, 0.54, 0.82, 1.25, 1.91, 2.91, 4.44, 6.77]
MAGIC_NUMBER = 10002
LOG_FILE = "trade_log.txt"
INITIAL_TP_PIPS = 20000  # Take profit for initial and hedge trades
HEDGE_DISTANCE_PIPS = 10000  # Distance in pips for hedge orders
SL_DISTANCE_PIPS = HEDGE_DISTANCE_PIPS + 0.3 * HEDGE_DISTANCE_PIPS  # SL = 10000 + 0.3 * 10000 = 13000 pips
time_check = 60  # Increased to 60 seconds to allow more time for TP detection
ATR_THRESHOLD = 80  # ATR threshold in USD for signal generation
ATR_SLEEP_SECONDS = 600  # Sleep for 10 minutes if ATR > threshold
CONNECTION_SLEEP_SECONDS = 600  # Sleep for 10 minutes if connection fails after retries
TELEGRAM_BOT_TOKEN = "8183508860:AAHLP0nXwx4ehTv2waCuTpgPUMVw2-_C22E"  # Your Telegram bot token
TELEGRAM_CHAT_ID = "639750211"  # Your Telegram chat ID

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

# === SEND TELEGRAM MESSAGE ===
def send_telegram_message(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message
    }
    max_attempts = 3
    for attempt in range(max_attempts):
        try:
            response = requests.post(url, json=payload, timeout=5)
            if response.status_code == 200:
                print(f"✅ Telegram notification sent: {message}")
                return True
            else:
                print(f"❌ Telegram notification failed (attempt {attempt + 1}/{max_attempts}): {response.status_code} {response.text}")
        except requests.RequestException as e:
            print(f"❌ Telegram notification error (attempt {attempt + 1}/{max_attempts}): {e}")
        time.sleep(2)
    print(f"❌ Failed to send Telegram notification after {max_attempts} attempts.")
    return False

# === MT5 CONNECT ===
def connect_mt5():
    if not mt5.initialize(login=247888719, password="BISONdemo@1$", server="Exness-MT5Trial"):
        print("❌ MT5 initialization/login failed!")
        send_telegram_message("❌ MT5 server disconnected! Attempting to reconnect...")
        return False
    print("✅ MT5 initialized and logged in successfully.")
    account_info = mt5.account_info()
    if account_info is None:
        print("❌ Unable to fetch account information!")
        send_telegram_message("❌ MT5 server disconnected! Attempting to reconnect...")
        return False
    print(f"💰 Account Balance: {account_info.balance:.2f} USD")
    return True

# === ENSURE MT5 CONNECTION ===
def ensure_mt5_connection():
    max_connection_attempts = 3
    connection_delay = 1
    for attempt in range(max_connection_attempts):
        if mt5.terminal_info().connected:
            return True
        print(f"❌ MT5 connection lost. Attempting to reconnect (attempt {attempt + 1}/{max_connection_attempts})...")
        send_telegram_message(f"❌ MT5 server disconnected! Attempting to reconnect (attempt {attempt + 1}/{max_connection_attempts})...")
        if connect_mt5():
            return True
        time.sleep(connection_delay)
    print(f"❌ Failed to reconnect to MT5 after {max_connection_attempts} attempts. Sleeping for {CONNECTION_SLEEP_SECONDS/60:.0f} minutes before retrying...")
    send_telegram_message(f"❌ Failed to reconnect to MT5 after {max_connection_attempts} attempts. Sleeping for {CONNECTION_SLEEP_SECONDS/60:.0f} minutes before retrying...")
    time.sleep(CONNECTION_SLEEP_SECONDS)
    if connect_mt5():
        return True
    return False

# === GET POSITIONS WITH RETRY ===
def get_positions_with_retry(symbol, max_attempts=3, delay=1):
    for attempt in range(max_attempts):
        positions = mt5.positions_get(symbol=symbol)
        if positions is not None:
            return positions
        print(f"❌ Failed to get positions (attempt {attempt + 1}/{max_attempts}). Error: {mt5.last_error()}. Retrying...")
        time.sleep(delay)
    return None

# === GET ORDERS WITH RETRY ===
def get_orders_with_retry(symbol, max_attempts=3, delay=1):
    for attempt in range(max_attempts):
        orders = mt5.orders_get(symbol=symbol)
        if orders is not None:
            return orders
        print(f"❌ Failed to get orders (attempt {attempt + 1}/{max_attempts}). Error: {mt5.last_error()}. Retrying...")
        time.sleep(delay)
    return None

# === CLOSE PREVIOUS POSITION ===
def close_previous_position(lot_size):
    positions = get_positions_with_retry(SYMBOL)
    if positions is None:
        print(f"❌ Failed to retrieve positions to close position with lot size {lot_size}")
        return False
    position = None
    for pos in positions:
        if pos.comment == str(lot_size) and pos.magic == MAGIC_NUMBER:
            position = pos
            break
    if not position:
        print(f"❌ Position with lot size {lot_size} not found")
        return False
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "position": position.ticket,
        "symbol": position.symbol,
        "volume": position.volume,
        "type": mt5.ORDER_TYPE_SELL if position.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
        "price": mt5.symbol_info_tick(SYMBOL).bid if position.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).ask,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }
    order = mt5.order_send(request)
    if order is None or order.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"❌ Failed to close position with lot size {lot_size}: {RETCODE_MESSAGES.get(order.retcode, 'Unknown error') if order else 'Order is None'}")
        return False
    print(f"✅ Closed position with lot size {lot_size} (ticket {position.ticket})")
    return True

# === WAIT FOR NEXT CANDLE ===
def wait_for_next_candle():
    now = datetime.now()
    seconds_in_timeframe = timeframe_to_next_candle_minutes * 60
    seconds_since_epoch = int(now.timestamp())
    seconds_to_next_candle = seconds_in_timeframe - (seconds_since_epoch % seconds_in_timeframe)
    time.sleep(seconds_to_next_candle)

# === CALCULATE ATR ===
def calculate_atr(dataframe, period=14):
    if len(dataframe) < period + 1:
        print(f"❌ Insufficient data for ATR calculation. Need {period + 1} candles, got {len(dataframe)}.")
        return None
    df = dataframe.copy()
    df['high_low'] = df['high'] - df['low']
    df['high_prev_close'] = abs(df['high'] - df['close'].shift(1))
    df['low_prev_close'] = abs(df['low'] - df['close'].shift(1))
    df['true_range'] = df[['high_low', 'high_prev_close', 'low_prev_close']].max(axis=1)
    df['atr'] = df['true_range'].rolling(window=period).mean()
    return df['atr'].iloc[-2]  # Return ATR for the most recent closed candle

# === IDENTIFY TRADE SIGNALS ===
def generate_signals(dataframe):
    signal = None
    entry_price = None
    take_profit = None
    stop_loss = None
    symbol_info = mt5.symbol_info(SYMBOL)

    if symbol_info is None:
        print(f"❌ Unable to fetch symbol info for {SYMBOL}")
        return None, None, None, None

    point = symbol_info.point
    tp_points = INITIAL_TP_PIPS
    sl_points = SL_DISTANCE_PIPS

    # Calculate ATR
    atr = calculate_atr(dataframe)
    if atr is None:
        print(f"❌ Failed to calculate ATR for {SYMBOL}")
        return None, None, None, None
    if atr > ATR_THRESHOLD:
        print(f"⚠️ ATR ({atr:.2f}) exceeds threshold ({ATR_THRESHOLD}). No signal generated.")
        return None, None, None, None

    candle_1 = dataframe.iloc[-2]  # Most recent closed candle
    candle_2 = dataframe.iloc[-3]  # Candle before that

    # Double Bullish for BUY
    if candle_2['close'] > candle_2['open'] and candle_1['close'] > candle_1['open']:
        signal = "BUY"
        entry_price = candle_1['close']
        take_profit = entry_price + (tp_points * point)
        stop_loss = entry_price - (sl_points * point)

    # Double Bearish for SELL
    elif candle_2['close'] < candle_2['open'] and candle_1['close'] < candle_1['open']:
        signal = "SELL"
        entry_price = candle_1['close']
        take_profit = entry_price - (tp_points * point)
        stop_loss = entry_price + (sl_points * point)

    if signal:
        print(f"📈 Signal generated: {signal}, ATR={atr:.2f}")
        log_trade_signal(signal, entry_price, take_profit, stop_loss, HEDGE_LOT_SIZES[0])

    return signal, entry_price, take_profit, stop_loss

# === FETCH MARKET DATA ===
def get_data(symbol, timeframe, count=20):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None:
        print(f"❌ No data for {symbol}. Check symbol name!")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# === LOG TRADE SIGNAL ===
def log_trade_signal(signal, entry_price, take_profit, stop_loss, lot_size):
    with open(LOG_FILE, "a") as file:
        file.write(f"{datetime.now()} | {SYMBOL} | {signal} | Entry: {entry_price} | TP: {take_profit} | SL: {stop_loss} | Lot: {lot_size}\n")

# === PLACE MARKET TRADE ===
def place_market_trade(signal, take_profit, stop_loss):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Unable to fetch tick data for {SYMBOL}")
        return None, None
    lot_size = HEDGE_LOT_SIZES[0]
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": lot_size,
        "type": mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": tick.ask if signal == "BUY" else tick.bid,
        "tp": take_profit,
        "sl": stop_loss,
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": str(lot_size),  # Use lot size as comment
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }
    order = mt5.order_send(request)
    if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ {signal} Market Order Placed: Entry=Market, Lot={lot_size}, TP={take_profit}, SL={stop_loss}")
        log_trade_signal(signal, tick.ask if signal == "BUY" else tick.bid, take_profit, stop_loss, lot_size)
        return order.deal, tick.ask if signal == "BUY" else tick.bid
    else:
        error_message = RETCODE_MESSAGES.get(order.retcode, "Unknown error") if order else "Order is None"
        print(f"❌ Market Trade Failed: [{order.retcode if order else 'None'}] {error_message}")
        return None, None

# === PLACE HEDGE MARKET ORDER ===
def place_hedge_market_order(signal, initial_entry_price, lot_size, hedge_index=0):
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        print(f"❌ Unable to fetch symbol info for {SYMBOL}")
        return None, None
    point = symbol_info.point
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Unable to fetch tick data for {SYMBOL}")
        return None, None
    hedge_distance = HEDGE_DISTANCE_PIPS * point
    tp_points = INITIAL_TP_PIPS
    sl_points = SL_DISTANCE_PIPS
    if hedge_index % 2 == 1:
        hedge_price = initial_entry_price - hedge_distance if signal == "BUY" else initial_entry_price + hedge_distance
        order_type = mt5.ORDER_TYPE_SELL_STOP if signal == "BUY" else mt5.ORDER_TYPE_BUY_STOP
        order_signal = "SELL" if signal == "BUY" else "BUY"
        market_price = tick.bid if order_signal == "SELL" else tick.ask
        take_profit = hedge_price - (tp_points * point) if order_signal == "SELL" else hedge_price + (tp_points * point)
        stop_loss = hedge_price + (sl_points * point) if order_signal == "SELL" else hedge_price - (sl_points * point)
    else:
        hedge_price = initial_entry_price
        order_type = mt5.ORDER_TYPE_BUY_STOP if signal == "BUY" else mt5.ORDER_TYPE_SELL_STOP
        order_signal = signal
        market_price = tick.ask if order_signal == "BUY" else tick.bid
        take_profit = hedge_price + (tp_points * point) if order_signal == "BUY" else hedge_price - (tp_points * point)
        stop_loss = hedge_price - (sl_points * point) if order_signal == "BUY" else hedge_price + (sl_points * point)
    price_diff = abs(hedge_price - market_price)
    use_market_order = price_diff <= symbol_info.trade_stops_level * point
    max_verify_attempts = 3
    verify_delay = 2.5
    if not use_market_order:
        for verify_attempt in range(max_verify_attempts):
            request = {
                "action": mt5.TRADE_ACTION_PENDING,
                "symbol": SYMBOL,
                "volume": lot_size,
                "type": order_type,
                "price": hedge_price,
                "tp": take_profit,
                "sl": stop_loss,
                "deviation": 20,
                "magic": MAGIC_NUMBER,
                "comment": str(lot_size),  # Use lot size as comment
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            order = mt5.order_send(request)
            if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
                time.sleep(verify_delay)
                orders = get_orders_with_retry(SYMBOL)
                if orders is None:
                    print(f"❌ Failed to retrieve orders for verification (attempt {verify_attempt + 1}/{max_verify_attempts}). Retrying...")
                    continue
                if any(o.ticket == order.order for o in orders):
                    print(f"✅ Hedge Order Verified: Type={order_signal}, Price={hedge_price}, Lot={lot_size}, TP={take_profit}, SL={stop_loss}, Stop")
                    log_trade_signal(order_signal, hedge_price, take_profit, stop_loss, lot_size)
                    return order.order, hedge_price
                positions = get_positions_with_retry(SYMBOL)
                if positions is None:
                    print(f"❌ Failed to retrieve positions for verification (attempt {verify_attempt + 1}/{max_verify_attempts}). Retrying...")
                    continue
                for pos in positions:
                    if pos.comment == str(lot_size) and pos.magic == MAGIC_NUMBER:
                        actual_price = pos.price_open
                        print(f"✅ Hedge Order Activated and Verified as Position: Type={order_signal}, Price={actual_price}, Lot={lot_size}, TP={take_profit}, SL={stop_loss}, Stop")
                        log_trade_signal(order_signal, actual_price, take_profit, stop_loss, lot_size)
                        return pos.ticket, actual_price
                print(f"❌ Hedge order {order.order} placed but not found in orders or positions (attempt {verify_attempt + 1}/{max_verify_attempts}). Retrying...")
                continue
            else:
                error_message = RETCODE_MESSAGES.get(order.retcode, "Unknown error") if order else "Order is None"
                print(f"❌ Stop Order Failed: [{order.retcode if order else 'None'}] {error_message}. Attempting market order...")
                use_market_order = True
                break
        if not use_market_order:
            print(f"❌ Failed to place and verify stop order after {max_verify_attempts} attempts. Aborting.")
            return None, None
    if use_market_order:
        max_attempts = 10
        for attempt in range(max_attempts):
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                print(f"❌ Unable to fetch tick data for {SYMBOL} on attempt {attempt + 1}")
                time.sleep(1)
                continue
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": SYMBOL,
                "volume": lot_size,
                "type": mt5.ORDER_TYPE_BUY if order_signal == "BUY" else mt5.ORDER_TYPE_SELL,
                "price": market_price,
                "tp": take_profit,
                "sl": stop_loss,
                "deviation": 20,
                "magic": MAGIC_NUMBER,
                "comment": str(lot_size),  # Use lot size as comment
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            order = mt5.order_send(request)
            if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
                time.sleep(verify_delay)
                positions = get_positions_with_retry(SYMBOL)
                if positions is None:
                    print(f"❌ Failed to retrieve positions for verification (attempt {attempt + 1}/{max_attempts}). Retrying...")
                    time.sleep(1)
                    continue
                if any(pos.ticket == order.deal for pos in positions):
                    actual_price = tick.ask if order_signal == "BUY" else tick.bid
                    print(f"✅ Hedge Market Order Verified: Type={order_signal}, Price={actual_price}, Lot={lot_size}, TP={take_profit}, SL={stop_loss}, Market (Attempt {attempt + 1})")
                    log_trade_signal(order_signal, actual_price, take_profit, stop_loss, lot_size)
                    return order.deal, actual_price
                else:
                    print(f"❌ Hedge order {order.deal} placed but not found in positions (attempt {attempt + 1}/{max_attempts}). Retrying...")
                    time.sleep(1)
                    continue
            else:
                error_message = RETCODE_MESSAGES.get(order.retcode, "Unknown error") if order else "Order is None"
                print(f"❌ Market Order Failed: [{order.retcode if order else 'None'}] {error_message}. Retrying (Attempt {attempt + 1}/{max_attempts})...")
                time.sleep(1)
        print(f"❌ Failed to place and verify market order after {max_attempts} attempts. Aborting.")
        return None, None
    return None, None

# === CHECK IF TRADE HIT TP ===
def check_tp_reached(lot_size, signal, initial_take_profit=None, hedge_index=1, position_tickets=None):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Unable to fetch tick data for {SYMBOL}")
        return False
    current_price = tick.bid if signal == "BUY" else tick.ask
    positions = get_positions_with_retry(SYMBOL)
    if positions is None:
        print(f"❌ Failed to retrieve positions to check TP for lot size {lot_size}")
        return False
    position = None
    for pos in positions:
        if pos.comment == str(lot_size) and pos.magic == MAGIC_NUMBER:
            position = pos
            break
    if position:
        # Position still open, check TP
        point = mt5.symbol_info(SYMBOL).point
        if hedge_index == 1 and initial_take_profit is not None:
            # Initial trade: Use stored TP
            if signal == "BUY":
                tp_hit = current_price >= initial_take_profit
            else:  # SELL
                tp_hit = current_price <= initial_take_profit
        else:
            # Hedge trade: Use position's price_open
            if signal == "BUY":
                tp_hit = current_price >= position.price_open + (INITIAL_TP_PIPS * point)
            else:  # SELL
                tp_hit = current_price <= position.price_open - (INITIAL_TP_PIPS * point)
        if tp_hit:
            print(f"✅ Open position confirms TP hit for lot size {lot_size} (ticket {position.ticket})")
        return tp_hit
    else:
        # Position closed, check historical deals for all tickets
        if position_tickets is None or not position_tickets:
            print(f"❌ No position tickets available to check TP for lot size {lot_size}")
            return False
        from_date = datetime.now() - timedelta(minutes=30)  # Check last 30 minutes
        to_date = datetime.now()
        for ticket in position_tickets:
            deals = mt5.history_deals_get(position=ticket)
            if deals is None:
                print(f"❌ Failed to retrieve historical deals for position ticket {ticket}")
                continue
            for deal in deals:
                if deal.magic == MAGIC_NUMBER and deal.volume == lot_size:
                    # Log deal details for debugging
                    if deal.entry == mt5.DEAL_ENTRY_OUT and deal.reason == mt5.DEAL_REASON_TP:
                        print(f"✅ Historical deal confirms TP hit for lot size {lot_size} (ticket {ticket})")
                        return True
        print(f"❌ Position with lot size {lot_size} not found and no TP deal confirmed")
        return False

# === CLOSE ALL TRADES AND ORDERS ===
def close_all_trades_and_orders():
    positions = get_positions_with_retry(SYMBOL)
    if positions is None:
        print(f"❌ Failed to retrieve positions for closing. Error: {mt5.last_error()}")
        return
    orders = get_orders_with_retry(SYMBOL)
    if orders is None:
        print(f"❌ Failed to retrieve orders for closing. Error: {mt5.last_error()}")
        return
    for pos in positions:
        if pos.magic == MAGIC_NUMBER:
            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "position": pos.ticket,
                "symbol": pos.symbol,
                "volume": pos.volume,
                "type": mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY,
                "price": mt5.symbol_info_tick(SYMBOL).bid if pos.type == mt5.ORDER_TYPE_BUY else mt5.symbol_info_tick(SYMBOL).ask,
                "deviation": 20,
                "magic": MAGIC_NUMBER,
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC
            }
            order = mt5.order_send(request)
            if order is None or order.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Failed to close position {pos.ticket}: {RETCODE_MESSAGES.get(order.retcode, 'Unknown error') if order else 'Order is None'}")
            else:
                print(f"✅ Closed position {pos.ticket}")
    for order in orders:
        if order.magic == MAGIC_NUMBER:
            request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket,
                "symbol": order.symbol
            }
            result = mt5.order_send(request)
            if result is None or result.retcode != mt5.TRADE_RETCODE_DONE:
                print(f"❌ Failed to cancel order {order.ticket}: {RETCODE_MESSAGES.get(result.retcode, 'Unknown error') if result else 'Order is None'}")
            else:
                print(f"✅ Canceled order {order.ticket}")
    print("✅ All trades and orders closed.")

# === RUN THE BOT ===
def run_bot():
    connect_mt5()
    initial_equity = mt5.account_info().equity
    current_hedge_index = 1
    initial_order_placed = False
    hedge_order_ticket = None
    initial_entry_price = None
    initial_take_profit = None
    initial_stop_loss = None
    signal = None
    no_pending_order_count = 0
    no_active_position_count = 0
    last_check_time = None
    position_tickets = []  # Track all position tickets
    while True:
        if not ensure_mt5_connection():
            print("❌ No MT5 connection. Retrying...")
            wait_for_next_candle()
            continue
        df = get_data(SYMBOL, TIMEFRAME, 20)
        if df is None or df.empty:
            print("❌ No data received, retrying...")
            wait_for_next_candle()
            continue
        if not initial_order_placed:
            # Check ATR before generating signals
            atr = calculate_atr(df)
            if atr is None:
                print(f"❌ Failed to calculate ATR for {SYMBOL}. Retrying...")
                wait_for_next_candle()
                continue
            if atr > ATR_THRESHOLD:
                print(f"⚠️ ATR ({atr:.2f}) exceeds threshold ({ATR_THRESHOLD}). Sleeping for {ATR_SLEEP_SECONDS/60:.0f} minutes.")
                time.sleep(ATR_SLEEP_SECONDS)
                continue
            signal, entry_price, take_profit, stop_loss = generate_signals(df)
            if signal:
                print(f"📊 Using HEDGE_DISTANCE_PIPS={HEDGE_DISTANCE_PIPS}, INITIAL_TP_PIPS={INITIAL_TP_PIPS}, SL_DISTANCE_PIPS={SL_DISTANCE_PIPS}")
                deal_ticket, actual_entry_price = place_market_trade(signal, take_profit, stop_loss)
                if deal_ticket:
                    initial_order_placed = True
                    initial_entry_price = actual_entry_price
                    initial_take_profit = take_profit
                    initial_stop_loss = stop_loss
                    position_tickets.append(deal_ticket)  # Track initial position
                    hedge_order_ticket, hedge_price = place_hedge_market_order(signal, actual_entry_price, HEDGE_LOT_SIZES[1], current_hedge_index)
        else:
            positions = get_positions_with_retry(SYMBOL)
            if positions is None:
                print(f"❌ Failed to retrieve positions for {SYMBOL}. Error: {mt5.last_error()}. Retrying...")
                wait_for_next_candle()
                continue
            orders = get_orders_with_retry(SYMBOL)
            if orders is None:
                print(f"❌ Failed to retrieve orders for {SYMBOL}. Error: {mt5.last_error()}. Retrying...")
                wait_for_next_candle()
                continue
            if initial_order_placed and current_hedge_index < len(HEDGE_LOT_SIZES):
                # Check TP first
                if initial_take_profit and signal:
                    tp_hit = check_tp_reached(
                        HEDGE_LOT_SIZES[current_hedge_index - 1],
                        signal,
                        initial_take_profit if current_hedge_index == 1 else None,
                        current_hedge_index,
                        position_tickets
                    )
                    if tp_hit:
                        account_info = mt5.account_info()
                        balance = account_info.balance if account_info else "Unknown"
                        print(f"🎯 Trade with lot size {HEDGE_LOT_SIZES[current_hedge_index - 1]} hit TP. Closing all trades and resetting cycle.")
                        send_telegram_message(f"🎯 TP Hit at lot size {HEDGE_LOT_SIZES[current_hedge_index - 1]}, Account Balance: {balance:.2f} USD")
                        close_all_trades_and_orders()
                        initial_equity = mt5.account_info().equity
                        initial_order_placed = False
                        hedge_order_ticket = None
                        position_tickets = []  # Reset position tickets
                        current_hedge_index = 1
                        signal = None
                        initial_take_profit = None
                        initial_stop_loss = None
                        no_pending_order_count = 0
                        no_active_position_count = 0
                        last_check_time = None
                        continue
                # Check for no pending orders
                current_time = datetime.now()
                if len(orders) < 1:
                    if last_check_time is None or (current_time - last_check_time).total_seconds() >= time_check:
                        no_pending_order_count += 1
                        print(f"⚠️ No pending orders detected (check {no_pending_order_count}/2).")
                        last_check_time = current_time
                    if no_pending_order_count >= 2:
                        account_info = mt5.account_info()
                        balance = account_info.balance if account_info else "Unknown"
                        print("❌ Two consecutive checks confirmed no pending orders. Closing all trades and resetting cycle.")
                        send_telegram_message(f"❌ All trades closed due to no pending orders. Account Balance: {balance:.2f} USD")
                        close_all_trades_and_orders()
                        initial_equity = mt5.account_info().equity
                        initial_order_placed = False
                        hedge_order_ticket = None
                        position_tickets = []  # Reset position tickets
                        current_hedge_index = 1
                        signal = None
                        initial_take_profit = None
                        initial_stop_loss = None
                        no_pending_order_count = 0
                        no_active_position_count = 0
                        last_check_time = None
                        continue
                else:
                    no_pending_order_count = 0
                    last_check_time = None
                # Check if no active position exists
                active_position_exists = any(pos.comment == str(HEDGE_LOT_SIZES[current_hedge_index - 1]) and pos.magic == MAGIC_NUMBER for pos in positions)
                if not active_position_exists and not tp_hit:
                    if last_check_time is None or (current_time - last_check_time).total_seconds() >= time_check:
                        no_active_position_count += 1
                        print(f"⚠️ No active position detected for lot size {HEDGE_LOT_SIZES[current_hedge_index - 1]} (check {no_active_position_count}/2).")
                        last_check_time = current_time
                    if no_active_position_count >= 2:
                        account_info = mt5.account_info()
                        balance = account_info.balance if account_info else "Unknown"
                        print("❌ Two consecutive checks confirmed no active position. Closing all trades and resetting cycle.")
                        send_telegram_message(f"❌ All trades closed due to no active position. Account Balance: {balance:.2f} USD")
                        close_all_trades_and_orders()
                        initial_equity = mt5.account_info().equity
                        initial_order_placed = False
                        hedge_order_ticket = None
                        position_tickets = []  # Reset position tickets
                        current_hedge_index = 1
                        signal = None
                        initial_take_profit = None
                        initial_stop_loss = None
                        no_pending_order_count = 0
                        no_active_position_count = 0
                        last_check_time = None
                        continue
                else:
                    no_active_position_count = 0
                    last_check_time = None
                # Check if hedge order has activated
                for pos in positions:
                    if pos.comment == str(HEDGE_LOT_SIZES[current_hedge_index]) and pos.magic == MAGIC_NUMBER:
                        close_previous_position(HEDGE_LOT_SIZES[current_hedge_index - 1])
                        position_tickets.append(pos.ticket)  # Track new position
                        for order in orders:
                            if order.magic == MAGIC_NUMBER:
                                request = {
                                    "action": mt5.TRADE_ACTION_REMOVE,
                                    "order": order.ticket,
                                    "symbol": order.symbol
                                }
                                mt5.order_send(request)
                                print(f"✅ Canceled pending order {order.ticket} for lot size {order.volume}")
                        new_lot_size = HEDGE_LOT_SIZES[current_hedge_index + 1] if current_hedge_index < len(HEDGE_LOT_SIZES) - 1 else None
                        if new_lot_size:
                            hedge_order_ticket, hedge_price = place_hedge_market_order(signal, initial_entry_price, new_lot_size, current_hedge_index + 1)
                            if hedge_order_ticket:
                                current_hedge_index += 1
                        break
            if not orders and current_hedge_index >= len(HEDGE_LOT_SIZES) - 1:
                account_info = mt5.account_info()
                balance = account_info.balance if account_info else "Unknown"
                print("🏁 Lot size sequence exhausted. Closing all trades and resetting cycle.")
                send_telegram_message(f"❌ All trades closed due to lot size sequence exhausted. Account Balance: {balance:.2f} USD")
                close_all_trades_and_orders()
                initial_equity = mt5.account_info().equity
                initial_order_placed = False
                hedge_order_ticket = None
                position_tickets = []  # Reset position tickets
                current_hedge_index = 1
                signal = None
                initial_take_profit = None
                initial_stop_loss = None
                no_pending_order_count = 0
                no_active_position_count = 0
                last_check_time = None
                continue
        wait_for_next_candle()

# Start the trading bot
if __name__ == "__main__":
    run_bot()
    
    
    
