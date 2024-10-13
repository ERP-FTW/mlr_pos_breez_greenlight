# coding: utf-8
# Part of Odoo. See LICENSE file for full copyright and licensing details.
import json
import logging
import breez_sdk
import requests

from odoo import fields, models, api, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)
TIMEOUT = 10

class PosPaymentMethod(models.Model):
    _inherit = 'pos.payment.method'

    def _get_payment_terminal_selection(self):
        return super()._get_payment_terminal_selection() + [('breez', 'Breez')]

    # cryptopay server fields
    breez_payment_type = fields.Selection([('lightning','BTC-Lightning'), ('onchain','BTC-onchain')], string='Breez Payment Type')
    breez_invite_code = fields.Char(string='Breez Invite Code')
    breez_mnemonic = fields.Char(string='Breez Mneomonic')

    def call_breez_api(self,payload,api,method,jwt=0):
        try:
            _logger.info(f"Called Breez call_breez_api. Passed args are {payload}")
            request_url = f"{self.server_url}{api}"
            headers = {"Authorization": "Token %s" % (self.api_key), "Content-Type": "application/json"}
            _logger.info(f"value of server_url is {request_url} and method is {method} and header is {headers}")
            if method == "GET":
                _logger.info(f"value of server_url is {request_url} and method is {method} and header is {headers}")
                apiRes=requests.request(method="GET", url=request_url, headers=headers)
                _logger.info(f"value of server_url is {request_url} and method is {method} and header is {headers}")
            elif method == "POST":
                apiRes=requests.request(method="POST",url=request_url, data=json.dumps(payload), headers=headers)
            _logger.info(f"Completed Breez call_breez_api, status {apiRes.status_code}. Passing back {apiRes}")
            return apiRes
        except Exception as e:
            _logger.info("API call failure: %s", e.args)
            raise UserError(_("API call failure: %s", e.args))

    def _test_connection(self):
        _logger.info("called Breez check connection")
        if self.use_payment_terminal == 'breez':
            return self.call_breez_api({},"/api/v1/health","GET")
        else:
            return super()._test_connection()
    def action_get_conversion_rate(self): #obtains conversion rate from BTCpay server
        try:
            server_url = self.server_url + "/api/v1/stores/" + self.breez_invite_code + "/rates"
            headers = {"Authorization": "Token %s" % (self.api_key)}
            response = requests.request(method="GET", url=server_url, headers=headers)
            response_json = response.json()
            _logger.info(f"Called Breez action_get_conversion_rate1. Response is {response_json}")
            #response = self.call_breez_api({}, server_url, 'GET')
            #response_json = response.json()
            #_logger.info(f"Called Breez action_get_conversion_rate2. Response is {response_json}")
            result = response_json[0]['rate'] if response.status_code == 200 else None
            return result
        except Exception as e:
            raise UserError(_("Get Conversion Rate: %s", e.args))

    def get_amount_sats(self, pos_payment_obj): #obtains amount of satoshis to invoice by calling action_get_conversion_rate and and doing the math, returns dict of both values
        try:
            breez_conversion_rate = self.action_get_conversion_rate()
            amount_sats = round((float(pos_payment_obj.get('amount')) / float(breez_conversion_rate)) * 100000000, 1) #conversion to satoshis and rounding to one decimal
            invoiced_info = {'conversion_rate': breez_conversion_rate,
                             'invoiced_sat_amount': amount_sats}
            return invoiced_info #return dictionary with results of both functions
        except Exception as e:
            raise UserError(_("Get Millisat amount: %s", e.args))

    # "description": self.breez_company_name + " " + args.get('order_name'),
    # desciption for customer - company name and order name
    # str(self.breez_company_name) + " " + str(args.get('order_name'))

    def breez_create_crypto_invoice_payment_link(self, args):
        try:
            _logger.info(f"Called Breez breez_create_crypto_invoice_payment_link. Passed args are {args}")
            invoiced_info = self.get_amount_sats(args)
            amount_btc = invoiced_info['invoiced_sat_amount'] /100000000  # converts sats to millisats as required by breezserver
            lightning_expiration_minutes = self.breez_expiration_minutes * 60
            payload = {
                "metadata": {
                    "orderId":str(self.breez_company_name) + " Order: " + str(args.get('order_id'))},
                "checkout": {
                    "speedPolicy": str(self.breez_speed_policy),
                    "expirationMinutes": lightning_expiration_minutes,},
                 "amount": amount_btc,
                "currency": "BTC",}
            server_url = "/api/v1/stores/" + self.breez_invite_code + "/invoices/"
            create_invoice_api = self.call_breez_api(payload, server_url, 'POST')
            if create_invoice_api.status_code != 200:
                return {"code": create_invoice_api.status_code}
            create_invoice_json = create_invoice_api.json()
            inv_json = {
                "code": 0,
                "invoice_id": create_invoice_json.get('id'),
                "invoice": create_invoice_json.get('checkoutLink'),
                "cryptopay_payment_link": create_invoice_json.get('checkoutLink'),
                "cryptopay_payment_type": 'BTC',
                "crypto_amt": invoiced_info['invoiced_sat_amount'],}
            _logger.info(f"Completed Breez breez_create_crypto_invoice_payment_link. Passing back {inv_json}")
            return inv_json
        except Exception as e:
            message = "An exception occurred with Breez breez_create_crypto_invoice_payment_link: " + str(e)
            _logger.info(message)
            return {"code": message}



    def breez_create_crypto_invoice_direct_invoice(self, args):
        try:
            _logger.info(f"Called Breez breez_create_crypto_invoice_direct_invoice. Passed args are {args}")
            invoiced_info = self.get_amount_sats(args)
            amount_millisats = invoiced_info['invoiced_sat_amount'] * 1000  # converts sats to millisats as required by breezserver
            lightning_expiration_minutes = self.breez_expiration_minutes * 60  # conversion of expiration time from min to sec for submission to breez server
            headers = {"Authorization": "Token %s" % (self.api_key), "Content-Type": "application/json"}
            if self.breez_selected_crypto == 'lightning':
                server_url = self.server_url + "/api/v1/stores/" + self.breez_invite_code + "/lightning/BTC/invoices"
                payload = {
                    "amount": amount_millisats,
                    "description": str(self.breez_company_name) + " Order: " + str(args.get('order_id')),
                    "expiry": lightning_expiration_minutes,}
            #create_invoice_api = self.call_breez_api(payload, server_url, 'POST')
            create_invoice_api = requests.request(method="POST", url=server_url, data=json.dumps(payload), headers=headers)
            _logger.info(create_invoice_api.json())
            if create_invoice_api.status_code != 200:
                return {"code": create_invoice_api.status_code}
            create_invoice_json = create_invoice_api.json()
            if self.breez_selected_crypto == 'lightning':
                invoice = create_invoice_json.get('BOLT11')
                cryptopay_payment_link = 'lightning:' + create_invoice_json.get('BOLT11')
            inv_json = {
                "code": 0,
                "invoice_id": create_invoice_json.get('id'),
                "invoice": invoice,
                "cryptopay_payment_link": cryptopay_payment_link,
                "cryptopay_payment_type": 'BTC-' + self.breez_selected_crypto,
                "crypto_amt": float(create_invoice_json.get('amount'))/1000, }
            _logger.info(f"Completed Breez breez_create_crypto_invoice_direct_invoice. Passing back {inv_json}")
            return inv_json
        except Exception as e:
            message = "An exception occurred with Breez breez_create_crypto_invoice_direct_invoice: " + str(e)
            _logger.info(message)
            return {"code":message}

    @api.model
    def breez_create_crypto_invoice(self, args):
        try:
            _logger.info(f"Called Breez breez_create_crypto_invoice. Passed args are {args}")
            cryptopay_pm = self.env['pos.payment.method'].search([('id', '=', args['pm_id'])], limit=1)
            if cryptopay_pm.use_payment_terminal != 'breez':
                return super().breez_create_crypto_invoice(args)
            if cryptopay_pm.crypto_minimum_amount > args['amount']:
                return {"code": "Below minimum amount of method: " + str(self.env.ref('base.main_company').currency_id.symbol) + str(cryptopay_pm.crypto_minimum_amount)}
            if cryptopay_pm.crypto_maximum_amount < args['amount']:
                return {"code": "Above maximum amount of method: " + str(self.env.ref('base.main_company').currency_id.symbol) + str(cryptopay_pm.crypto_maximum_amount)}
            breez_payment_flow = cryptopay_pm['breez_payment_flow']
            if breez_payment_flow == 'direct invoice':
                create_invoice_api = cryptopay_pm.breez_create_crypto_invoice_direct_invoice(args)
                return create_invoice_api
            else:
                create_invoice_api = cryptopay_pm.breez_create_crypto_invoice_payment_link(args)
                return create_invoice_api
        except Exception as e:
            message = "An exception occurred with Breez breez_create_crypto_invoice: " + str(e)
            _logger.info(message)
            return {"code": message}

    def breez_check_payment_status_payment_link(self, args):
        try:
            _logger.info(f"Called Breez breez_check_payment_status_payment_link. Passed args are {args}")
            cryptopay_pm = self.env['pos.payment.method'].search([('id', '=', args['pm_id'])], limit=1)
            if cryptopay_pm.use_payment_terminal != 'breez':
                return super().breez_check_payment_status(args)
            server_url = "/api/v1/stores/" + self.breez_invite_code + "/invoices/" + args['invoice_id']
            invoice_status_api = cryptopay_pm.call_breez_api({}, server_url, 'GET')
            if invoice_status_api.status_code != 200:
                invoice_status_api = {'status': 'inaccessible'}
            _logger.info(f"Completed Breez breez_check_payment_status. Passing back {invoice_status_api.json()}")
            return invoice_status_api.json()
        except Exception as e:
            message = "An exception occurred with Breez breez_check_payment_status_payment_link: " + str(e)
            _logger.info(message)
            return {"code": message}

    def breez_check_payment_status_direct_invoice(self, args):
        try:
            _logger.info(f"Called Breez breez_check_payment_status_direct_invoice. Passed args are {args}")
            cryptopay_pm = self.env['pos.payment.method'].search([('id', '=', args['pm_id'])], limit=1)
            if cryptopay_pm.use_payment_terminal != 'breez':
                return super().breez_check_payment_status(args)
            server_url = "/api/v1/stores/" + self.breez_invite_code + "/lightning/BTC/invoices/" + args['invoice_id']
            invoice_status_api = cryptopay_pm.call_breez_api({}, server_url, 'GET')
            if invoice_status_api.status_code != 200:
                return false
            _logger.info(f"Completed Breez breez_check_payment_status_direct_invoice. Passing back {invoice_status_api.json()}")
            return invoice_status_api.json()
        except Exception as e:
            message = "An exception occurred with Breez breez_check_payment_status_direct_invoice: " + str(e)
            _logger.info(message)
            return {"code": message}

    @api.model 
    def breez_check_payment_status(self, args):
        try:
            _logger.info(f"Called Breez breez_check_payment_status. Passed args are {args}")
            cryptopay_pm = self.env['pos.payment.method'].search([('id', '=', args['pm_id'])], limit=1)
            if cryptopay_pm.use_payment_terminal != 'breez':
                return super().breez_check_payment_status(args)
            if cryptopay_pm.breez_payment_flow == 'direct invoice':
                check_payment_api = cryptopay_pm.breez_check_payment_status_direct_invoice(args)
                return check_payment_api
            else:
                check_payment_api = cryptopay_pm.breez_check_payment_status_payment_link(args)
                return check_payment_api
        except Exception as e:
            message = "An exception occurred with Breez breez_check_payment_status: " + str(e)
            _logger.info(message)
            return {"code": message}


