import unittest
from unittest.mock import patch, MagicMock
from webhook_listener import app, sendProtoOANewOrderReq

class WebhookListenerTestCase(unittest.TestCase):

    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True
        self.headers = {
            "Authorization": "test_secret",
            "Content-Type": "application/json"
        }

    @patch('webhook_listener.sendProtoOANewOrderReq')
    def test_valid_webhook_request(self, mock_send_order):
        mock_send_order.return_value = None
        response = self.app.post('/webhook', json={
            "symbolId": 12345,
            "tradeSide": "BUY",
            "volume": 1
        }, headers=self.headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json, {"status": "Order placed"})

    def test_invalid_trade_side(self):
        response = self.app.post('/webhook', json={
            "symbolId": 12345,
            "tradeSide": "INVALID",
            "volume": 1
        }, headers=self.headers)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {"error": "Trade side must be 'BUY' or 'SELL'"})

    def test_missing_auth_header(self):
        response = self.app.post('/webhook', json={
            "symbolId": 12345,
            "tradeSide": "BUY",
            "volume": 1
        })
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json, {"message": "Unauthorized"})

    def test_invalid_json_format(self):
        response = self.app.post('/webhook', data="invalid_json", headers={"Authorization": "test_secret", "Content-Type": "application/json"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json, {"error": "Invalid data"})

if __name__ == '__main__':
    with patch.dict('os.environ', {'WEBHOOK_SECRET': 'test_secret'}):
        unittest.main()
