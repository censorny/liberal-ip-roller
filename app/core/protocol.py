from typing import Protocol, List, Optional
from .models import IPAddress

class CloudProvider(Protocol):
    """Protocol defining the interface for all cloud service integrations."""
    
    async def list_addresses(self) -> List[IPAddress]:
        """Returns all active IPs/VMs in the project."""
        ...

    async def create_address(self, zone_id: str) -> str:
        """
        Initiates creation of a new IP/VM.
        Returns an Operation ID or Resource ID.
        """
        ...

    async def wait_for_operation(self, op_id: str, timeout: int = 300) -> str:
        """
        Polls until the resource is active and returns the stabilized Resource ID.
        """
        ...

    async def delete_address(self, resource_id: str) -> bool:
        """Deletes the specified IP/VM and returns True when cleanup is complete."""
        ...

    async def get_address_info(self, resource_id: str) -> IPAddress:
        """Fetches fresh state for a single resource."""
        ...

    async def close(self):
        """Cleanly releases all connections."""
        ...
