"""ARI WebSocket event handling

Copyright (c) 2014, Matthew Jordan
Matthew Jordan <mjordan@digium.com>

This program is free software, distributed under the terms of
the MIT License (MIT)
"""

import json
import logging
import urllib

try:
    from autobahn.websocket import WebSocketClientFactory, \
        WebSocketClientProtocol, connectWS
except:
    from autobahn.twisted.websocket import WebSocketClientFactory, \
        WebSocketClientProtocol, connectWS

LOGGER = logging.getLogger(__name__)

class ARIWebSocketClientFactory(WebSocketClientFactory):
    """Twisted WebSocket client protocol factory for ARI

    This is a relatively simple wrapper around WebSocketClientFactory that
    produces instances of ARIWebSocketClientProtocol.

    Attributes:
    receiver An instance of ARIEventResource
    """

    def __init__(self, receiver, host, username, password, apps, port=8088,
                 secure=False, debug=True):
        """Constructor

        Args:
        receiver The instance of ARIEventResource that will receive updates
        host     The Asterisk host to connect to
        username Username for the ARI account
        password Password for the ARI account
        apps     The application or list of applications to subscribe to
        port     Optional. Port to connect to.
        secure   Optional. Whether or not to use WSS or WS.
        debug    Optional. Enable greater debugging in WebSocketClientFactory
        """
        apps_param = apps
        if isinstance(apps, list):
            apps_param = ','.join(apps)
        scheme = 'wss' if secure else 'ws'
        params = urllib.urlencode({'app': apps_param,
                                   'api_key': '%s:%s' % (username, password)})
        url = "%s://%s:%d/ari/events?%s" % (scheme, host, port, params)

        super(ARIWebSocketClientFactory, self).__init__(url, debug=debug,
                                                        protocols=['ari'])
        self.receiver = receiver

    def buildProtocol(self, addr):
        """Build an ARIWebSocketClientProtocol instance"""
        return ARIWebSocketClientProtocol(self, self.receiver)


class ARIWebSocketClientProtocol(WebSocketClientProtocol):
    """Twisted WebSocket client protocol for ARI

    This acts as a very thin facade over WebSocketClientProtocol. Most of the
    work is deferred to the receiver, for two reasons:
    (1) It is much easier to unit test something that doesn't inherit from
        an Autobahn class
    (2) Our ARIEventResource receiver object maps the received JSON events
        to what our Asterisk server has told us it wants. That doesn't belong
        in our protocol.

    Attributes:
    receiver Our ARIEventResource receiver object
    """

    def __init__(self, receiver):
        """Constructor

        Args:
        receiver Our ARIEventResource receiver object
        """
        self.receiver = receiver

    def onOpen(self):
        """Callback called when the WebSocket connection is made"""
        self.receiver.on_open(self)

    def onClose(self, wasClean, code, reason):
        """Callback called when the WebSocket connection is closed"""
        self.receiver.on_close(self, wasClean, code, reason)

    def onMessage(self, msg, binary):
        """Callback called when the WebSocket receives a message"""
        event = None
        try:
            event = json.loads(msg)
        except:
            LOGGER.warn('Received invalid JSON from server: %s' % msg)
            return
        self.receiver.on_event(event)


