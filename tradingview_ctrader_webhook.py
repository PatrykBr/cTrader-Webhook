import os
import logging
from flask import Flask, request, jsonify, Response
from functools import wraps
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes,
    ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOANewOrderReq
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from twisted.internet import endpoints
import json
import argparse
import time
from twisted.internet import task

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Environment variables with defaults for local testing
HOST_TYPE = os.getenv("HOST_TYPE", "demo").lower()
APP_CLIENT_ID = os.getenv("APP_CLIENT_ID", "test_client_id")
APP_CLIENT_SECRET = os.getenv("APP_CLIENT_SECRET", "test_client_secret")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "test_access_token")
ACCOUNT_ID = int(os.getenv("ACCOUNT_ID", "0"))
WEBHOOK_USER = os.getenv("WEBHOOK_USER", "test_user")
WEBHOOK_PASS = os.getenv("WEBHOOK_PASS", "test_pass")

# Global variable to track connection status
is_connected = False

client = Client(EndPoints.PROTOBUF_LIVE_HOST if HOST_TYPE == "live" else EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)

def connected(client):
    global is_connected
    is_connected = True
    logger.info("Connected to cTrader Open API")
    request = ProtoOAApplicationAuthReq()
    request.clientId = APP_CLIENT_ID
    request.clientSecret = APP_CLIENT_SECRET
    deferred = client.send(request)
    deferred.addErrback(onError)

def disconnected(client, reason):
    global is_connected
    is_connected = False
    logger.warning(f"Disconnected from cTrader Open API: {reason}")
    reconnect()

def reconnect():
    global is_connected
    max_retries = 5
    retry_delay = 5  # Start with a 5-second delay

    def attempt_reconnect():
        nonlocal max_retries, retry_delay
        if is_connected:
            return

        try:
            logger.info(f"Attempting to reconnect (attempts left: {max_retries})")
            client.startService()
        except Exception as e:
            logger.error(f"Reconnection attempt failed: {e}")
            max_retries -= 1
            if max_retries > 0:
                retry_delay *= 2  # Exponential backoff
                reactor.callLater(retry_delay, attempt_reconnect)
            else:
                logger.critical("Failed to reconnect after multiple attempts")

    attempt_reconnect()

def onMessageReceived(client, message):
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("API Application authorized")
        sendProtoOAAccountAuthReq()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        protoOAAccountAuthRes = Protobuf.extract(message)
        logger.info(f"Account {protoOAAccountAuthRes.ctidTraderAccountId} has been authorized")

def onError(failure):
    logger.error(f"Message Error: {failure}")

def sendProtoOAAccountAuthReq(clientMsgId=None):
    request = ProtoOAAccountAuthReq()
    request.ctidTraderAccountId = ACCOUNT_ID
    request.accessToken = ACCESS_TOKEN
    deferred = client.send(request, clientMsgId=clientMsgId)
    deferred.addErrback(onError)

def sendProtoOANewOrderReq(symbolId, orderType, tradeSide, volume, clientMsgId=None):
    try:
        request = ProtoOANewOrderReq()
        request.ctidTraderAccountId = ACCOUNT_ID
        request.symbolId = int(symbolId)
        request.orderType = ProtoOAOrderType.Value(orderType.upper())
        request.tradeSide = ProtoOATradeSide.Value(tradeSide.upper())
        request.volume = int(volume) * 100
        deferred = client.send(request, clientMsgId=clientMsgId)
        deferred.addCallback(onOrderPlaced)
        deferred.addErrback(onError)
        return True
    except Exception as e:
        logger.error(f"Error while sending new order request: {e}")
        return False

def onOrderPlaced(response):
    logger.info(f"Order placed successfully: {response}")

def check_auth(username, password):
    return username == WEBHOOK_USER and password == WEBHOOK_PASS

def authenticate():
    return Response(
        'Authentication required', 401,
        {'WWW-Authenticate': 'Basic realm="Login Required"'})

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_auth(auth.username, auth.password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated

@app.route('/')
def index():
    return "Webhook listener for TradingView to cTrader is running."

@app.route('/health')
def health_check():
    global is_connected
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

        symbolId = data["symbolId"]
        tradeSide = data["tradeSide"].upper()
        volume = data["volume"]

        if tradeSide not in ["BUY", "SELL"]:
            return jsonify({"error": "Trade side must be 'BUY' or 'SELL'"}), 400

        if not isinstance(volume, (int, float)) or volume <= 0:
            return jsonify({"error": "Volume must be a positive number"}), 400

        # Place the order directly
        success = sendProtoOANewOrderReq(symbolId, "MARKET", tradeSide, volume)
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

def run_twisted():
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(onMessageReceived)
    client.startService()
    reactor.run()

if __name__ == '__main__':
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
            run_twisted()

    # Add a periodic check to ensure connection
    l = task.LoopingCall(lambda: client.startService() if not is_connected else None)
    l.start(60.0)  # Check every 60 seconds