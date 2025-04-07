Crypto Trading Application - Local Setup Guide

This document describes how to set up, run, and perform basic verification of the Crypto Trading Application on your local machine for development and testing purposes.

Prerequisites

Before you begin, ensure you have the following installed on your system:

Git: For cloning the repository. (Download Git: https://git-scm.com/)

Docker & Docker Compose: For running dependencies (Redis, MongoDB) easily in containers. (Install Docker: https://docs.docker.com/get-docker/)

Python: Version 3.11 or compatible (as used in the project). Ensure pip is available. (Download Python: https://www.python.org/)

Python Virtual Environment Tool: venv (usually included with Python).

Get the Code

Clone the repository from GitHub to your local machine:

bash
git clone https://github.com/sudobatu/bilira-assignment.git
cd bilira-assignment

Set Up Dependencies (Redis & MongoDB)

We use Docker Compose to quickly spin up the required Redis and MongoDB services.

Make sure Docker Desktop (or Docker daemon) is running.
Navigate to the project's root directory (where docker-compose.yml is located).
Run the following command to start the services in detached mode:

bash
docker-compose up -d

Verify services are running: You can check the status of the containers:

bash
docker ps

You should see containers listed for redis and mongo.

Configure the Application

The application uses environment variables for configuration, loaded from a .env file.

The .env file is typically ignored by Git (check .gitignore). You'll need to create it.
You can copy an example if one exists (cp .env.example .env) or create a new file named .env in the project root directory.
Add the following content to your .env file for local development connecting to the Docker Compose services:

dotenv

.env
Use the appropriate WebSocket URL for the exchange (e.g., Binance bookTicker)
EXCHANGE_WS_URL=wss://stream.binance.com:9443/ws/btcusdt@bookTicker

--- IMPORTANT ---
When running the Python app directly on your host machine (NOT in Docker),
connect to Redis/Mongo via localhost and the ports exposed in docker-compose.yml
REDIS_HOST=localhost
REDIS_PORT=6379
MONGO_CONN_STRING=mongodb://localhost:27017
MONGO_DB_NAME=crypto_trading

Set Up Python Environment & Install Dependencies

It's highly recommended to use a Python virtual environment to manage project dependencies.

Create a virtual environment: (Run from the project root)

bash
python -m venv venv

Activate the virtual environment:
macOS / Linux:

bash
source venv/bin/activate

Windows (Command Prompt):

bash
venv\Scripts\activate.bat

Windows (PowerShell):

bash
venv\Scripts\Activate.ps1

(You might need to adjust execution policy: Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process)
Your terminal prompt should now indicate you are in the (venv).

Install Python packages:

bash
pip install -r requirements.txt

Run the Application

With the virtual environment activated and dependencies installed, run the main script:

bash
python main.py

The application will start logging output to your console.
You should see logs indicating:
Database connections being established.
Historical data being fetched (this runs only once on startup if data isn't already present or needs refresh based on logic).
WebSocket connection attempt and success.
Data processor initialization.

To stop the application: Press Ctrl+C in the terminal where it's running.

Basic Verification and Testing

While the application is running:

Observe Logs:
Check for successful connection messages for Redis, MongoDB, and the WebSocket.
See the "Processor initialized" message.
The application will mostly run silently, processing ticks.
After midnight UTC: Watch for the "Derived Close for..." log, followed by "Triggering SMA crossover check...".
If an SMA crossover occurs, look for "BUY/SELL SIGNAL DETECTED", "Saving signal...", "Triggering Order Manager...", and subsequent logs from the order manager about simulated orders and position updates.
Check for any ERROR or WARNING messages.

Check Redis State:
You can use redis-cli (if installed locally) or connect via a Docker command:

bash
docker exec -it crypto-trader_redis_1 redis-cli

(Replace crypto-trader_redis_1 if your container name is different - check 'docker ps')
Inside redis-cli:
Check historical/derived prices: LRANGE prices:BTCUSDT:derived_1d 0 -1 (Should show ~250 prices after initial run)
Check position: GET position:BTCUSDT (Will be nil initially, then FLAT or LONG)
Check previous SMAs: HGETALL previous_sma:BTCUSDT (Populated after the first daily calculation)
Check WebSocket status: GET websocket_status:BTCUSDT
Type exit to leave redis-cli.

Check MongoDB Data:
Use a tool like MongoDB Compass or the mongosh shell to connect to mongodb://localhost:27017.
Navigate to the crypto_trading database.
Check collections:
daily_derived_prices: Should contain historical data (is_historical: true) and prices derived from the live feed.
signals: Should contain documents if any SMA crossover signals were generated.
orders: Should contain documents for simulated BUY/SELL orders if signals led to trades.

Stopping Dependencies

When you are finished testing:

Stop and remove the Redis and MongoDB containers started by Docker Compose:

bash
docker-compose down

(Note: This command with the default docker-compose.yml might remove the data stored in the volumes unless persistent volumes are configured differently).

This guide provides the essential steps for running the application locally. Refer to the specific code modules for more implementation details.
