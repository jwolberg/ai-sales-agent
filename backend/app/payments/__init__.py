"""Hosted-payment slice (BUILD_PLAN_PAYMENTS).

Stripe payment links / invoices + Twilio SMS delivery. Hosted checkout only — our server never
touches card data (PCI stays SAQ-A). Feature-flagged off until a Stripe key + approved prices land.
"""
