import uuid
import pytest
from app.services.credits import deduct_credit, refund_credit
from app.models import User, CreditTransaction, TransactionType


def test_deduct_credit_success(db):
    user = User(email="test@example.com", password_hash="hashed", credits_remaining=5)
    db.add(user)
    db.commit()
    db.refresh(user)
    success = deduct_credit(db, user.id)
    assert success is True
    db.refresh(user)
    assert user.credits_remaining == 4
    txn = db.query(CreditTransaction).filter(CreditTransaction.user_id == user.id).first()
    assert txn.amount == -1
    assert txn.type == TransactionType.deduction


def test_deduct_credit_insufficient(db):
    user = User(email="broke@example.com", password_hash="hashed", credits_remaining=0)
    db.add(user)
    db.commit()
    db.refresh(user)
    success = deduct_credit(db, user.id)
    assert success is False
    db.refresh(user)
    assert user.credits_remaining == 0


def test_refund_credit(db):
    user = User(email="refund@example.com", password_hash="hashed", credits_remaining=5)
    db.add(user)
    db.commit()
    db.refresh(user)
    job_id = uuid.uuid4()
    refund_credit(db, user.id, job_id)
    db.refresh(user)
    assert user.credits_remaining == 6
