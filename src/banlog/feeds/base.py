from abc import ABC, abstractmethod


class FeedParser(ABC):
    name: str

    @abstractmethod
    def fetch(self, url: str) -> bytes: ...

    @abstractmethod
    def parse(self, raw: bytes) -> set[str]: ...
