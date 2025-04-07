import logging
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as redis
from datetime import date, datetime, timezone
from config import MONGO_CONN_STRING, MONGO_DB_NAME, REDIS_HOST, REDIS_PORT

_mongo_client = None
_redis_client = None

def get_mongo_db():
    global _mongo_client
    if _mongo_client is None:
        raise ConnectionError("MongoDB client not initialized.")
    return _mongo_client[MONGO_DB_NAME]

def get_redis_client():
    global _redis_client
    if _redis_client is None:
        raise ConnectionError("Redis client not initialized.")
    return _redis_client

async def setup_databases():
    global _mongo_client, _redis_client
    logging.info("Setting up database connections...")
    try:
        _mongo_client = AsyncIOMotorClient(MONGO_CONN_STRING)
        await _mongo_client.admin.command('ping') # ensuring connection
        logging.info(f"MongoDB connected successfully to {MONGO_CONN_STRING}")

        _redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        await _redis_client.ping() # ensuring connection
        logging.info(f"Redis connected successfully to {REDIS_HOST}:{REDIS_PORT}")
    
    except Exception as e:
        logging.critical(f"Database connection failed: {e}", exc_info=True)
        raise

async def close_databases():
    global _mongo_client, _redis_client
    if _redis_client:
        await _redis_client.close()
        logging.info("Redis connection closed.")
    if _mongo_client:
        _mongo_client.close()
        logging.info("MongoDB connection closed.")

async def save_derived_price(db, day_date: date, price: float, symbol: str):
    collection = db['daily_derived_prices']
    date_str = day_date.isoformat() # string date as key
    logging.debug(f"Saving derived price to Mongo: Date={date_str}, Price={price}, Symbol={symbol}")
    try:
        await collection.update_one(
            {'date': date_str, 'symbol': symbol},
            {'$set': {'price': price, 'timestamp_utc': datetime.combine(day_date, datetime.min.time(), tzinfo=timezone.utc)}},
            upsert=True # insert if not exists
        )
        logging.debug(f"Successfully saved price for {date_str} / {symbol}")
    except Exception as e:
        logging.error(f"Failed to save derived price for {date_str} / {symbol}: {e}", exc_info=True)

async def add_derived_price_to_cache(redis_client, symbol: str, price: float, max_len: int = 250):
    key = f"prices:{symbol}:derived_1d"
    logging.debug(f"Adding derived price to Redis Cache: Key={key}, Price={price}")
    try:
        # LPUSH adds to the beginning (left) of the list
        await redis_client.lpush(key, str(price))
        # LTRIM keeps only the latest `max_len` elements
        await redis_client.ltrim(key, 0, max_len - 1)
        logging.debug(f"Successfully updated Redis cache for {symbol}")
    except Exception as e:
        logging.error(f"Failed to update Redis cache for {key}: {e}", exc_info=True)

async def get_prices_from_cache(redis_client, symbol: str, count: int = 200) -> list[float]:
    key = f"prices:{symbol}:derived_1d"
    try:
        # LRANGE 0 to count-1 gets the first 'count' elements (most recent due to LPUSH)
        price_strings = await redis_client.lrange(key, 0, count - 1)
        prices = [float(p) for p in price_strings]
        logging.debug(f"Retrieved {len(prices)} prices from cache for {symbol}")
        return prices
    except Exception as e:
        logging.error(f"Failed to retrieve prices from Redis cache for {key}: {e}", exc_info=True)
        return []

# todo placeholders

async def save_signal(db, signal_data: dict):
    collection = db['signals']
    logging.info(f"Saving signal to Mongo: {signal_data}")
    try:
        await collection.insert_one(signal_data)
    except Exception as e:
        logging.error(f"Failed to save signal: {e}", exc_info=True)

async def save_order(db, order_data: dict):
    collection = db['orders']
    logging.info(f"Saving order to Mongo: {order_data}")
    try:
        await collection.insert_one(order_data)
    except Exception as e:
        logging.error(f"Failed to save order: {e}", exc_info=True)

async def get_position(redis_client, symbol: str) -> str | None:
    key = f"position:{symbol}"
    try:
        position = await redis_client.get(key)
        return position # returns None if key doesn't exist
    except Exception as e:
        logging.error(f"Failed to get position for {symbol}: {e}", exc_info=True)
        return None # indicate error or inability to fetch

async def set_position(redis_client, symbol: str, state: str):
    key = f"position:{symbol}"
    logging.info(f"Setting position for {symbol} to {state}")
    try:
        await redis_client.set(key, state)
    except Exception as e:
        logging.error(f"Failed to set position for {symbol}: {e}", exc_info=True)

async def get_previous_smas(redis_client, symbol: str) -> tuple[float | None, float | None]:
    key = f"previous_sma:{symbol}"
    try:
        # HGETALL to get both values at once
        sma_values = await redis_client.hgetall(key)
        sma50 = float(sma_values.get('sma_50')) if sma_values.get('sma_50') else None
        sma200 = float(sma_values.get('sma_200')) if sma_values.get('sma_200') else None
        return sma50, sma200
    except Exception as e:
        logging.error(f"Failed to get previous SMAs for {symbol}: {e}", exc_info=True)
        return None, None

async def set_previous_smas(redis_client, symbol: str, sma_short: float, sma_long: float):
    key = f"previous_sma:{symbol}"
    logging.debug(f"Setting previous SMAs for {symbol}: 50={sma_short}, 200={sma_long}")
    try:
        # HMSET or HSET multiple fields
        await redis_client.hset(key, mapping={'sma_50': str(sma_short), 'sma_200': str(sma_long)})
    except Exception as e:
        logging.error(f"Failed to set previous SMAs for {symbol}: {e}", exc_info=True)

async def update_websocket_status(redis_client, status: str):
    key = "websocket_status:BTCUSDT" # example key
    try:
        await redis_client.set(key, status)
        logging.debug(f"Updated websocket status to: {status}")
    except Exception as e:
        logging.warning(f"Could not update websocket status in Redis: {e}")