from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..models import JobIngestRecord


class JobSource(ABC):
    @abstractmethod
    def fetch_jobs(self) -> List[JobIngestRecord]:
        raise NotImplementedError

