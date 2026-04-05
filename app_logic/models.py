"""
Unified Data Models for Liberal IP Roller.
Provides standardized schemas for cloud entities across different providers.
"""

from typing import Optional
from pydantic import BaseModel


class CloudAddress(BaseModel):
    """
    Standardized representation of a Reserved IP Address in any cloud.
    """
    id: str
    address: str
    status: str
    zone_id: Optional[str] = None
    folder_id: Optional[str] = None
