from dataclasses import dataclass


@dataclass
class EmailItem:
    custom_id: str
    thread_id: str
    sender: str
    subject: str
    date: str
    snippet: str
    body: str


@dataclass
class Decision:
    action: str
    reason: str
    summary: str
    reply: str
