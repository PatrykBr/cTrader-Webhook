import os
import logging
import json
from flask import Flask, request, jsonify
from functools import wraps
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOANewOrderReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor, task
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from twisted.internet import endpoints
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment variables
HOST_TYPE = os.getenv("HOST_TYPE", "demo").lower()
APP_CLIENT_ID = os.getenv("APP_CLIENT_ID", "test_client_id")
APP_CLIENT_SECRET = os.getenv("APP_CLIENT_SECRET", "test_client_secret")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "test_access_token")
ACCOUNT_ID = int(os.getenv("ACCOUNT_ID", "0"))
AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_secure_token_here")

app = Flask(__name__)

# Global variables
is_connected = False
client = Client(
    EndPoints.PROTOBUF_LIVE_HOST if HOST_TYPE == "live" else EndPoints.PROTOBUF_DEMO_HOST,
    EndPoints.PROTOBUF_PORT,
    TcpProtocol
)

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        if not token or token != AUTH_TOKEN:
            logger.warning("Unauthorized access attempt")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

def connected(client):
    global is_connected
    is_connected = True
    logger.info("Connected to cTrader Open API")
    send_application_auth_request()

def disconnected(client, reason):
    global is_connected
    is_connected = False
    logger.warning(f"Disconnected from cTrader Open API: {reason}")
    reactor.callLater(5, client.startService)  # Attempt reconnection after 5 seconds

def on_message_received(client, message):
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("API Application authorized")
        send_account_auth_request()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        protoOAAccountAuthRes = Protobuf.extract(message)
        logger.info(f"Account {protoOAAccountAuthRes.ctidTraderAccountId} has been authorized")

def on_error(failure):
    logger.error(f"Message Error: {failure}")

def send_application_auth_request():
    request = ProtoOAApplicationAuthReq()
    request.clientId = APP_CLIENT_ID
    request.clientSecret = APP_CLIENT_SECRET
    client.send(request).addErrback(on_error)

def send_account_auth_request():
    request = ProtoOAAccountAuthReq()
    request.ctidTraderAccountId = ACCOUNT_ID
    request.accessToken = ACCESS_TOKEN
    client.send(request).addErrback(on_error)

def send_new_order_request(symbol_id, order_type, trade_side, volume):
    try:
        request = ProtoOANewOrderReq()
        request.ctidTraderAccountId = ACCOUNT_ID
        request.symbolId = int(symbol_id)
        request.orderType = ProtoOAOrderType.Value(order_type.upper())
        request.tradeSide = ProtoOATradeSide.Value(trade_side.upper())
        request.volume = int(volume * 100)  # Convert to cTrader volume units
        deferred = client.send(request)
        deferred.addCallback(on_order_placed)
        deferred.addErrback(on_error)
        return True
    except Exception as e:
        logger.error(f"Error while sending new order request: {e}")
        return False

def on_order_placed(response):
    logger.info(f"Order placed successfully: {response}")

@app.route('/health')
def health_check():
    if is_connected:
        return jsonify({"status": "healthy"}), 200
    else:
        return jsonify({"status": "unhealthy", "reason": "Not connected to cTrader API"}), 503

@app.route('/webhook', methods=['POST'])
@requires_auth
def webhook():
    try:
        data = request.json
        if not data:
            return jsonify({"error": "Invalid data"}), 400

        required_fields = ["symbolId", "tradeSide", "volume"]
        if not all(field in data for field in required_fields):
            missing_fields = [field for field in required_fields if field not in data]
            return jsonify({"error": f"Missing required fields: {', '.join(missing_fields)}"}), 400

        symbol_id = data["symbolId"]
        trade_side = data["tradeSide"].upper()
        volume = float(data["volume"])

        if trade_side not in ["BUY", "SELL"]:
            return jsonify({"error": "Trade side must be 'BUY' or 'SELL'"}), 400

        if volume <= 0:
            return jsonify({"error": "Volume must be a positive number"}), 400

        success = send_new_order_request(symbol_id, "MARKET", trade_side, volume)
        if success:
            return jsonify({"status": "Order placement initiated"}), 202
        else:
            return jsonify({"error": "Failed to place order"}), 500

    except json.JSONDecodeError:
        logger.error("Invalid JSON data received")
        return jsonify({"error": "Invalid JSON data"}), 400
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {e}")
        return jsonify({"error": "Internal server error"}), 500

def run_server(port, debug=False):
    if debug:
        app.run(host='0.0.0.0', port=port, debug=True)
    else:
        resource = WSGIResource(reactor, reactor.getThreadPool(), app)
        site = Site(resource)
        endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface='0.0.0.0')
        endpoint.listen(site)
        logger.info(f"Server running on port {port}")

def main():
    parser = argparse.ArgumentParser(description='Run the TradingView to cTrader webhook server')
    parser.add_argument('--debug', action='store_true', help='Run in debug mode')
    parser.add_argument('--test', action='store_true', help='Run in test mode (no cTrader connection)')
    parser.add_argument('--port', type=int, default=int(os.environ.get("PORT", 5000)), help='Port to run the server on')
    args = parser.parse_args()

    if args.test:
        logger.info("Running in test mode (no cTrader connection)")
        run_server(args.port, args.debug)
    else:
        run_server(args.port, args.debug)
        if not args.debug:
            client.setConnectedCallback(connected)
            client.setDisconnectedCallback(disconnected)
            client.setMessageReceivedCallback(on_message_received)
            client.startService()

            # Add a periodic check to ensure connection
            l = task.LoopingCall(lambda: client.startService() if not is_connected else None)
            l.start(60.0)  # Check every 60 seconds

            reactor.run()

if __name__ == '__main__':
    main()