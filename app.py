import os
from flask import Flask, request, jsonify
from ctrader_open_api import Client, Protobuf, TcpProtocol, Auth, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import *
from twisted.internet import reactor

# Initialize Flask app
app = Flask(__name__)

# cTrader API configuration
HOST = os.environ.get('CTRADER_HOST', 'demo.ctraderapi.com')
PORT = int(os.environ.get('CTRADER_PORT', '5035'))
APP_CLIENT_ID = os.environ.get('APP_CLIENT_ID')
APP_CLIENT_SECRET = os.environ.get('APP_CLIENT_SECRET')
ACCESS_TOKEN = os.environ.get('ACCESS_TOKEN')
ACCOUNT_ID = int(os.environ.get('ACCOUNT_ID'))

# Initialize cTrader client
client = Client(HOST, PORT, TcpProtocol)

def on_connected(client):
    print("Connected to cTrader API")
    send_application_auth_request()

def on_disconnected(client, reason):
    print(f"Disconnected from cTrader API: {reason}")

def on_message_received(client, message):
    if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
        print("Application authenticated")
        send_account_auth_request()
    elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
        print(f"Account {ACCOUNT_ID} authenticated")
    else:
        print("Message received:", Protobuf.extract(message))

def on_error(failure):
    print("Error:", failure)

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

def send_market_order(symbol_id, volume, trade_side):
    request = ProtoOANewOrderReq()
    request.ctidTraderAccountId = ACCOUNT_ID
    request.symbolId = symbol_id
    request.orderType = ProtoOAOrderType.MARKET
    request.tradeSide = trade_side
    request.volume = volume * 100  # Volume is in cents
    client.send(request).addErrback(on_error)

@app.route('/webhook', methods=['POST'])
def webhook():
    data = request.json
    
    if 'action' not in data or 'symbol' not in data or 'volume' not in data:
        return jsonify({"error": "Missing required fields"}), 400

    action = data['action'].upper()
    symbol_id = int(data['symbol'])
    volume = float(data['volume'])

    if action == 'BUY':
        trade_side = ProtoOATradeSide.BUY
    elif action == 'SELL':
        trade_side = ProtoOATradeSide.SELL
    else:
        return jsonify({"error": "Invalid action"}), 400

    send_market_order(symbol_id, volume, trade_side)
    return jsonify({"message": "Order sent successfully"}), 200

if __name__ == "__main__":
    # Set up cTrader client callbacks
    client.setConnectedCallback(on_connected)
    client.setDisconnectedCallback(on_disconnected)
    client.setMessageReceivedCallback(on_message_received)

    # Start cTrader client service
    client.startService()

    # Run Flask app
    app.run(port=5000)

    # Run Twisted reactor
    reactor.run()