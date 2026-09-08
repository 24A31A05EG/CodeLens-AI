from sqlalchemy.orm import Session

from models.db_models import User


DEFAULT_USERNAME = "codelens_demo"
DEFAULT_EMAIL = "demo@codelens.local"


def get_or_create_default_user(db: Session) -> User:
    user = (
        db.query(User)
        .filter(User.username == DEFAULT_USERNAME)
        .first()
    )

    if user:
        return user

    user = User(
        username=DEFAULT_USERNAME,
        email=DEFAULT_EMAIL,
    )

    db.add(user)
    db.commit()
    db.refresh(user)

    return user
