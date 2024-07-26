import os
import logging
import json
from flask import Flask, request, jsonify
from functools import wraps
from ctrader_open_api import Client, Protobuf, TcpProtocol, EndPoints
from ctrader_open_api.messages.OpenApiMessages_pb2 import (
    ProtoOAApplicationAuthRes, ProtoOAAccountAuthRes, 
    ProtoOAApplicationAuthReq, ProtoOAAccountAuthReq, ProtoOAReconcileReq, 
    ProtoOANewOrderReq, ProtoOAClosePositionReq)
from ctrader_open_api.messages.OpenApiModelMessages_pb2 import ProtoOAPositionStatus, ProtoOATradeSide, ProtoOAOrderType
from twisted.internet import reactor, task
from twisted.web.wsgi import WSGIResource
from twisted.web.server import Site
from twisted.internet import endpoints
import argparse

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class Config:
    HOST_TYPE = os.getenv("HOST_TYPE", "demo").lower()
    APP_CLIENT_ID = os.getenv("APP_CLIENT_ID", "test_client_id")
    APP_CLIENT_SECRET = os.getenv("APP_CLIENT_SECRET", "test_client_secret")
    ACCESS_TOKEN = os.getenv("ACCESS_TOKEN", "test_access_token")
    ACCOUNT_ID = int(os.getenv("ACCOUNT_ID", "0"))
    AUTH_TOKEN = os.getenv("AUTH_TOKEN", "your_secure_token_here")
    PORT = int(os.environ.get("PORT", 5000))

app = Flask(__name__)

class CTradingAPI:
    def __init__(self):
        self.is_connected = False
        self.client = Client(
            EndPoints.PROTOBUF_LIVE_HOST if Config.HOST_TYPE == "live" else EndPoints.PROTOBUF_DEMO_HOST,
            EndPoints.PROTOBUF_PORT,
            TcpProtocol
        )
        self.setup_client_callbacks()

    def setup_client_callbacks(self):
        self.client.setConnectedCallback(self.connected)
        self.client.setDisconnectedCallback(self.disconnected)
        self.client.setMessageReceivedCallback(self.on_message_received)

    def connected(self, client):
        self.is_connected = True
        logger.info("Connected to cTrader Open API")
        self.send_application_auth_request()

    def disconnected(self, client, reason):
        self.is_connected = False
        logger.warning(f"Disconnected from cTrader Open API: {reason}")
        reactor.callLater(5, self.client.startService)

    def on_message_received(self, client, message):
        if message.payloadType == ProtoOAApplicationAuthRes().payloadType:
            logger.info("API Application authorized")
            self.send_account_auth_request()
        elif message.payloadType == ProtoOAAccountAuthRes().payloadType:
            protoOAAccountAuthRes = Protobuf.extract(message)
            logger.info(f"Account {protoOAAccountAuthRes.ctidTraderAccountId} has been authorized")

    def on_error(self, failure):
        logger.error(f"Error occurred: {failure.getErrorMessage()}")
        logger.error(f"Error details: {failure.getTraceback()}")
        return None

    def send_application_auth_request(self):
        try:
            request = ProtoOAApplicationAuthReq(
                clientId=Config.APP_CLIENT_ID,
                clientSecret=Config.APP_CLIENT_SECRET
            )
            self.client.send(request).addErrback(self.on_error)
        except Exception as e:
            logger.error(f"Error in send_application_auth_request: {str(e)}")

    def send_account_auth_request(self):
        try:
            request = ProtoOAAccountAuthReq(
                ctidTraderAccountId=Config.ACCOUNT_ID,
                accessToken=Config.ACCESS_TOKEN
            )
            self.client.send(request).addErrback(self.on_error)
        except Exception as e:
            logger.error(f"Error in send_account_auth_request: {str(e)}")

    def get_existing_positions(self, symbol_id):
        try:
            request = ProtoOAReconcileReq(ctidTraderAccountId=Config.ACCOUNT_ID)
            deferred = self.client.send(request)
            deferred.addCallback(lambda response: self.on_reconcile_received(response, symbol_id))
            deferred.addErrback(self.on_error)
            return deferred
        except Exception as e:
            logger.error(f"Error in get_existing_positions: {str(e)}")
            return None

    def on_reconcile_received(self, response, symbol_id):
        try:
            reconcile_data = Protobuf.extract(response)
            positions = [
                position for position in reconcile_data.position
                if hasattr(position, 'tradeData') and 
                position.tradeData.symbolId == symbol_id and 
                position.positionStatus == ProtoOAPositionStatus.POSITION_STATUS_OPEN
            ]
            logger.info(f"Found {len(positions)} open positions for symbol {symbol_id}")
            return positions
        except Exception as e:
            logger.error(f"Error in on_reconcile_received: {str(e)}")
            return []

    def send_new_order_request(self, symbol_id, order_type, trade_side, volume):
        try:
            def place_order(existing_positions):
                if existing_positions is None:
                    logger.error("Failed to retrieve existing positions")
                    return False

                net_volume = volume
                same_side_volume = 0
                opposite_side = ProtoOATradeSide.SELL if trade_side == "BUY" else ProtoOATradeSide.BUY
                
                for position in existing_positions:
                    if position.tradeData.tradeSide == ProtoOATradeSide.Value(trade_side):
                        same_side_volume += position.tradeData.volume / 100
                        self.send_close_position_request(position.positionId, position.tradeData.volume / 100)
                    elif position.tradeData.tradeSide == opposite_side:
                        position_volume = position.tradeData.volume / 100
                        if position_volume <= net_volume:
                            self.send_close_position_request(position.positionId, position_volume)
                            net_volume -= position_volume
                        else:
                            self.send_close_position_request(position.positionId, net_volume)
                            net_volume = 0
                            break

                total_volume = net_volume + same_side_volume
                if total_volume > 0:
                    request = ProtoOANewOrderReq(
                        ctidTraderAccountId=Config.ACCOUNT_ID,
                        symbolId=int(symbol_id),
                        orderType=ProtoOAOrderType.Value(order_type.upper()),
                        tradeSide=ProtoOATradeSide.Value(trade_side.upper()),
                        volume=int(total_volume * 100)
                    )
                    deferred = self.client.send(request)
                    deferred.addCallback(self.on_order_placed)
                    deferred.addErrback(self.on_error)
                    logger.info(f"Placing new order: {trade_side} {total_volume} lots")
                else:
                    logger.info("No new order placed after netting existing positions")
                
                return True

            deferred = self.get_existing_positions(int(symbol_id))
            deferred.addCallback(place_order)
            deferred.addErrback(self.on_error)
            return True
        except Exception as e:
            logger.error(f"Error in send_new_order_request: {str(e)}")
            return False

    def send_close_position_request(self, position_id, volume):
        try:
            request = ProtoOAClosePositionReq(
                ctidTraderAccountId=Config.ACCOUNT_ID,
                positionId=position_id,
                volume=int(volume * 100)
            )
            deferred = self.client.send(request)
            deferred.addCallback(self.on_position_closed)
            deferred.addErrback(self.on_error)
            logger.info(f"Closing position {position_id} with volume {volume}")
        except Exception as e:
            logger.error(f"Error in send_close_position_request: {str(e)}")

    def on_position_closed(self, response):
        try:
            logger.info(f"Position closed successfully: {response}")
        except Exception as e:
            logger.error(f"Error in on_position_closed: {str(e)}")

    def on_order_placed(self, response):
        try:
            logger.info(f"Order placed successfully: {response}")
        except Exception as e:
            logger.error(f"Error in on_order_placed: {str(e)}")

