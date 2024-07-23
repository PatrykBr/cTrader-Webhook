import os
import json
import unittest
from unittest.mock import patch
from flask import Flask
import base64

# Ensure the webhook_listener module can be found
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from webhook_listener import app, sendProtoOANewOrderReq

class WebhookListenerTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_index(self):
        result = self.app.get('/')
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.data, b"Webhook listener for TradingView to cTrader is running.")

    @patch('webhook_listener.sendProtoOANewOrderReq')
    def test_webhook(self, mock_send_order):
        # Set environment variables for testing
        os.environ['WEBHOOK_USER'] = 'test_user'
        os.environ['WEBHOOK_PASS'] = 'test_pass'
        
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + base64.b64encode(b'test_user:test_pass').decode('utf-8')
        }
        data = {
            "symbolId": 12345,
            "tradeSide": "BUY",
            "volume": 1
        }
        result = self.app.post('/webhook', data=json.dumps(data), headers=headers)
        self.assertEqual(result.status_code, 200)
        self.assertIn('Order placed', result.data.decode('utf-8'))
        mock_send_order.assert_called_once_with(12345, "MARKET", "BUY", 1)

    def test_webhook_auth_failure(self):
        headers = {
            'Content-Type': 'application/json',
            'Authorization': 'Basic ' + base64.b64encode(b'wrong_user:wrong_pass').decode('utf-8')
        }
        data = {
            "symbolId": 12345,
            "tradeSide": "BUY",
            "volume": 1
        }
        result = self.app.post('/webhook', data=json.dumps(data), headers=headers)
        self.assertEqual(result.status_code, 401)
        self.assertIn('Could not verify your access level for that URL', result.data.decode('utf-8'))

if __name__ == '__main__':
    unittest.main()
