import logging
import httpx # httpx for async requests
import asyncio
from datetime import datetime, timedelta, timezone
import persistence

# exchange API details
BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
SYMBOL = "BTCUSDT"
INTERVAL = "1d"
DAYS_HISTORY_NEEDED = 250 # Need > 200 for SMA(200)

async def fetch_historical_data(redis_client, db):
    logging.info(f"Starting historical data fetch for {SYMBOL} ({DAYS_HISTORY_NEEDED} days)...")

    # start date
    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(days=DAYS_HISTORY_NEEDED)

    # convert times to milliseconds timestamp for Binance API
    start_ts_ms = int(start_time.timestamp() * 1000)
    end_ts_ms = int(end_time.timestamp() * 1000)

    params = {
        'symbol': SYMBOL,
        'interval': INTERVAL,
        'startTime': start_ts_ms,
        'endTime': end_ts_ms,
        'limit': DAYS_HISTORY_NEEDED + 50 # fetching slightly more for safety
    }

    prices_to_cache = []
    documents_to_save = []

    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(BINANCE_KLINE_URL, params=params)
            response.raise_for_status() # raise exception for 4xx/5xx errors
            klines = response.json()

            logging.info(f"Fetched {len(klines)} historical klines from API.")

            if not klines:
                logging.warning("No historical klines received from API.")
                return

            for kline in klines:
                # binance kline format: [open_time, open, high, low, close, volume, close_time, ...]
                try:
                    close_time_ms = kline[6]
                    close_price_str = kline[4]

                    close_price = float(close_price_str)
                    # close_time to determine the date the candle represents
                    close_dt = datetime.fromtimestamp(close_time_ms / 1000.0, tz=timezone.utc)
                    day_date = close_dt.date()

                    prices_to_cache.append(close_price)

                    # document for MongoDB bulk insert
                    documents_to_save.append({
                        'date': day_date.isoformat(),
                        'symbol': SYMBOL,
                        'price': close_price,
                        'timestamp_utc': close_dt,
                        'is_historical': True # flag as historical data
                    })

                except (IndexError, ValueError, TypeError) as e:
                    logging.warning(f"Could not parse historical kline: {kline}, Error: {e}")
                    continue

            if documents_to_save:
                 collection = db['daily_derived_prices']
                 logging.info(f"Saving {len(documents_to_save)} historical prices to MongoDB...")
                 try:
                      from pymongo import UpdateOne
                      bulk_ops = [
                          UpdateOne(
                              {'date': doc['date'], 'symbol': doc['symbol']},
                              {'$set': doc},
                              upsert=True
                          ) for doc in documents_to_save
                      ]
                      await collection.bulk_write(bulk_ops, ordered=False)
                      logging.info("Bulk save to MongoDB complete.")
                 except Exception as e:
                      logging.error(f"MongoDB bulk save failed: {e}", exc_info=True)
            else:
                logging.warning("No valid historical documents to save to MongoDB.")

            if prices_to_cache:
                key = f"prices:{SYMBOL}:derived_1d"
                logging.info(f"Populating Redis cache '{key}' with {len(prices_to_cache)} historical prices...")
                try:
                    await redis_client.delete(key) # clear old cache
                    # push prices (convert to string for Redis) - push oldest first so newest are at head
                    await redis_client.lpush(key, *[str(p) for p in reversed(prices_to_cache)])
                    # trim to ensure correct size
                    await redis_client.ltrim(key, 0, DAYS_HISTORY_NEEDED - 1)
                    logging.info(f"Redis cache '{key}' populated.")
                except Exception as e:
                    logging.error(f"Failed to populate Redis cache '{key}': {e}", exc_info=True)
            else:
                 logging.warning("No valid historical prices to cache in Redis.")


    except httpx.HTTPStatusError as e:
        logging.error(f"HTTP error fetching historical data: {e.response.status_code} - {e.response.text}")
    except httpx.RequestError as e:
        logging.error(f"Network error fetching historical data: {e}")
    except Exception as e:
        logging.error(f"Unexpected error fetching historical data: {e}", exc_info=True)

    logging.info("Historical data fetch process finished.")