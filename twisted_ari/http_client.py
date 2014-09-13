"""Asynchronous HTTP client for swaggerpy

Copyright (c) 2014, Matthew Jordan
Matthew Jordan <mjordan@digium.com>

This program is free software, distributed under the terms of
the MIT License (MIT)

This module provides an asynchronous HTTP client for SwaggerPy, along with
supporting classes. The asynchronous HTTP client uses a twisted HTTP agent
for HTTP requests, and an Autobahn websocket for the ARI events. Both the
agent and the websocket are handled by the Asynchronous HTTP client.

Generally, users of this module should:
(1) Implement the IARIEventReceiver interface in some class
(2) Create an instance of AsyncHTTPClient for SwaggerPy, providing it an
    instance of IARIEventReceiver
(3) Process and handle events as needed; query ARI through the instance of
    AsyncHTTPClient
"""

import json
import urllib
import logging

from base64 import b64encode

from zope.interface import Interface, implements

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
    method: The HTTP verb to use for this request
    url: The base URL for the request
    params: Parameters for the request (unencoded)
    headers: The twisted.web.http_headers HTTP headers object
    body_producer: A twisted.web.iweb IBodyProducer. Assign if needed.
    """

    def __init__(self, method, url, params=None):
        """Constructor

        Args:
        method: The HTTP verb to use for this request
        url: The base url for the request
        params: Parameters for the request
        """
        self.method = method
        self.url = url
        self.params = params or {}
        self.headers = Headers()
        self.body_producer = None

    def build_url(self):
        """Build the URL from this object

        This will encode the parameters and append them to the URL

        Returns:
        A string representation of the URL
        """
        if len(self.params) == 0:
            return self.url
        encoded_params = urllib.urlencode(self.params)
        return "%s?%s" % (self.url, encoded_params)


class JSONBodyProducer(object):
    """A twisted.web.iweb.IBodyProducer for application/json content types

    Attributes:
    body: A string representation of the JSON body
    length: The length of body
    """
    implements(IBodyProducer)

    def __init__(self, body):
        """Constructor

        Args:
        body: The JSON to produce for the HTTP request
        """
        self.body = json.dumps(body, separators=(',', ':'))
        self.length = len(body)

    #pylint: disable=C0103
    def startProducing(self, consumer):
        """IBodyProducer.startProducing override

        This will write the JSON body to the consumer

        Args:
        consumer: The consumer to write the body to

        Returns:
        A twisted.internet.defer.succeed
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
    """A swaggerpy.Authenticator authentication object for basic HTTP auth

    Attributes:
    userpass: Base 64 encoded username/password
    """
    def __init__(self, host, username, password):
        """Constructor

        Args:
        host: The host to authenticate for
        username: The user's name
        password: The user's password
        """
        super(BasicAuthenticator, self).__init__(host)

        self.userpass = b64encode(b'%s:%s' % (username, password))

    def apply(self, request):
        """Apply the authentication to the Request object

        This will add an Authorization header with the base 64 encoded
        username and password

        Args:
        request: The request to apply authentication to
        """
        request.headers.addRawHeader(name=b'Authorization',
            value=b'Basic ' + self.userpass)


class ApiKeyAuthenticator(Authenticator):
    """A swaggerpy.Authenticator for API key authentication (query param)

    Attributes:
    param_name: The name of the query parameter
    api_key: The API key that the query parameter will specify
    """

    def __init__(self, host, api_key, param_name='api_key'):
        """Constructor

        Args:
        host: The host to provide authentication for
        api_key: The API key to use
        param_name: Optional. The parameter name for the API key. Defaults to
                    api_key.
        """
        super(ApiKeyAuthenticator, self).__init__(host)
        self.param_name = param_name
        self.api_key = api_key

    def apply(self, request):
        """Apply the authentication to the Request object

        This will add a query parameter (param_name) with the API key (api_key)

        Args:
        request: The request to apply authentication to
        """
        request.params[self.param_name] = self.api_key


class IARIEventReceiver(Interface):
    """An event receiver used with the ARI protocol

    An implementation of this interface is passed to an ARI protocol factory,
    and will be used with whatever instances of the protocol are made. The
    protocol, in turn, will call the implementation when events occur in the
    protocol, such as when an event is received from Asterisk.
    """

    def on_open(protocol):
        """Callback called when the ARI protocol connects

        Args:
        protocol: An instance of the ARI protocol communicating with Asterisk
        """

    def on_close(protocol, was_clean, code, reason):
        """Callback called when the ARI protocol disconnects

        Args:
        protocol: An instance of the ARI protocol communicating with Asterisk
        was_clean: True iff the WebSocket was closed cleanly
        code: Close status code, as sent by the WebSocket peer
        reason: Close reason, as sent by the WebSocket peer
        """

    def on_event(protocol, event_obj):
        """Callback called when an ARI event is received from Asterisk

        Args:
        protocol: An instance of the ARI protocol communicating with Asterisk
        event_obj: The ARI event object received from Asterisk
        """


