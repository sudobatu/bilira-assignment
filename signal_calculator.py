import logging
import asyncio
from datetime import date, datetime, timezone
import persistence
import historical
import order_manager

SHORT_SMA_PERIOD = 50
LONG_SMA_PERIOD = 200
SYMBOL = historical.SYMBOL

def calculate_sma(prices: list[float], period: int) -> float | None:
    if not prices or len(prices) < period:
        return None # not enough data
    # most recent 'period' prices (which are at the start of the list due to LPUSH)
    relevant_prices = prices[:period]
    try:
        return sum(relevant_prices) / period
    except ZeroDivisionError:
        return None # should not happen if len check passes, just in case

async def check_sma_crossover(redis_client, mongo_db, calculation_date: date, derived_close_price: float):
    # this function is triggered after a new daily price is derived and saved
    logging.info(f"[{SYMBOL}] Checking SMA crossover for date: {calculation_date}")

    # fetch required price history from Redis cache
    # need at least LONG_SMA_PERIOD prices for the longest SMA
    prices = await persistence.get_prices_from_cache(redis_client, SYMBOL, count=LONG_SMA_PERIOD)

    if not prices:
        logging.warning(f"[{SYMBOL}] No prices found in cache. Cannot calculate SMAs for {calculation_date}.")
        return

    # check if enough data exists
    if len(prices) < LONG_SMA_PERIOD:
        logging.warning(f"[{SYMBOL}] Insufficient price data ({len(prices)} points) for {LONG_SMA_PERIOD}-day SMA. Need {LONG_SMA_PERIOD}. Skipping crossover check for {calculation_date}.")
        # optional: still calculate and store short SMA if possible
        current_sma_short = calculate_sma(prices, SHORT_SMA_PERIOD)
        if current_sma_short is not None:
             # storing only the short SMA if long isn't available yet
             # waits until both are calculable
             logging.info(f"[{SYMBOL}] Short SMA ({SHORT_SMA_PERIOD}d) calculable: {current_sma_short:.2f}, but waiting for enough data for long SMA.")
        return # exit until enough data for both SMAs is available

    # calculate current SMAs
    current_sma_short = calculate_sma(prices, SHORT_SMA_PERIOD)
    current_sma_long = calculate_sma(prices, LONG_SMA_PERIOD)

    if current_sma_short is None or current_sma_long is None:
        logging.error(f"[{SYMBOL}] Failed to calculate one or both SMAs for {calculation_date} even with sufficient data points. Short={current_sma_short}, Long={current_sma_long}")
        return # exit if calculation failed unexpectedly

    logging.info(f"[{SYMBOL}] Calculated SMAs for {calculation_date}: SMA{SHORT_SMA_PERIOD}={current_sma_short:.2f}, SMA{LONG_SMA_PERIOD}={current_sma_long:.2f}")

    # fetch previous day's SMAs
    prev_sma_short, prev_sma_long = await persistence.get_previous_smas(redis_client, SYMBOL)
    logging.debug(f"[{SYMBOL}] Previous SMAs fetched: SMA{SHORT_SMA_PERIOD}={prev_sma_short}, SMA{LONG_SMA_PERIOD}={prev_sma_long}")


    # storing current SMAs for the *next* day's comparison
    try:
         await persistence.set_previous_smas(redis_client, SYMBOL, current_sma_short, current_sma_long)
         logging.debug(f"[{SYMBOL}] Stored current SMAs ({current_sma_short:.2f}, {current_sma_long:.2f}) as 'previous' for next calculation.")
    except Exception as e:
         logging.error(f"[{SYMBOL}] Failed to store current SMAs in Redis: {e}", exc_info=True)

    # crossover Detection (requires previous values)
    if prev_sma_short is None or prev_sma_long is None:
        logging.info(f"[{SYMBOL}] Previous SMA values not found (likely first run after backfill). Cannot determine crossover for {calculation_date}.")
        return # cannot detect crossover without previous state

    signal = None
    reason = ""

    # check for Golden Cross (BUY)
    if current_sma_short > current_sma_long and prev_sma_short <= prev_sma_long:
        signal = "BUY"
        reason = f"SMA{SHORT_SMA_PERIOD} crossed above SMA{LONG_SMA_PERIOD}"
        logging.info(f"*** [{SYMBOL}] BUY SIGNAL DETECTED (Golden Cross) on {calculation_date} ***")

    # check for Death Cross (SELL)
    elif current_sma_short < current_sma_long and prev_sma_short >= prev_sma_long:
        signal = "SELL"
        reason = f"SMA{SHORT_SMA_PERIOD} crossed below SMA{LONG_SMA_PERIOD}"
        logging.info(f"*** [{SYMBOL}] SELL SIGNAL DETECTED (Death Cross) on {calculation_date} ***")

    # if a signal is generated, save it and trigger order manager
    if signal:
        signal_time = datetime.combine(calculation_date, datetime.min.time(), tzinfo=timezone.utc) # signal relates to the completed day
        signal_data = {
            'timestamp': signal_time,
            'symbol': SYMBOL,
            'signal_type': signal,
            'reason': reason,
            'price_at_signal': derived_close_price, # the price for the day the signal is based on
            f'sma_{SHORT_SMA_PERIOD}': current_sma_short,
            f'sma_{LONG_SMA_PERIOD}': current_sma_long,
            'calculation_ran_at': datetime.now(timezone.utc) # record when this logic actually ran
        }

        await persistence.save_signal(mongo_db, signal_data)

        logging.info(f"[{SYMBOL}] Triggering Order Manager for {signal} signal...")
        asyncio.create_task(
            order_manager.process_signal(
                redis_client=redis_client,
                mongo_db=mongo_db,
                signal_type=signal,
                price_at_signal=derived_close_price
            )
        )

    else:
        logging.info(f"[{SYMBOL}] No SMA crossover detected for {calculation_date}.")