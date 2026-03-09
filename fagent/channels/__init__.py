"""Chat channels module with plugin architecture."""

from fagent.channels.base import BaseChannel
from fagent.channels.manager import ChannelManager

__all__ = ["BaseChannel", "ChannelManager"]
