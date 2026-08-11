"""Internal alert representation shared across the notifier."""

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel


class Alert(BaseModel):
    """Internal representation of a printer event/notice."""
    id: str
    title: str
    description: str
    severity: Literal['low', 'medium', 'high', 'critical']
    timestamp: str
    source: Optional[str] = None
    details: Optional[Dict[str, Any]] = None


class PrinterApiResponse(BaseModel):
    """Response format from the printer's alert API."""
    success: bool
    data: List[Alert]
    timestamp: str
