from sqlalchemy import update
from sqlalchemy.orm import Session

from app.models.user import User
from app.models.transaction import CreditTransaction, TransactionType


def deduct_credit(db: Session, user_id: str, job_id: str | None = None, commit: bool = True) -> bool:
    """Atomically deduct 1 credit. Set commit=False to let caller manage transaction."""
    result = db.execute(
        update(User)
        .where(User.id == user_id, User.credits_remaining >= 1)
        .values(credits_remaining=User.credits_remaining - 1)
    )
    if result.rowcount == 0:
        return False
    txn = CreditTransaction(user_id=user_id, amount=-1, type=TransactionType.deduction, job_id=job_id)
    db.add(txn)
    if commit:
        db.commit()
    return True


def refund_credit(db: Session, user_id: str, job_id: str | None = None, commit: bool = True) -> None:
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_remaining=User.credits_remaining + 1)
    )
    txn = CreditTransaction(user_id=user_id, amount=1, type=TransactionType.refund, job_id=job_id)
    db.add(txn)
    if commit:
        db.commit()


def add_credits(db: Session, user_id: str, amount: int, commit: bool = True) -> None:
    db.execute(
        update(User)
        .where(User.id == user_id)
        .values(credits_remaining=User.credits_remaining + amount)
    )
    txn = CreditTransaction(user_id=user_id, amount=amount, type=TransactionType.purchase)
    db.add(txn)
    if commit:
        db.commit()
