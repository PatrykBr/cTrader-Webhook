# app.py

import os
from flask import Flask, request, jsonify
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.endpoints import EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthReq,
    ProtoOAApplicationAuthRes,
    ProtoOANewOrderReq,
    ProtoOAExecutionEvent,
    ProtoOASubscribeSpotsReq,
    ProtoOAUnsubscribeSpotsReq,
    ProtoOAVersionReq,
    ProtoOAGetAccountListByAccessTokenReq,
    ProtoOAAccountLogoutReq,
    ProtoOAAccountAuthReq,
    ProtoOAAssetListReq,
    ProtoOAAssetClassListReq,
    ProtoOASymbolCategoryListReq,
    ProtoOASymbolsListReq,
    ProtoOATraderReq,
    ProtoOAReconcileReq,
    ProtoOAGetTrendbarsReq,
    ProtoOAGetTickDataReq,
    ProtoOAClosePositionReq,
    ProtoOACancelOrderReq,
    ProtoOADealOffsetListReq,
    ProtoOAGetPositionUnrealizedPnLReq,
    ProtoOAOrderDetailsReq,
    ProtoOAOrderListByPositionIdReq,
    ProtoOAErrorRes
)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import (
    ProtoOAOrderType,
    ProtoOATradeSide,
    ProtoOAPayloadType
)
from twisted.internet import reactor
from twisted.internet.defer import Deferred
from threading import Thread
import logging
import json

app = Flask(__name__)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# cTrader API configuration
CLIENT_ID = os.environ.get('CTRADER_CLIENT_ID')
CLIENT_SECRET = os.environ.get('CTRADER_CLIENT_SECRET')
ACCOUNT_ID = os.environ.get('CTRADER_ACCOUNT_ID')
IS_DEMO = os.environ.get('CTRADER_IS_DEMO', 'True').lower() == 'true'

# Global variables
client = None
is_authenticated = False

def setup_ctrader_client():
    global client
    host = EndPoints.PROTOBUF_DEMO_HOST if IS_DEMO else EndPoints.PROTOBUF_LIVE_HOST
    client = Client(host, EndPoints.PROTOBUF_PORT, TcpProtocol)
    
    client.setConnectedCallback(connected)
    client.setDisconnectedCallback(disconnected)
    client.setMessageReceivedCallback(on_message_received)
    
    client.startService()
    
    # Run the Twisted reactor in a separate thread
    reactor_thread = Thread(target=reactor.run, args=(False,))
    reactor_thread.daemon = True
    reactor_thread.start()

def connected(client):
    logger.info("Connected to cTrader")
    request = ProtoOAApplicationAuthReq()
    request.clientId = CLIENT_ID
    request.clientSecret = CLIENT_SECRET
    client.send(request).addCallbacks(on_auth_response, on_error)

def disconnected(client, reason):
    logger.warning(f"Disconnected from cTrader: {reason}")
    global is_authenticated
    is_authenticated = False

def on_message_received(client, message):
    logger.debug(f"Message received: {Protobuf.extract(message)}")

def on_auth_response(message):
    global is_authenticated
    if message.payloadType == ProtoOAPayloadType.PROTO_OA_APPLICATION_AUTH_RES:
        logger.info("Authentication successful")
        is_authenticated = True
    else:
        logger.error(f"Unexpected response during authentication: {message}")

def on_error(failure):
    logger.error(f"Error: {failure}")

def place_order(symbol, action, volume):
    if not is_authenticated:
        raise Exception("Not authenticated with cTrader")
    
    request = ProtoOANewOrderReq()
    try:
        request.ctidTraderAccountId = int(ACCOUNT_ID)
        request.symbolId = int(symbol)  # Convert symbol to int if needed
        request.orderType = ProtoOAOrderType.MARKET
        request.tradeSide = ProtoOATradeSide.BUY if action.lower() == 'buy' else ProtoOATradeSide.SELL
        request.volume = int(volume * 100)  # Convert to cents
        request.comment = "Order from TradingView"
    except AttributeError as e:
        logger.error(f"AttributeError in place_order: {str(e)}")
        raise Exception(f"Error setting order attributes: {str(e)}")
    
    deferred = client.send(request)
    return deferred

@app.route('/', methods=['GET'])
def root():
    return jsonify({
        "message": "TradingView to cTrader Webhook Service",
        "status": "running",
        "authenticated": is_authenticated
    }), 200

@app.route('/webhook', methods=['POST'])
def webhook():
    if request.method == 'POST':
        try:
            # Try to parse JSON data regardless of Content-Type
            try:
                data = request.get_json(force=True)
            except Exception as json_error:
                # If JSON parsing fails, try to parse the data as a string
                data_str = request.data.decode('utf-8')
                # Assuming the data is in the format: symbol,action,quantity
                parts = data_str.split(',')
                if len(parts) != 3:
                    raise ValueError("Invalid data format")
                data = {
                    'symbol': parts[0],
                    'action': parts[1],
                    'quantity': float(parts[2])
                }
            
            logger.info(f"Received webhook data: {data}")
            
            symbol = data.get('symbol')
            action = data.get('action')  # 'buy' or 'sell'
            quantity = float(data.get('quantity', 0))
            
            if not all([symbol, action, quantity]):
                logger.warning("Missing required parameters in webhook data")
                return jsonify({"message": "Missing required parameters"}), 400
            
            order_deferred = place_order(symbol, action, quantity)
            
            def on_order_response(message):
                if message.payloadType == ProtoOAPayloadType.PROTO_OA_EXECUTION_EVENT:
                    logger.info(f"Order placed successfully: {message.orderId}")
                    return jsonify({"message": "Order placed successfully", "order_id": message.orderId}), 200
                else:
                    logger.warning(f"Unexpected response: {message}")
                    return jsonify({"message": "Unexpected response", "response": str(message)}), 400
            
            order_deferred.addCallbacks(on_order_response, on_error)
            
            return jsonify({"message": "Order processing"}), 202
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
            return jsonify({"message": "Failed to process order", "error": str(e)}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "healthy", "authenticated": is_authenticated}), 200

if __name__ == '__main__':
    setup_ctrader_client()
    port = int(os.environ.get('PORT', 10000))
    app.run(debug=False, host='0.0.0.0', port=port)
