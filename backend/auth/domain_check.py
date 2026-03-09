from backend.config import ALLOWED_DOMAIN
from fastapi import HTTPException, status

def validate_domain(email: str) -> bool:
    """Ensures only @constelli.com emails are accepted."""
    email = email.strip().lower()
    if "@" not in email:
        return False
    domain = email.split("@")[-1]
    return domain == ALLOWED_DOMAIN

def enforce_domain(email: str):
    if not validate_domain(email):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access restricted to @{ALLOWED_DOMAIN} email addresses only."
        )