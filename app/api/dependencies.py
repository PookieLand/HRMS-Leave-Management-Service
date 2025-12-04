from typing import Annotated

from fastapi import Depends
from sqlmodel import Session

from app.core.database import get_session

# Database session dependency
SessionDep = Annotated[Session, Depends(get_session)]

# Add CurrentUserDep in here
