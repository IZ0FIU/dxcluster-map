from abc import ABC, abstractmethod
from typing import List
from models import Spot


class SpotProvider(ABC):
    """Interfaccia comune per qualsiasi fonte di spot."""

    @abstractmethod
    def fetch_spots(self, limit: int = 200) -> List[Spot]:
        ...
