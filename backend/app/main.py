import os

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from .auth import LoginRequest, create_token, require_owner, verify_access_code
from .engine import get_diagnostics, get_roadmap
from .providers import SUPPORTED_SYMBOLS


app = FastAPI(
    title="Options Workstation Personal API",
    version="3.0.0",
)

origin = os.getenv("FRONTEND_ORIGIN", "*")
origins = (
    ["*"]
    if origin == "*"
    else [
        origin.rstrip("/"),
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=origin != "*",
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {
        "name": "Options Workstation Personal API",
        "status": "online",
        "version": "3.0.0",
        "features": [
            "provider cascade",
            "5-minute intraday bars",
            "VWAP",
            "EMA 9/21",
            "opening range",
            "automatic scenario states",
        ],
        "docs": "/docs",
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0"}


@app.post("/api/login")
def login(payload: LoginRequest):
    if not verify_access_code(payload.access_code):
        raise HTTPException(status_code=401, detail="Invalid access code.")
    return {"token": create_token(), "token_type": "bearer"}


@app.get("/api/symbols")
def symbols(_: dict = Depends(require_owner)):
    return {"symbols": sorted(SUPPORTED_SYMBOLS)}


@app.get("/api/roadmap/{symbol}")
def roadmap(symbol: str, _: dict = Depends(require_owner)):
    return get_roadmap(symbol)


@app.get("/api/diagnostics/{symbol}")
def diagnostics(symbol: str, _: dict = Depends(require_owner)):
    return get_diagnostics(symbol)
