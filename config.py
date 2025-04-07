import os
from dotenv import load_dotenv

load_dotenv()

EXCHANGE_WS_URL = os.getenv("EXCHANGE_WS_URL")
REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
MONGO_CONN_STRING = os.getenv("MONGO_CONN_STRING", "mongodb://localhost:27017")
MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "crypto_trading")