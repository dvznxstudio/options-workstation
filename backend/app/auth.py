from datetime import datetime, timedelta, timezone
import os
import jwt
from fastapi import Header, HTTPException
from pydantic import BaseModel

ACCESS_CODE=os.getenv('PERSONAL_ACCESS_CODE','change-me')
SECRET=os.getenv('TOKEN_SECRET','change-this-secret')

class LoginRequest(BaseModel):
    access_code:str

def login_token(code:str)->str:
    if code!=ACCESS_CODE:
        raise HTTPException(status_code=401,detail='Invalid access code')
    now=datetime.now(timezone.utc)
    return jwt.encode({'sub':'owner','iat':now,'exp':now+timedelta(hours=72)},SECRET,algorithm='HS256')

def require_owner(authorization:str|None=Header(default=None)):
    if not authorization or not authorization.startswith('Bearer '):
        raise HTTPException(status_code=401,detail='Missing access token')
    try:
        return jwt.decode(authorization[7:],SECRET,algorithms=['HS256'])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401,detail='Invalid or expired access token') from exc
