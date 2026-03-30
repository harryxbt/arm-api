import stripe
from app.config import settings

stripe.api_key = settings.stripe_secret_key


def create_checkout_session(customer_id: str, price_id: str, success_url: str, cancel_url: str) -> str:
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return session.url


def create_customer(email: str) -> str:
    customer = stripe.Customer.create(email=email)
    return customer.id


def create_portal_session(customer_id: str, return_url: str) -> str:
    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=return_url,
    )
    return session.url


def construct_webhook_event(payload: bytes, sig_header: str) -> stripe.Event:
    return stripe.Webhook.construct_event(payload, sig_header, settings.stripe_webhook_secret)


def get_credits_from_invoice(invoice) -> int:
    """Extract credit amount from the Price metadata on the invoice line item."""
    for line in invoice.lines.data:
        if line.price and line.price.metadata.get("credits"):
            return int(line.price.metadata["credits"])
    return 0
