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
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        protoOAAccountAuthRes = Protobuf.extract(message)
        currentAccountId = protoOAAccountAuthRes.ctidTraderAccountId
        logging.info(f"Account {currentAccountId} has been authorized")
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

def sendNewMarketOrder(symbol, action, quantity, clientMsgId=None):
    if currentAccountId is None:
        raise ValueError("Account ID is not set. Please set the account ID first.")
    request = ProtoOANewOrderReq()
    request.ctidTraderAccountId = currentAccountId
    symbolId = get_symbol_id(symbol)  # Implement this function to map symbols to symbolId
    request.symbolId = symbolId
    request.orderType = ProtoOAOrderType.MARKET
    request.tradeSide = ProtoOATradeSide.BUY if action.lower() == "buy" else ProtoOATradeSide.SELL
    request.volume = int(float(quantity) * 100000)  # Adjust based on the lot size of the asset
    deferred = client.send(request, clientMsgId=clientMsgId)
    deferred.addErrback(onError)

def get_symbol_id(symbol):
    # Implement this function to map symbols to symbolId
    symbol_map = {
        "BTCUSD": 1,  # Example mapping
        # Add more symbol mappings here
    }
    return symbol_map.get(symbol, 0)  # Return 0 or appropriate default if symbol not found

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.json
        logging.debug("Webhook received data: %s", data)
        symbol = data['symbol']
        action = data['action']
        quantity = data['quantity']
        sendNewMarketOrder(symbol, action, quantity)
        return jsonify({"status": "order placed"}), 200
    except KeyError as e:
        logging.error("Missing key in JSON data: %s", e)
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error processing webhook: %s", e)
        return jsonify({"error": str(e)}), 400

@app.route('/set_account', methods=['POST'])
def set_account():
    global currentAccountId
    try:
        data = request.json
        currentAccountId = data['accountId']
        sendProtoOAAccountAuthReq()
        return jsonify({"status": f"Account {currentAccountId} set and authenticated"}), 200
    except KeyError as e:
        logging.error("Missing key in JSON data: %s", e)
        return jsonify({"error": f"Missing key: {str(e)}"}), 400
    except Exception as e:
        logging.error("Error setting account: %s", e)
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
