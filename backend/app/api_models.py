from pydantic import BaseModel


class ServerAlertRequest(BaseModel):
    symbol: str = "SPY"
    type: str
    threshold: float | None = None
    enabled: bool = True
