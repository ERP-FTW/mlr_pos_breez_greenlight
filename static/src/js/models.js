/** @odoo-module */
import { register_payment_method } from "@point_of_sale/app/store/pos_store";
import { PaymentBreezPayment } from '@mlr_pos_breez/js/payment_cryptopayment';

    register_payment_method('breez', PaymentBreezPayment);

