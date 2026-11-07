"""Enterprise boundaries. Only local stubs are installed in this version."""

from typing import Protocol


class ApprovalGateway(Protocol):
    def submit(self, command_id: str, snapshot: dict) -> dict: ...
    def query(self, command_id: str) -> dict | None: ...


class DirectoryGateway(Protocol):
    def employees(self) -> list[dict]: ...


class NotificationGateway(Protocol):
    def send(self, recipient_id: str, invitation_id: str) -> dict: ...


class LedgerSink(Protocol):
    def project(self, event_id: str, rows: list[dict]) -> dict: ...
