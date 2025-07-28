# ============ Justice's Advice ===============
# Closes losing trade as pending trade is activated

import logging
import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime, timedelta
import uuid

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
HEDGE_LOT_SIZES = [0.02, 0.03, 0.05, 0.08, 0.14, 0.23, 0.38, 0.64, 1.06, 1.77, 2.95]
MAGIC_NUMBER = 10002
LOG_FILE = "trade_log.txt"
INITIAL_TP_PIPS = 15000  # Take profit for initial trade
HEDGE_DISTANCE_PIPS = 10000  # Distance in pips for hedge orders
EQUITY_TP_PIPS = 15000  # Equity take profit in pips

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
    if not mt5.initialize(login=247888719, password="BISONdemo@1$", server="Exness-MT5Trial"):
        print("❌ MT5 initialization/login failed!")
        quit()
    print("✅ MT5 initialized and logged in successfully.")
    account_info = mt5.account_info()
    if account_info is None:
        print("❌ Unable to fetch account information!")
        quit()
    print(f"💰 Account Balance: {account_info.balance:.2f} USD")

# === VALIDATE SYMBOL ===
def validate_symbol(symbol):
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None or not symbol_info.visible:
        print(f"❌ Symbol {symbol} is not available or not visible in MT5.")
        return False
    return True

# === ENSURE MT5 CONNECTION ===
def ensure_mt5_connection():
    if not mt5.terminal_info().connected:
        print("❌ MT5 connection lost. Attempting to reconnect...")
        connect_mt5()
    return mt5.terminal_info().connected

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

# === CLOSE POSITION BY COMMENT ===
def close_position_by_comment(comment):
    positions = get_positions_with_retry(SYMBOL)
    if positions is None:
        print(f"❌ Failed to retrieve positions to close position with comment {comment}")
        return False
    position = None
    for pos in positions:
        if pos.comment == str(comment) and pos.magic == MAGIC_NUMBER:
            position = pos
            break
    if not position:
        print(f"❌ Position with comment {comment} not found")
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
        print(f"❌ Failed to close position with comment {comment}: {RETCODE_MESSAGES.get(order.retcode, 'Unknown error') if order else 'Order is None'}")
        return False
    print(f"✅ Closed position with comment {comment} (ticket {position.ticket})")
    return True

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
    take_profit = None
    symbol_info = mt5.symbol_info(SYMBOL)

    if symbol_info is None:
        print(f"❌ Unable to fetch symbol info for {SYMBOL}")
        return None, None, None

    point = symbol_info.point
    tp_points = INITIAL_TP_PIPS

    candle_1 = dataframe.iloc[-2]  # Most recent closed candle
    candle_2 = dataframe.iloc[-3]  # Candle before that

    # Double Bullish for BUY
    if candle_2['close'] > candle_2['open'] and candle_1['close'] > candle_1['open']:
        signal = "BUY"
        entry_price = candle_1['close']
        take_profit = entry_price + (tp_points * point)

    # Double Bearish for SELL
    elif candle_2['close'] < candle_2['open'] and candle_1['close'] < candle_1['open']:
        signal = "SELL"
        entry_price = candle_1['close']
        take_profit = entry_price - (tp_points * point)

    if signal:
        log_trade_signal(signal, entry_price, take_profit, HEDGE_LOT_SIZES[0])

    return signal, entry_price, take_profit

# === FETCH MARKET DATA ===
def get_data(symbol, timeframe, count=10):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, count)
    if rates is None:
        print(f"❌ No data for {symbol}. Check symbol name!")
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

# === LOG TRADE SIGNAL ===
def log_trade_signal(signal, entry_price, take_profit, lot_size):
    with open(LOG_FILE, "a") as file:
        file.write(f"{datetime.now()} | {SYMBOL} | {signal} | Entry: {entry_price} | TP: {take_profit} | SL: None | Lot: {lot_size}\n")

