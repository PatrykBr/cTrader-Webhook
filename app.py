import os
from flask import Flask, request, jsonify
from ctrader_open_api import Client, TcpProtocol
from ctrader_open_api.messages.OpenApiMessages_pb2 import ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOANewOrderReq
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAOrderType, ProtoOATradeSide
from dotenv import load_dotenv
from twisted.internet import reactor

# Load environment variables
load_dotenv()

# Initialize Flask app
app = Flask(__name__)

# cTrader configuration
HOST = os.getenv('CTRADER_HOST', 'demo.ctraderapi.com')
PORT = int(os.getenv('CTRADER_PORT', '5035'))
APP_CLIENT_ID = os.getenv('APP_CLIENT_ID')
APP_CLIENT_SECRET = os.getenv('APP_CLIENT_SECRET')
ACCESS_TOKEN = os.getenv('ACCESS_TOKEN')
ACCOUNT_ID = int(os.getenv('ACCOUNT_ID'))

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
    
    symbol_id = int(data.get('symbol_id'))
    order_type = ProtoOAOrderType.Value(data.get('order_type', 'MARKET'))
    trade_side = ProtoOATradeSide.Value(data.get('trade_side'))
    volume = int(float(data.get('volume')) * 100)  # Convert to cTrader volume
    price = float(data.get('price', 0))

    send_order(symbol_id, order_type, trade_side, volume, price)

    return jsonify({"status": "success", "message": "Order received"}), 200

if __name__ == "__main__":
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.startService()
    reactor.callInThread(app.run, host='0.0.0.0', port=5000)
    reactor.run()