import os
import logging
from flask import Flask, request, jsonify
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAApplicationAuthRes, ProtoOAAccountAuthReq, ProtoOAAccountAuthRes, ProtoOANewOrderReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor
import webbrowser

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Environment variables
HOST_TYPE = os.getenv("HOST_TYPE")
APP_CLIENT_ID = os.getenv("APP_CLIENT_ID")
APP_CLIENT_SECRET = os.getenv("APP_CLIENT_SECRET")
ACCESS_TOKEN = os.getenv("ACCESS_TOKEN")
ACCOUNT_ID = int(os.getenv("ACCOUNT_ID"))

if not all([HOST_TYPE, APP_CLIENT_ID, APP_CLIENT_SECRET, ACCESS_TOKEN, ACCOUNT_ID]):
    raise ValueError("All required environment variables are not set.")

client = Client(EndPoints.PROTOBUF_LIVE_HOST if HOST_TYPE == "live" else EndPoints.PROTOBUF_DEMO_HOST, EndPoints.PROTOBUF_PORT, TcpProtocol)

def connected(client):
    logger.info("\nConnected")
    request = ProtoOAApplicationAuthReq()
    request.clientId = APP_CLIENT_ID
    request.clientSecret = APP_CLIENT_SECRET
    deferred = client.send(request)
    deferred.addErrback(onError)

def disconnected(client, reason):
    logger.info(f"\nDisconnected: {reason}")

def onMessageReceived(client, message):
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logger.info("API Application authorized\n")
        sendProtoOAAccountAuthReq()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        protoOAAccountAuthRes = Protobuf.extract(message)
        logger.info(f"Account {protoOAAccountAuthRes.ctidTraderAccountId} has been authorized\n")

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
        deferred.addErrback(onError)
    except Exception as e:
        logger.error(f"Error while sending new order request: {e}")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    if not data:
        return jsonify({"error": "Invalid data"}), 400

    try:
        symbolId = data["symbolId"]
        tradeSide = data["tradeSide"].upper()
        volume = data["volume"]

        if tradeSide not in ["BUY", "SELL"]:
            return jsonify({"error": "Trade side must be 'BUY' or 'SELL'"}), 400

        sendProtoOANewOrderReq(symbolId, "MARKET", tradeSide, volume)
        return jsonify({"status": "Order placed"}), 200

    except KeyError as ke:
        logger.error(f"Missing key in JSON data: {ke}")
        return jsonify({"error": "Invalid data format"}), 400
    except Exception as e:
        logger.error(f"Unexpected error: {e}")
        return jsonify({"error": "Internal server error"}), 500

if __name__ == '__main__':
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(onMessageReceived)
    client.startService()
    reactor.callInThread(app.run, host='0.0.0.0', port=5000)
    reactor.run()
