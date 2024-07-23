#!/usr/bin/env python

from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiCommonMessages_pb2 import *
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import *
from twisted.internet import reactor
from flask import Flask, request, jsonify
import webbrowser
import datetime
import calendar
import threading
import logging
import os

app = Flask(__name__)

# Configure logging
logging.basicConfig(level=logging.DEBUG)

currentAccountId = None
hostType = os.environ.get("HOST_TYPE", "demo").lower()
appClientId = os.environ.get("APP_CLIENT_ID")
appClientSecret = os.environ.get("APP_CLIENT_SECRET")
accessToken = os.environ.get("ACCESS_TOKEN")
appRedirectUri = os.environ.get("APP_REDIRECT_URI")

def initialize_client():
    global client
    client = Client(
        EndPoints.PROTOBUF_LIVE_HOST if hostType == "live" else EndPoints.PROTOBUF_DEMO_HOST,
        EndPoints.PROTOBUF_PORT,
        TcpProtocol
    )
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(onMessageReceived)
    client.startService()
    reactor.run(installSignalHandlers=0)

def start_client_in_thread():
    client_thread = threading.Thread(target=initialize_client)
    client_thread.daemon = True
    client_thread.start()

def connected(client):  # Callback for client connection
    logging.info("Connected")
    request = ProtoOAApplicationAuthReq()
    request.clientId = appClientId
    request.clientSecret = appClientSecret
    deferred = client.send(request)
    deferred.addErrback(onError)

def disconnected(client, reason):  # Callback for client disconnection
    logging.info("Disconnected: %s", reason)

def onMessageReceived(client, message):  # Callback for receiving all messages
    global currentAccountId
    if message.payloadType in [ProtoOASubscribeSpotsRes().payloadType, ProtoOAAccountLogoutRes().payloadType, ProtoHeartbeatEvent().payloadType]:
        return
    elif message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        logging.info("API Application authorized")
        if currentAccountId is not None:
            sendProtoOAAccountAuthReq()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        protoOAAccountAuthRes = Protobuf.extract(message)
        logging.info(f"Account {protoOAAccountAuthRes.ctidTraderAccountId} has been authorized")
    else:
        logging.info("Message received: %s", Protobuf.extract(message))

def onError(failure):  # Callback for errors
    logging.error("Message Error: %s", failure)

def sendProtoOAAccountAuthReq(clientMsgId=None):
    request = ProtoOAAccountAuthReq()
    request.ctidTraderAccountId = currentAccountId
    request.accessToken = accessToken
    deferred = client.send(request, clientMsgId=clientMsgId)
    deferred.addErrback(onError)

def sendNewMarketOrder(symbolId, tradeSide, volume, clientMsgId=None):
    request = ProtoOANewOrderReq()
    request.ctidTraderAccountId = currentAccountId
    request.symbolId = int(symbolId)
    request.orderType = ProtoOAOrderType.MARKET
    request.tradeSide = ProtoOATradeSide.Value(tradeSide.upper())
    request.volume = int(volume) * 100
    deferred = client.send(request, clientMsgId=clientMsgId)
    deferred.addErrback(onError)

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logging.debug("Webhook received data: %s", data)
        symbolId = data['symbolId']
        tradeSide = data['tradeSide']
        volume = data['volume']
        sendNewMarketOrder(symbolId, tradeSide, volume)
        return jsonify({"status": "order placed"}), 200
    except KeyError as e:
        logging.error("Missing key in JSON data: %s", e)
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error processing webhook: %s", e)
        return jsonify({"error": str(e)}), 400

def authenticate_and_start():
    global accessToken
    if not accessToken:
        if not appRedirectUri:
            raise ValueError("APP_REDIRECT_URI must be set in the environment if no access token is available.")
        auth = Auth(appClientId, appClientSecret, appRedirectUri)
        authUri = auth.getAuthUri()
        print(f"Please continue the authentication on your browser:\n {authUri}")
        webbrowser.open_new(authUri)
        authCode = input("Auth Code: ")
        token = auth.getToken(authCode)
        if "accessToken" not in token:
            raise KeyError(token)
        accessToken = token["accessToken"]
    start_client_in_thread()

def main():
    authenticate_and_start()
    app.run(host="0.0.0.0", port=5000, debug=True)

if __name__ == "__main__":
    main()
