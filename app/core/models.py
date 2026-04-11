from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

class CloudStatus(str, Enum):
    UNKNOWN = "unknown"
    BUILDING = "building"
    ACTIVE = "active"
    ARCHIVED = "archived"
    ERROR = "error"

class IPAddress(BaseModel):
    id: str
    address: str = ""
    status: CloudStatus = CloudStatus.UNKNOWN
    zone_id: Optional[str] = None
    reserved: bool = False
    
    @property
    def is_active(self) -> bool:
        return self.status == CloudStatus.ACTIVE and bool(self.address)


class SubnetInsight(BaseModel):
    network: str
    count: int = 0
    share_percent: float = 0.0
    category: str = "observed"

class RollerStats(BaseModel):
    attempts: int = 0
    matches: int = 0
    non_matches: int = 0
    errors: int = 0
    deleted_resources: int = 0
    active_workers: int = 0
    is_running: bool = False
    uptime_seconds: int = 0
    unique_ip_count: int = 0
    unique_subnet_count: int = 0
    attempts_per_minute: float = 0.0
    success_rate_percent: float = 0.0
    last_ip: str = ""
    last_match_ip: str = ""
    last_error: str = ""
    last_subnet: str = ""
    top_subnets: list[SubnetInsight] = Field(default_factory=list)
