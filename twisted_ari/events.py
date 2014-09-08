"""ARI WebSocket event handling

Copyright (c) 2014, Matthew Jordan
Matthew Jordan <mjordan@digium.com>

This program is free software, distributed under the terms of
the MIT License (MIT)
"""

import json
import logging

try:
    from autobahn.websocket import WebSocketClientFactory, \
        WebSocketClientProtocol, connectWS
except:
    from autobahn.twisted.websocket import WebSocketClientFactory, \
        WebSocketClientProtocol, connectWS

LOGGER = logging.getLogger(__name__)


