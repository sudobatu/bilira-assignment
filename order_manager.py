import logging
import asyncio
from datetime import datetime, timezone
import persistence
import historical

SYMBOL = historical.SYMBOL

async def process_signal(redis_client, mongo_db, signal_type: str, price_at_signal: float):
    logging.info(f"[{SYMBOL}] Order Manager received signal: {signal_type} at price {price_at_signal:.2f}")

    # get current position state from Redis
    current_position = await persistence.get_position(redis_client, SYMBOL)
    if current_position is None:
        # init position if it doesn't exist
        logging.info(f"[{SYMBOL}] No existing position found in Redis. Initializing to FLAT.")
        current_position = "FLAT"

    logging.info(f"[{SYMBOL}] Current position state: {current_position}")

    order_to_log = None
    new_position = current_position # default to no change

    # determine action based on signal and current position
    if signal_type == "BUY":
        if current_position == "FLAT":
            logging.info(f"[{SYMBOL}] BUY signal received while FLAT. Simulating MARKET BUY order.")
            order_to_log = {
                'timestamp': datetime.now(timezone.utc), # order placement time
                'symbol': SYMBOL,
                'side': 'BUY',
                'type': 'MARKET', # assuming market orders for simplicity
                'price': price_at_signal, # price at which the signal occurred
                'status': 'SIMULATED_FILLED', # instantly filled in simulation
                'signal_based_on_date': datetime.combine(datetime.now(timezone.utc).date() - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) if datetime.now(timezone.utc).hour < 1 else datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc) # the date the signal derived from, rough estimate
            }
            new_position = "LONG"
        else: # already LONG
            logging.info(f"[{SYMBOL}] BUY signal received but already LONG. No action taken.")

    elif signal_type == "SELL":
        if current_position == "LONG":
            logging.info(f"[{SYMBOL}] SELL signal received while LONG. Simulating MARKET SELL order.")
            order_to_log = {
                'timestamp': datetime.now(timezone.utc),
                'symbol': SYMBOL,
                'side': 'SELL',
                'type': 'MARKET',
                'price': price_at_signal,
                'status': 'SIMULATED_FILLED',
                'signal_based_on_date': datetime.combine(datetime.now(timezone.utc).date() - timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) if datetime.now(timezone.utc).hour < 1 else datetime.combine(datetime.now(timezone.utc).date(), datetime.min.time(), tzinfo=timezone.utc) # the date the signal derived from, rough estimate
            }
            new_position = "FLAT"
        else: # already FLAT
            logging.info(f"[{SYMBOL}] SELL signal received but already FLAT. No action taken.")

    else:
        logging.warning(f"[{SYMBOL}] Order Manager received unknown signal type: {signal_type}")


    # if an order was generated, log it and update position state
    if order_to_log:
        try:
            await persistence.save_order(mongo_db, order_to_log)
            logging.info(f"[{SYMBOL}] Successfully logged simulated {order_to_log['side']} order to MongoDB.")

            # update position state in Redis *after* successfully logging order
            await persistence.set_position(redis_client, SYMBOL, new_position)
            logging.info(f"[{SYMBOL}] Position state updated in Redis to: {new_position}")

        except Exception as e:
            logging.error(f"[{SYMBOL}] Failed to log order or update position for signal {signal_type}: {e}", exc_info=True)

    else:
        logging.debug(f"[{SYMBOL}] No order generated for signal {signal_type} and position {current_position}.")