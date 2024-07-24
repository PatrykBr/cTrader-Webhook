# TradingView to cTrader Webhook Server

This Python script sets up a webhook server that listens for trade information from TradingView and places the corresponding trades on cTrader using the cTrader Open API.

## Features

- Listens for POST requests from TradingView containing trade information
- Authenticates incoming requests using a token
- Connects to cTrader Open API (demo or live environment)
- Places market orders on cTrader based on received trade information
- Provides a health check endpoint
- Supports debug and test modes

## Prerequisites

- Python 3.7+

## Installation

1. Clone this repository or download the script.
2. Install the required dependencies using the provided `requirements.txt` file:

```bash
pip install -r requirements.txt
```

This will install all necessary dependencies, including Flask, ctrader_open_api, and Twisted.

## Configuration

Set the following environment variables:

- `HOST_TYPE`: "demo" or "live" (default: "demo")
- `APP_CLIENT_ID`: Your cTrader Open API client ID
- `APP_CLIENT_SECRET`: Your cTrader Open API client secret
- `ACCESS_TOKEN`: Your cTrader Open API access token
- `ACCOUNT_ID`: Your cTrader account ID
- `AUTH_TOKEN`: A secure token for webhook authentication
- `PORT`: The port to run the server on (default: 5000)

## Usage

Run the script using:

```bash
python script_name.py [--debug] [--test] [--port PORT]
```

Options:
- `--debug`: Run in debug mode
- `--test`: Run in test mode (no cTrader connection)
- `--port`: Specify the port to run the server on

## Endpoints

1. Health Check: GET `/health`
2. Webhook: POST `/webhook`

### Webhook Payload

The webhook expects a JSON payload with the following structure:

```json
{
  "symbolId": 1234,
  "tradeSide": "BUY",
  "volume": 0.01
}
```

- `symbolId`: The cTrader symbol ID
- `tradeSide`: "BUY" or "SELL"
- `volume`: The trade volume

## Security

- The webhook is protected by a token-based authentication system.
- Include the token as a query parameter in the webhook URL: `/webhook?token=your_secure_token_here`

## Error Handling

The script includes error handling for various scenarios, including:
- Invalid JSON data
- Missing required fields
- Invalid trade side or volume
- Connection issues with cTrader API

## Logging

The script uses Python's logging module to provide informative logs about its operation, connections, and any errors that occur.

## Note

This script is designed to run continuously. It will attempt to reconnect to the cTrader API if the connection is lost.

## Disclaimer

This script is for educational purposes only. Use it at your own risk. Always test thoroughly before using in a live trading environment.