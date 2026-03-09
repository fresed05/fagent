"""Message bus module for decoupled channel-agent communication."""

from fagent.bus.events import InboundMessage, OutboundMessage
from fagent.bus.queue import MessageBus

__all__ = ["MessageBus", "InboundMessage", "OutboundMessage"]
