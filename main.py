import asyncio
import websockets
import json
import logging
import time
import config
from datetime import datetime, timezone, date
import persistence
import historical
import signal_calculator

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(filename)s:%(lineno)d - %(message)s')

async def websocket_listener(queue: asyncio.Queue, redis_client):
    url = config.EXCHANGE_WS_URL
    while True:
        try:
            async with websockets.connect(url) as ws:
                logging.info(f"WebSocket connected to {url}")
                await persistence.update_websocket_status(redis_client, "connected")
                while True:
                    try:
                        message = await ws.recv()
                        data = json.loads(message)

                        processing_ts = time.time()
                        best_bid_str = data.get('b')
                        best_ask_str = data.get('a')
                        symbol = data.get('s')
                        update_id = data.get('u')

                        if best_bid_str and best_ask_str and symbol == 'BTCUSDT':
                            try:
                                best_bid = float(best_bid_str)
                                best_ask = float(best_ask_str)

                                await queue.put({
                                    'ts': processing_ts,
                                    'bid': best_bid,
                                    'ask': best_ask,
                                    'update_id': update_id
                                })
                            except (ValueError, TypeError) as parse_err:
                                logging.warning(f"Could not parse data types in message: {data}, Error: {parse_err}")

                    except websockets.ConnectionClosed:
                        logging.warning("WebSocket connection closed.")
                        await persistence.update_websocket_status(redis_client, "disconnected")
                        break # to trigger reconnect
                    except json.JSONDecodeError:
                        logging.warning(f"Could not decode JSON: {message}")
                    except Exception as e:
                        logging.error(f"Error processing WebSocket message: {e}", exc_info=True)
        
        except (websockets.exceptions.ConnectionClosedError, ConnectionRefusedError, OSError) as e:
            logging.error(f"WebSocket connection failed: {e}")
            await persistence.update_websocket_status(redis_client, "error")
        except Exception as e:
            logging.error(f"Unexpected error in WebSocket listener: {e}", exc_info=True)
            await persistence.update_websocket_status(redis_client, "error")
        
        logging.info("Attempting to reconnect in 5 seconds...")
        await asyncio.sleep(5) # simple backoff

async def data_processor(queue: asyncio.Queue, redis_client, mongo_db):
    logging.info("Data processor started.")
    current_day: date | None = None
    last_mid_price: float | None = None
    symbol = signal_calculator.SYMBOL

    while True:
        try:
            item = await queue.get()
            timestamp = item['ts']
            bid = item['bid']
            ask = item['ask']

            if bid <= 0 or ask <= 0:
                logging.warning(f"Received invalid bid/ask price: {item}")
                queue.task_done()
                continue

            mid_price = (bid + ask) / 2.0

            event_dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
            event_date = event_dt.date()

            # first run init
            if current_day is None:
                current_day = event_date
                last_mid_price = mid_price
                logging.info(f"Processor initialized. Current day set to: {current_day}, Initial mid: {mid_price:.2f}")
                queue.task_done()
                continue

            # day change check
            if event_date > current_day:
                logging.info(f"Day boundary crossed. Old day: {current_day}, New day: {event_date}")

                if last_mid_price is not None:
                    derived_close_price = last_mid_price
                    derived_close_day = current_day # most recent day
                    logging.info(f"*** [{symbol}] Derived Close for {derived_close_day}: {derived_close_price:.2f} ***")

                    await persistence.save_derived_price(mongo_db, derived_close_day, derived_close_price, symbol)
                    await persistence.add_derived_price_to_cache(redis_client, symbol, derived_close_price, signal_calculator.LONG_SMA_PERIOD + 50)

                    logging.info(f"[{symbol}] Triggering SMA crossover check for completed day: {derived_close_day}")
                    asyncio.create_task(
                        signal_calculator.check_sma_crossover(
                            redis_client=redis_client,
                            mongo_db=mongo_db,
                            calculation_date=derived_close_day,
                            derived_close_price=derived_close_price
                        )
                    )
                else:
                    logging.warning(f"[{symbol}] Day boundary crossed but last_mid_price was None for {current_day}. Skipping derived close.")
                
                # update state for the new day
                current_day = event_date
                last_mid_price = mid_price
            
            elif event_date == current_day:
                # same day, just updating the last known price
                last_mid_price = mid_price
            
            else: # should not happen in live feed
                logging.warning(f"Received data from the past.")
            
            queue.task_done()
        
        except KeyError as e:
            logging.error(f"Missing key in queue item: {e}. Item: {item if 'item' in locals() else 'unknown'}")
            if 'queue' in locals():
                queue.task_done() # marking to prevent blocking
        except Exception as e:
            logging.error(f"Error in data processor: {e}", exc_info=True)
            await asyncio.sleep(1) # small delay before retrying to prevent fast error loops

async def main():
    logging.info("Starting application...")

    try:
        await persistence.setup_databases()
        redis_client = persistence.get_redis_client()
        mongo_db = persistence.get_mongo_db()

        await historical.fetch_historical_data(redis_client, mongo_db)
        
        data_queue = asyncio.Queue(maxsize=1000) # defining a maxsize to prevent infinite growth

        listener_task = asyncio.create_task(websocket_listener(data_queue, redis_client))
        processor_task = asyncio.create_task(data_processor(data_queue, redis_client, mongo_db))

        # weakness: if one task crashes, gather will exit. need more robust supervision here
        await asyncio.gather(
            listener_task,
            processor_task
        )
    
    except ConnectionError as e:
        logging.critical(f"Failed to start application due to DB connection error: {e}")
    except Exception as e:
        logging.critical(f"Application failed critically during main execution: {e}", exc_info=True)
    finally:
        await persistence.close_databases()
        logging.info("Application shutdown complete.")

if __name__ == "__main__":
    asyncio.run(main())