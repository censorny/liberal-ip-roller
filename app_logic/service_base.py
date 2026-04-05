"""
Abstract Cloud Infrastructure Interface.
Defines the contract for all cloud service implementations.
"""

from abc import ABC, abstractmethod
from typing import List, Optional
from .models import CloudAddress


class CloudService(ABC):
    """
    Abstract Base Class for VPC Cloud Service providers.
    Ensures consistent interaction patterns across different cloud ecosystems.
    """

    @abstractmethod
    async def list_addresses(self) -> List[CloudAddress]:
        """ Fetches all reserved IP addresses for the current project. """
        pass

    @abstractmethod
    async def create_address(self, zone_id: str) -> str:
        """
        Initiates IP creation.
        Returns: Operation ID or directly the new address ID depending on provider.
        """
        pass

    @abstractmethod
    async def delete_address(self, addr_id: str) -> Optional[str]:
        """
        Requests IP deletion.
        Returns: Operation ID or None.
        """
        pass

    @abstractmethod
    async def wait_for_operation(self, op_id: str, timeout: int = 60) -> str:
        """
        Standardized Operation Poller. 
        Returns: The resulting address ID or success message.
        """
        pass

    @abstractmethod
    async def get_address_info(self, addr_id: str) -> CloudAddress:
        """ Fetches full metadata for a specific address. """
        pass

    @abstractmethod
    async def close(self):
        """ Cleanly terminates connection pools. """
        pass
