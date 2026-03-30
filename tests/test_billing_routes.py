# tests/test_billing_routes.py
import pytest
from unittest.mock import patch, MagicMock
from app.models import User
from app.database import get_db


@patch("app.routes.billing.construct_webhook_event")
def test_webhook_invoice_payment_succeeded(mock_construct, client, db):
    user = User(email="test@example.com", password_hash="h", stripe_customer_id="cus_123", credits_remaining=0)
    db.add(user)
    db.commit()
    db.refresh(user)

    mock_event = MagicMock()
    mock_event.type = "invoice.payment_succeeded"
    mock_invoice = MagicMock()
    mock_invoice.customer = "cus_123"
    mock_line = MagicMock()
    mock_line.price.metadata = {"credits": "50"}
    mock_invoice.lines.data = [mock_line]
    mock_event.data.object = mock_invoice
    mock_construct.return_value = mock_event

    resp = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    assert resp.status_code == 200
    db.refresh(user)
    assert user.credits_remaining == 50


@patch("app.routes.billing.construct_webhook_event")
def test_webhook_subscription_deleted(mock_construct, client, db):
    user = User(email="test2@example.com", password_hash="h", stripe_customer_id="cus_456", is_active=True)
    db.add(user)
    db.commit()

    mock_event = MagicMock()
    mock_event.type = "customer.subscription.deleted"
    mock_sub = MagicMock()
    mock_sub.customer = "cus_456"
    mock_event.data.object = mock_sub
    mock_construct.return_value = mock_event

    resp = client.post("/billing/webhook", content=b"{}", headers={"stripe-signature": "sig"})
    assert resp.status_code == 200
    db.refresh(user)
    assert user.is_active is False