ctrading_api = CTradingAPI()

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        if not token or token != Config.AUTH_TOKEN:
            logger.warning("Unauthorized access attempt")
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated

@app.route('/health')
def health_check():
    if ctrading_api.is_connected:
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

        reactor.callLater(2, process_order, symbol_id, trade_side, volume)

        return jsonify({"status": "Order processing initiated"}), 202

    except json.JSONDecodeError:
        logger.error("Invalid JSON data received")
        return jsonify({"error": "Invalid JSON data"}), 400
    except Exception as e:
        logger.error(f"Unexpected error in webhook handler: {str(e)}")
        return jsonify({"error": "Internal server error"}), 500

def process_order(symbol_id, trade_side, volume):
    try:
        logger.info(f"Processing order: Symbol ID: {symbol_id}, Trade Side: {trade_side}, Volume: {volume}")
        success = ctrading_api.send_new_order_request(symbol_id, "MARKET", trade_side, volume)
        if not success:
            logger.error("Failed to place order")
        else:
            logger.info("Order processing completed successfully")
    except Exception as e:
        logger.error(f"Error in process_order: {str(e)}")

def run_server(port, debug=False):
    try:
        if debug:
            app.run(host='0.0.0.0', port=port, debug=True)
        else:
            resource = WSGIResource(reactor, reactor.getThreadPool(), app)
            site = Site(resource)
            endpoint = endpoints.TCP4ServerEndpoint(reactor, port, interface='0.0.0.0')
            endpoint.listen(site)
            logger.info(f"Server running on port {port}")
    except Exception as e:
        logger.error(f"Error in run_server: {str(e)}")

def main():
    try:
        parser = argparse.ArgumentParser(description='Run the TradingView to cTrader webhook server')
        parser.add_argument('--debug', action='store_true', help='Run in debug mode')
        parser.add_argument('--test', action='store_true', help='Run in test mode (no cTrader connection)')
        parser.add_argument('--port', type=int, default=Config.PORT, help='Port to run the server on')
        args = parser.parse_args()

        if args.test:
            logger.info("Running in test mode (no cTrader connection)")
            run_server(args.port, args.debug)
        else:
            run_server(args.port, args.debug)
            if not args.debug:
                ctrading_api.client.startService()

                # Add a periodic check to ensure connection
                l = task.LoopingCall(lambda: ctrading_api.client.startService() if not ctrading_api.is_connected else None)
                l.start(60.0)  # Check every 60 seconds

                reactor.run()
    except Exception as e:
        logger.error(f"Error in main: {str(e)}")

if __name__ == '__main__':
    main()