"""Pydantic models and constants for Discord webhook messages."""

from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class DiscordEmbed(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    color: Optional[int] = None
    timestamp: Optional[str] = None
    fields: Optional[List[Dict[str, Any]]] = None
    footer: Optional[Dict[str, str]] = None
    image: Optional[Dict[str, str]] = None


class DiscordMessage(BaseModel):
    username: Optional[str] = None
    avatar_url: Optional[str] = None
    content: Optional[str] = None
    embeds: Optional[List[DiscordEmbed]] = None


SEVERITY_COLORS = {
    'low': 0x00ff00,      # Green
    'medium': 0xffff00,   # Yellow
    'high': 0xff8800,     # Orange
    'critical': 0xff0000,  # Red
}

SEVERITY_EMOJIS = {
    'low': '🟢',
    'medium': '🟡',
    'high': '🟠',
    'critical': '🔴',
}
