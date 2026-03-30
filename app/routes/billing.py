from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.billing import CheckoutRequest, CheckoutResponse, PortalResponse
from app.services.stripe_service import (
    create_checkout_session,
    create_portal_session,
    construct_webhook_event,
    get_credits_from_invoice,
)
from app.services.credits import add_credits

router = APIRouter(prefix="/billing", tags=["billing"])


@router.post("/checkout", response_model=CheckoutResponse)
def checkout(body: CheckoutRequest, user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked")
    url = create_checkout_session(
        customer_id=user.stripe_customer_id,
        price_id=body.price_id,
        success_url=f"{settings.frontend_url}/billing/success",
        cancel_url=f"{settings.frontend_url}/billing/cancel",
    )
    return CheckoutResponse(checkout_url=url)


@router.get("/portal", response_model=PortalResponse)
def portal(user: User = Depends(get_current_user)):
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="No Stripe customer linked")
    url = create_portal_session(
        customer_id=user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/billing",
    )
    return PortalResponse(portal_url=url)


@router.post("/webhook", status_code=200)
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature", "")

    try:
        event = construct_webhook_event(payload, sig_header)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid webhook signature")

    if event.type == "invoice.payment_succeeded":
        invoice = event.data.object
        customer_id = invoice.customer
        credits = get_credits_from_invoice(invoice)
        if credits > 0:
            user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
            if user:
                add_credits(db, user.id, credits)

    elif event.type == "customer.subscription.deleted":
        subscription = event.data.object
        customer_id = subscription.customer
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            user.is_active = False
            user.stripe_subscription_id = None
            db.commit()

    elif event.type == "customer.subscription.updated":
        # V1: track subscription ID only. Plan change credit adjustments deferred to V2.
        subscription = event.data.object
        customer_id = subscription.customer
        user = db.query(User).filter(User.stripe_customer_id == customer_id).first()
        if user:
            user.stripe_subscription_id = subscription.id
            db.commit()

    return {"status": "ok"}