# === PLACE MARKET TRADE ===
def place_market_trade(signal, take_profit):
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
        "deviation": 20,
        "magic": MAGIC_NUMBER,
        "comment": str(lot_size),  # Use lot size as comment
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC
    }
    order = mt5.order_send(request)
    if order is not None and order.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"✅ {signal} Market Order Placed: Entry=Market, Lot={lot_size}, TP={take_profit}, SL=None")
        log_trade_signal(signal, tick.ask if signal == "BUY" else tick.bid, take_profit, lot_size)
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
    stops_level = symbol_info.trade_stops_level * point
    if hedge_index % 2 == 1:
        hedge_price = initial_entry_price - hedge_distance if signal == "BUY" else initial_entry_price + hedge_distance
        order_type = mt5.ORDER_TYPE_SELL_STOP if signal == "BUY" else mt5.ORDER_TYPE_BUY_STOP
        order_signal = "SELL" if signal == "BUY" else "BUY"
        market_price = tick.bid if order_signal == "SELL" else tick.ask
    else:
        hedge_price = initial_entry_price
        order_type = mt5.ORDER_TYPE_BUY_STOP if signal == "BUY" else mt5.ORDER_TYPE_SELL_STOP
        order_signal = signal
        market_price = tick.ask if order_signal == "BUY" else tick.bid
    price_diff = abs(hedge_price - market_price)
    use_market_order = price_diff <= stops_level
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
                "tp": 0.0,
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
                    print(f"✅ Hedge Order Verified: Type={order_signal}, Price={hedge_price}, Lot={lot_size}, Stop")
                    log_trade_signal(order_signal, hedge_price, 0.0, lot_size)
                    return order.order, hedge_price
                positions = get_positions_with_retry(SYMBOL)
                if positions is None:
                    print(f"❌ Failed to retrieve positions for verification (attempt {verify_attempt + 1}/{max_verify_attempts}). Retrying...")
                    continue
                for pos in positions:
                    if pos.comment == str(lot_size) and pos.magic == MAGIC_NUMBER:
                        actual_price = pos.price_open
                        print(f"✅ Hedge Order Activated and Verified as Position: Type={order_signal}, Price={actual_price}, Lot={lot_size}, Stop")
                        log_trade_signal(order_signal, actual_price, 0.0, lot_size)
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
                "price": hedge_price,
                "tp": 0.0,
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
                    print(f"✅ Hedge Market Order Verified: Type={order_signal}, Price={actual_price}, Lot={lot_size}, Market (Attempt {attempt + 1})")
                    log_trade_signal(order_signal, actual_price, 0.0, lot_size)
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

# === CHECK EQUITY PROFIT ===
def check_equity_profit(initial_equity):
    current_equity = mt5.account_info().equity
    symbol_info = mt5.symbol_info(SYMBOL)
    if symbol_info is None:
        return False
    point = symbol_info.point
    equity_profit_pips = (current_equity - initial_equity) / (point * HEDGE_LOT_SIZES[0])
    return equity_profit_pips >= EQUITY_TP_PIPS

