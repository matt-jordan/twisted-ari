"""FOO!
"""

import json
import urllib
import logging

from base64 import b64encode

from zope.interface import implements

from twisted.internet import reactor
from twisted.internet.defer import succeed
from twisted.web.client import Agent, HTTPConnectionPool
from twisted.web.http_headers import Headers
from twisted.web.iweb import IBodyProducer
from swaggerpy.http_client import HttpClient, Authenticator

from autobahn.twisted.websocket import WebSocketClientFactory, \
    WebSocketClientProtocol, connectWS

LOGGER = logging.getLogger(__name__)

class Request(object):
    """A working object for an HTTP or WS request

    Attributes:
    method
    url
    params
    headers
    body_producer
    """

    def __init__(self, method, url, params=None):
        """Constructor

        Args:
        method
        url
        params
        """
        self.method = method
        self.url = url
        self.params = params or {}
        self.headers = Headers()
        self.body_producer = None

    def build_url(self):
        """Build the URL from this object

        Returns:
        A string representation of the URL
        """
        if len(self.params) == 0:
            return self.url
        encoded_params = urllib.urlencode(self.params)
        return "%s?%s" % (self.url, encoded_params)

class JSONBodyProducer(object):
    """

    Attributes:
    body
    length
    """
    implements(IBodyProducer)

    def __init__(self, body):
        self.body = json.dumps(body, separators=(',', ':'))
        self.length = len(body)

    #pylint: disable=C0103
    def startProducing(self, consumer):
        """

        Args:
        consumer
        """
        consumer.write(self.body)
        return succeed(None)

    #pylint: disable=C0103,C0111
    def pauseProducing(self):
        pass

    #pylint: disable=C0103,C0111
    def stopProducing(self):
        pass


class BasicAuthenticator(Authenticator):
    """

    Attributes:
    userpass
    """
    def __init__(self, host, username, password):
        """Constructor

        Args:
        host
        username
        password
        """
        super(BasicAuthenticator, self).__init__(host)

        self.userpass = b64encode(b'%s:%s' % (username, password))

    def apply(self, request):
        """

        Args:
        request
        """
        request.headers.addRawHeader(name=b'Authorization',
            value=b'Basic ' + self.userpass)

class ApiKeyAuthenticator(Authenticator):
    """

    Attributes:
    param_name
    api_key
    """

    def __init__(self, host, api_key, param_name='api_key'):
        """Constructor

        Args:
        host
        api_key
        param_name
        """
        super(ApiKeyAuthenticator, self).__init__(host)
        self.param_name = param_name
        self.api_key = api_key

    def apply(self, request):
        """

        Args:
        request
        """
        request.params[self.param_name] = self.api_key


class ARIWebSocketClientFactory(WebSocketClientFactory):
    """Twisted WebSocket client protocol factory for ARI

    This is a relatively simple wrapper around WebSocketClientFactory that
    produces instances of ARIWebSocketClientProtocol.

    Attributes:
    receiver An instance of ARIEventResource
    """

    def __init__(self, receiver, url, debug=True):
        """Constructor

        Args:
        receiver The instance of ARIEventResource that will receive updates
        url      The URL to connect the WebSocket to
        debug    Optional. Enable greater debugging in WebSocketClientFactory
        """
        WebSocketClientFactory.__init__(self, url, debug=debug,
                                        protocols=['ari'])
        self.receiver = receiver

    #pylint: disable=C0103
    def buildProtocol(self, addr):
        """Build an ARIWebSocketClientProtocol instance

        Returns:
        An instance of ARIWebSocketClientProtocol
        """
        return ARIWebSocketClientProtocol(self, self.receiver)

    def connect(self):
        """Connect the client factory to the WebSocket server

        Returns:
        An instance of twisted.internet.interfaces.IConnector
        """
        return connectWS(self)

#pylint: disable=R0904
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

    #pylint: disable=C0103
    def onOpen(self):
        """Callback called when the WebSocket connection is made"""
        self.receiver.on_open(self)

    #pylint: disable=C0103
    def onClose(self, wasClean, code, reason):
        """Callback called when the WebSocket connection is closed"""
        self.receiver.on_close(self, wasClean, code, reason)

    #pylint: disable=C0103,W0613
    def onMessage(self, msg, binary):
        """Callback called when the WebSocket receives a message"""
        event = None
        try:
            event = json.loads(msg)
        except ValueError:
            LOGGER.warn('Received invalid JSON from server: %s' % msg)
            return
        self.receiver.on_event(event)


class AsyncHTTPClient(HttpClient):
    """@@@@

    Attributes:
    http_pool
    agent
    authenticator
    ws_conn
    """

    def __init__(self):
        """Constructor
        """
        super(AsyncHTTPClient, self).__init__()
        self.http_pool = HTTPConnectionPool(reactor)
        self.agent = Agent(reactor, pool=self.http_pool)
        self.authenticator = None
        self.ws_conn = None

    def close(self):
        """
        """
        self.http_pool.closeCachedConnections()
        if self.ws_conn:
            self.ws_conn.disconnect()

    def set_basic_auth(self, host, username, password):
        """Set up a SwaggerPy basic authenticator

        Args:
        host
        username
        password
        """
        self.authenticator = BasicAuthenticator(
            host=host, username=username, password=password)

    def set_api_key(self, host, api_key, param_name='api_key'):
        """Set up a SwaggerPy API key authenticator

        Args:
        host
        api_key
        param_name
        """
        self.authenticator = ApiKeyAuthenticator(
            host=host, api_key=api_key, param_name=param_name)

    def apply_authentication(self, req):
        """Apply authentication to a request

        Args:
        req  The Request instance to apply authentication to
        """
        if self.authenticator and self.authenticator.matches(req.url):
            self.authenticator.apply(req)

    def request(self, method, url, params=None, data=None):
        """Perform an HTTP request

        Args:
        method
        url
        params
        data

        Returns:
        twisted.Deferred
        """

        request = Request(method, url, params=params)
        self.apply_authentication(request)
        if data:
            request.headers.addRawHeader('Content-Type', 'application/json')
            request.body_producer = JSONBodyProducer(data)
        deferred = self.agent.request(request.method,
                                      request.build_url(),
                                      request.headers,
                                      request.body_producer)
        return deferred

    def ws_connect(self, url, params=None):
        """Websocket-client based implementation.

        Args:
        url
        params

        Note that the connection object returned by this function
        should generally not be used to close the WebSocket connection.
        The close method should be used instead, as that will close
        both the WebSocket as well as the persistent HTTP connection.

        Returns:
        An instance of twisted.internet.interfaces.IConnector
        """
        request = Request('GET', url, params=params)
        self.apply_authentication(request)

        # @@@@ TODO: Add the receiver
        ws_factory = ARIWebSocketClientFactory(None, request.build_url())
        self.ws_conn = ws_factory.connect()
        return self.ws_conn

