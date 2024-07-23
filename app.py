from flask import Flask, request, jsonify
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.endpoints import EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from twisted.internet import reactor
import logging
import os

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Global variables
client = None
current_account_id = None

def initialize_client():
    global client, current_account_id
    
    host_type = os.environ.get('HOST_TYPE', 'demo').lower()
    app_client_id = os.environ.get('APP_CLIENT_ID')
    app_client_secret = os.environ.get('APP_CLIENT_SECRET')
    access_token = os.environ.get('ACCESS_TOKEN')
    current_account_id = int(os.environ.get('ACCOUNT_ID'))

    if not all([host_type, app_client_id, app_client_secret, access_token, current_account_id]):
        raise ValueError("Missing required environment variables")

    host = EndPoints.PROTOBUF_LIVE_HOST if host_type == 'live' else EndPoints.PROTOBUF_DEMO_HOST
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)

    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message_received)

    client.startService()

def on_connected(client):
    logger.info("Connected")
    request = ProtoOAApplicationAuthReq(clientId=os.environ.get('APP_CLIENT_ID'), clientSecret=os.environ.get('APP_CLIENT_SECRET'))
    deferred = client.send(request)
    deferred.addErrback(on_error)

def on_disconnected(client, reason):
    logger.info(f"Disconnected: {reason}")

def on_message_received(client, message):
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("API Application authorized")
        send_account_auth_req()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        account_auth_res = Protobuf.extract(message)
        logger.info(f"Account {account_auth_res.ctidTraderAccountId} has been authorized")
    else:
        logger.info(f"Message received: {Protobuf.extract(message)}")

def on_error(failure):
    logger.error(f"Message Error: {failure}")

def send_account_auth_req():
    request = ProtoOAAccountAuthReq(ctidTraderAccountId=current_account_id, accessToken=os.environ.get('ACCESS_TOKEN'))
    deferred = client.send(request)
    deferred.addErrback(on_error)

def send_new_market_order(symbol_id, trade_side, volume):
    request = ProtoOANewOrderReq(
        ctidTraderAccountId=current_account_id,
        symbolId=int(symbol_id),
        orderType=ProtoOAOrderType.MARKET,
        tradeSide=ProtoOATradeSide.Value(trade_side.upper()),
        volume=int(volume) * 100
    )
    deferred = client.send(request)
    deferred.addErrback(on_error)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "No data provided"}), 400

    symbol_id = data.get('symbol_id')
    trade_side = data.get('trade_side')
    volume = data.get('volume')

    if not all([symbol_id, trade_side, volume]):
        return jsonify({"error": "Missing required parameters"}), 400

    try:
        send_new_market_order(symbol_id, trade_side, volume)
        return jsonify({"message": "Order placed successfully"}), 200
    except Exception as e:
        logger.error(f"Error placing order: {str(e)}")
        return jsonify({"error": "Failed to place order"}), 500

if __name__ == "__main__":
    try:
        initialize_client()
        app.run(host='0.0.0.0', port=5000)
    finally:
        if reactor.running:
            reactor.stop()