class ARIWebSocketClientFactory(WebSocketClientFactory):
    """Twisted WebSocket client protocol factory for ARI

    This is a relatively simple wrapper around WebSocketClientFactory that
    produces instances of ARIWebSocketClientProtocol.

    Attributes:
    receiver An instance of IARIEventReceiver
    """

    def __init__(self, receiver, url, debug=True):
        """Constructor

        Args:
        receiver: The instance of IARIEventReceiver that will receive updates
        url: The URL to connect the WebSocket to
        debug: Optional. Enable greater debugging in WebSocketClientFactory.
               Defaults to True.
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

    Attributes:
    receiver: Our IARIEventReceiver receiver object
    """

    def __init__(self, receiver):
        """Constructor

        Args:
        receiver: Our IARIEventReceiver receiver object
        """
        self.receiver = receiver

    #pylint: disable=C0103
    def onOpen(self):
        """Callback called when the WebSocket connection is made"""
        self.receiver.on_open(self)

    #pylint: disable=C0103
    def onClose(self, wasClean, code, reason):
        """Callback called when the WebSocket connection is closed

        Args:
        wasClean: True iff the WebSocket was closed cleanly
        code: Close status code, as sent by the WebSocket peer
        reason: Close reason, as sent by the WebSocket peer
        """
        self.receiver.on_close(self, wasClean, code, reason)

    #pylint: disable=C0103,W0613
    def onMessage(self, msg, isBinary):
        """Callback called when the WebSocket receives a message

        Args:
        msg: Message payload received from the WebSocket
        isBinary: True iff msg is binary
        """

        # Ignore binary messages - we can't understand those!
        if isBinary:
            return

        event = None
        try:
            event = json.loads(msg)
        except ValueError:
            LOGGER.warn('Received invalid JSON from server: %s' % msg)
            return
        self.receiver.on_event(event)


class AsyncHTTPClient(HttpClient):
    """An asynchronous swaggerpy.HttpClient using twisted

    Attributes:
    receiver: An instance of IARIEventReceiver
    http_pool: A twisted.web.client.HTTPConnectionPool, used with agent
    agent: A twisted.web.client.Agent, for sending HTTP requests
    authenticator: The authenticator used with agent and ws_conn
    ws_conn: A twisted.internet.interfaces.IConnector representing the
             WebSocket connection
    """

    def __init__(self, receiver):
        """Constructor

        Args:
        receiver: An instance of IARIEventReceiver
        """
        super(AsyncHTTPClient, self).__init__()
        self.receiver = receiver
        self.http_pool = HTTPConnectionPool(reactor)
        self.agent = Agent(reactor, pool=self.http_pool)
        self.authenticator = None
        self.ws_conn = None

    def close(self):
        """Close the HTTP persistent connections and the WebSocket connection
        """
        self.http_pool.closeCachedConnections()
        if self.ws_conn:
            self.ws_conn.disconnect()

    def set_basic_auth(self, host, username, password):
        """Set up a SwaggerPy basic authenticator

        Args:
        host: The host to authenticate
        username: The user's name
        password: The user's password
        """
        self.authenticator = BasicAuthenticator(
            host=host, username=username, password=password)

    def set_api_key(self, host, api_key, param_name='api_key'):
        """Set up a SwaggerPy API key authenticator

        Args:
        host: The host to authenticate
        api_key: The API key
        param_name: The query parameter for api_key
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
        method: The HTTP verb to use for the request
        url: The base URL of the request
        params: Optional. Query parameters to use with the request.
        data: A JSON body to encode and provide with the request

        Returns:
        twisted.Deferred that will be called when the request completes. On
        success, the callback will be called; on failure, the errback will be
        called.
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
        url: The base url of the request
        params: Optional. Query parameters to use with the request.

        Note that the connection object returned by this function
        should generally not be used to close the WebSocket connection.
        The close method should be used instead, as that will close
        both the WebSocket as well as the persistent HTTP connection.

        Returns:
        An instance of twisted.internet.interfaces.IConnector
        """
        request = Request('GET', url, params=params)
        self.apply_authentication(request)

        ws_factory = ARIWebSocketClientFactory(self.receiver,
                                               request.build_url())
        self.ws_conn = ws_factory.connect()
        return self.ws_conn

