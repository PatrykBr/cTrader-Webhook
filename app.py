import os
from flask import Flask, request, jsonify
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOANewOrderReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from twisted.internet import reactor
import logging
# Initialize Flask app
app = Flask(__name__)

# cTrader configuration
HOST = os.environ.get('CTRADER_HOST', 'demo.ctraderapi.com')
PORT = int(os.environ.get('CTRADER_PORT', '5035'))
APP_CLIENT_ID = os.environ.get('APP_CLIENT_ID')
APP_CLIENT_SECRET = os.environ.get('APP_CLIENT_SECRET')
ACCESS_TOKEN = os.environ.get('ACCESS_TOKEN')
ACCOUNT_ID = int(os.environ.get('ACCOUNT_ID'))

# Set up logging
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

# Initialize cTrader client
client = Client(HOST, PORT, TcpProtocol)

def on_connected(client):
    print("Connected to cTrader")
    authenticate_application()

def on_disconnected(client, reason):
    print(f"Disconnected from cTrader: {reason}")

def on_error(failure):
    print(f"Error: {failure}")

def authenticate_application():
    request = ProtoOAApplicationAuthReq(clientId=APP_CLIENT_ID, clientSecret=APP_CLIENT_SECRET)
    deferred = client.send(request)
    deferred.addCallback(on_app_auth_response)
    deferred.addErrback(on_error)

def on_app_auth_response(response):
    print("Application authenticated")
    authenticate_account()

def authenticate_account():
    request = ProtoOAAccountAuthReq(ctidTraderAccountId=ACCOUNT_ID, accessToken=ACCESS_TOKEN)
    deferred = client.send(request)
    deferred.addCallback(on_account_auth_response)
    deferred.addErrback(on_error)

def on_account_auth_response(response):
    print(f"Account {ACCOUNT_ID} authenticated")

def send_order(symbol_id, order_type, trade_side, volume, price=None):
    request = ProtoOANewOrderReq(
        ctidTraderAccountId=ACCOUNT_ID,
        symbolId=symbol_id,
        orderType=order_type,
        tradeSide=trade_side,
        volume=volume
    )
    if price and order_type in [ProtoOAOrderType.LIMIT, ProtoOAOrderType.STOP]:
        setattr(request, f"{order_type.name.lower()}Price", price)

    deferred = client.send(request)
    deferred.addCallback(on_order_response)
    deferred.addErrback(on_error)

def on_order_response(response):
    print(f"Order placed: {response}")

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    logger.debug(f"Received data: {data}")
    
    if not data:
        logger.error("No JSON data received")
        return jsonify({"status": "error", "message": "No JSON data received"}), 400
    
    try:
        symbol_id = int(data['symbol_id'])
        order_type = ProtoOAOrderType.Value(data.get('order_type', 'MARKET'))
        trade_side = ProtoOATradeSide.Value(data['trade_side'])
        volume = int(float(data['volume']) * 100)  # Convert to cTrader volume
        price = float(data.get('price', 0))
    except KeyError as e:
        logger.error(f"Missing required field: {str(e)}")
        return jsonify({"status": "error", "message": f"Missing required field: {str(e)}"}), 400
    except ValueError as e:
        logger.error(f"Invalid value: {str(e)}")
        return jsonify({"status": "error", "message": f"Invalid value: {str(e)}"}), 400
    
    try:
        send_order(symbol_id, order_type, trade_side, volume, price)
    except Exception as e:
        logger.error(f"Error sending order: {str(e)}")
        return jsonify({"status": "error", "message": f"Error sending order: {str(e)}"}), 500
    
    logger.info("Order received successfully")
    return jsonify({"status": "success", "message": "Order received"}), 200

if __name__ == "__main__":
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.startService()
    reactor.callInThread(app.run, host='0.0.0.0', port=5000)
    reactor.run()