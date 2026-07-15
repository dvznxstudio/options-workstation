from datetime import datetime, timezone
import os
from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from .auth import LoginRequest, login_token, require_owner
from .live_engine import build_live_roadmap

app=FastAPI(title='Options Workstation Personal API',version='1.1.0')
origin=os.getenv('FRONTEND_ORIGIN','*')
origins=['*'] if origin=='*' else [origin.rstrip('/'),'http://localhost:3000']
app.add_middleware(CORSMiddleware,allow_origins=origins,allow_credentials=origin!='*',allow_methods=['GET','POST'],allow_headers=['*'])

@app.get('/')
def root(): return {'name':'Options Workstation Personal API','status':'online','docs':'/docs'}

@app.get('/health')
def health(): return {'status':'ok','time':datetime.now(timezone.utc).isoformat()}

@app.post('/api/login')
def login(payload:LoginRequest): return {'token':login_token(payload.access_code),'token_type':'bearer'}

@app.get('/api/roadmap/{symbol}')
def roadmap(symbol:str,_=Depends(require_owner)):
    try: return build_live_roadmap(symbol)
    except Exception as exc:
        return {'symbol':symbol.upper(),'spot':0,'source':'fallback','is_live':False,'updated_at':datetime.now(timezone.utc).isoformat(),'regime':'Data Unavailable','bias':'Do not trade from fallback data','conviction':0,'expected_move':{'low':0,'high':0,'points':0,'expiration':None},'levels':[],'briefing':'The app is online, but the free data source did not return a usable options chain.','scenarios':[],'warnings':[str(exc)],'metrics':{},'flow':[]}