# === CHECK IF INITIAL TRADE HIT TP ===
def check_initial_trade_tp_reached(initial_take_profit, signal):
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print(f"❌ Unable to fetch tick data for {SYMBOL}")
        return False
    current_price = tick.bid if signal == "BUY" else tick.ask
    if signal == "BUY":
        return current_price >= initial_take_profit
    else:  # SELL
        return current_price <= initial_take_profit

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
    if not validate_symbol(SYMBOL):
        print("❌ Terminating bot due to invalid symbol.")
        return
    initial_equity = mt5.account_info().equity
    current_hedge_index = 1
    initial_order_placed = False
    initial_trade_ticket = None  # Track initial trade ticket as fallback
    hedge_order_ticket = None
    initial_entry_price = None
    initial_take_profit = None
    signal = None
    first_hedge_activated = False
    no_pending_order_count = 0
    no_active_position_count = 0
    last_check_time = None
    active_position_ticket = None  # Track the current active position
    while True:
        if not ensure_mt5_connection():
            print("❌ No MT5 connection. Retrying...")
            wait_for_next_candle()
            continue
        df = get_data(SYMBOL, TIMEFRAME, 10)
        if df is None or df.empty:
            print("❌ No data received, retrying...")
            wait_for_next_candle()
            continue
        if not initial_order_placed:
            signal, entry_price, take_profit = generate_signals(df)
            if signal:
                print(f"📊 Using HEDGE_DISTANCE_PIPS={HEDGE_DISTANCE_PIPS} and EQUITY_TP_PIPS={EQUITY_TP_PIPS}")
                deal_ticket, actual_entry_price = place_market_trade(signal, take_profit)
                if deal_ticket:
                    initial_order_placed = True
                    initial_entry_price = actual_entry_price
                    initial_take_profit = take_profit
                    initial_trade_ticket = deal_ticket  # Store initial trade ticket
                    active_position_ticket = deal_ticket  # Set initial active position
                    hedge_order_ticket, hedge_price = place_hedge_market_order(signal, actual_entry_price, HEDGE_LOT_SIZES[1], current_hedge_index)
                    if hedge_order_ticket:
                        first_hedge_activated = True
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
                current_time = datetime.now()
                if len(orders) < 1:
                    if last_check_time is None or (current_time - last_check_time).total_seconds() >= 8:
                        no_pending_order_count += 1
                        print(f"⚠️ No pending orders detected (check {no_pending_order_count}/2).")
                        last_check_time = current_time
                    if no_pending_order_count >= 2:
                        print("❌ Two consecutive checks confirmed no pending orders. Closing all trades and resetting cycle.")
                        close_all_trades_and_orders()
                        initial_equity = mt5.account_info().equity
                        initial_order_placed = False
                        initial_trade_ticket = None
                        hedge_order_ticket = None
                        active_position_ticket = None
                        current_hedge_index = 1
                        first_hedge_activated = False
                        signal = None
                        initial_take_profit = None
                        no_pending_order_count = 0
                        no_active_position_count = 0
                        last_check_time = None
                        continue
                else:
                    no_pending_order_count = 0
                    last_check_time = None
                # Check if no active position exists
                active_position_exists = any(pos.comment == str(HEDGE_LOT_SIZES[current_hedge_index - 1]) and pos.magic == MAGIC_NUMBER for pos in positions)
                if not active_position_exists:
                    no_active_position_count += 1
                    print(f"⚠️ No active position detected for lot size {HEDGE_LOT_SIZES[current_hedge_index - 1]} (check {no_active_position_count}/2).")
                    if no_active_position_count >= 2:
                        print("❌ Two consecutive checks confirmed no active position. Closing all trades and resetting cycle.")
                        close_all_trades_and_orders()
                        initial_equity = mt5.account_info().equity
                        initial_order_placed = False
                        initial_trade_ticket = None
                        hedge_order_ticket = None
                        active_position_ticket = None
                        current_hedge_index = 1
                        first_hedge_activated = False
                        signal = None
                        initial_take_profit = None
                        no_pending_order_count = 0
                        no_active_position_count = 0
                        last_check_time = None
                        continue
                else:
                    no_active_position_count = 0
                    last_check_time = None
            if initial_take_profit and signal and check_initial_trade_tp_reached(initial_take_profit, signal):
                print(f"🎯 Initial trade hit TP ({initial_take_profit}) without hedge activation. Closing pending orders and resetting cycle.")
                close_all_trades_and_orders()
                initial_equity = mt5.account_info().equity
                initial_order_placed = False
                initial_trade_ticket = None
                hedge_order_ticket = None
                active_position_ticket = None
                current_hedge_index = 1
                first_hedge_activated = False
                signal = None
                initial_take_profit = None
                no_pending_order_count = 0
                no_active_position_count = 0
                last_check_time = None
                continue
            hedge_order_active = False
            new_active_position_ticket = None
            for pos in positions:
                if pos.comment == str(HEDGE_LOT_SIZES[current_hedge_index]) and pos.magic == MAGIC_NUMBER:
                    hedge_order_active = True
                    new_active_position_ticket = pos.ticket
                    break
            if hedge_order_active and current_hedge_index < len(HEDGE_LOT_SIZES) - 1:
                # Close the previous active position (lot size at current_hedge_index - 1)
                if close_position_by_comment(HEDGE_LOT_SIZES[current_hedge_index - 1]):
                    print(f"✅ Closed active position with lot size {HEDGE_LOT_SIZES[current_hedge_index - 1]}")
                if current_hedge_index == 1:
                    initial_trade_ticket = None  # Clear initial trade ticket only for first hedge
                active_position_ticket = new_active_position_ticket  # Update active position
                for order in orders:
                    if order.magic == MAGIC_NUMBER:
                        request = {
                            "action": mt5.TRADE_ACTION_REMOVE,
                            "order": order.ticket,
                            "symbol": order.symbol
                        }
                        mt5.order_send(request)
                        print(f"✅ Canceled pending order {order.ticket} for lot size {order.volume}")
                new_lot_size = HEDGE_LOT_SIZES[current_hedge_index + 1]
                hedge_order_ticket, hedge_price = place_hedge_market_order(signal, initial_entry_price, new_lot_size, current_hedge_index + 1)
                if hedge_order_ticket:
                    current_hedge_index += 1
            elif not orders and current_hedge_index >= len(HEDGE_LOT_SIZES) - 1:
                print("🏁 Lot size sequence exhausted. Closing all trades and resetting cycle.")
                close_all_trades_and_orders()
                initial_equity = mt5.account_info().equity
                initial_order_placed = False
                initial_trade_ticket = None
                hedge_order_ticket = None
                active_position_ticket = None
                current_hedge_index = 1
                first_hedge_activated = False
                signal = None
                initial_take_profit = None
                no_pending_order_count = 0
                no_active_position_count = 0
                last_check_time = None
                continue
            if first_hedge_activated and any(pos.comment == str(HEDGE_LOT_SIZES[current_hedge_index - 1]) and pos.magic == MAGIC_NUMBER for pos in positions) and check_equity_profit(initial_equity):
                print(f"🎯 Equity profit target of {EQUITY_TP_PIPS} pips reached. Closing all trades and resetting cycle.")
                close_all_trades_and_orders()
                initial_equity = mt5.account_info().equity
                initial_order_placed = False
                initial_trade_ticket = None
                hedge_order_ticket = None
                active_position_ticket = None
                current_hedge_index = 1
                first_hedge_activated = False
                signal = None
                initial_take_profit = None
                no_pending_order_count = 0
                no_active_position_count = 0
                last_check_time = None
                continue
        wait_for_next_candle()

# Start the trading bot
if __name__ == "__main__":
    run_bot()