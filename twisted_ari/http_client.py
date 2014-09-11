
from base64 import b64encode

from zope.interface import implements

from twisted.internet import reactor
from twisted.internet.defer import succeed
from twisted.web.client import Agent, HTTPConnectionPool
from twisted.web.http_headers import Headers
from swaggerpy.http_client import HttpClient, Authenticator

import json

class Request(Object):

    def __init__(self, method, url, params=None):
        self.method = method
        self.url = url
        self.params = params or {}
        self.headers = Headers()
        self.body_producer = None

class JSONBodyProducer(object):
    implements(IBodyProducer)

    def __init__(self, body):
        self.body = json.dumps(body, separators=(',', ':'))
        self.length = len(body)

    def startProducing(self, consumer):
        consumer.write(self.body)
        return succeed(None)

    def pauseProducing(self):
        pass

    def stopProducing(self):
        pass


class BasicAuthenticator(Authenticator):

    def __init__(self, host, username, password):
        super(BasicAuthenticator, self).__init__(host)

        self.userpass = b64encode(b'%s:%s' % (username, password))

    def apply(self, request):
        request.headers.addRawHeader(name=b'Authorization',
            value=b'Basic ' + self.userpass)

class ApiKeyAuthenticator(Authenticator):

    def __init__(self, host, api_key, param_name='api_key'):
        super(ApiKeyAuthenticator, self).__init__(host)
        self.param_name = param_name
        self.api_key = api_key

    def apply(self, request):
        self.request.params[self.param_name] = self.api_key


class AsyncHttpClient(HttpClient):

    def __init__(self):
        """Constructor
        """
        pool = HTTPConnectionPool(reactor)
        self.agent = Agent(reactor, pool=pool)

    def close(self):
        self.session.close()
        # There's no WebSocket factory to close; close connections individually

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
            request.body_producer = JSONBodyProducder(data)
        df = self.agent.request(request.method,
                                request.url,
                                request.headers,
                                request.body_producer)
        return df

    def ws_connect(self, url, params=None):
        """Websocket-client based implementation.

        :return: WebSocket connection
        :rtype:  websocket.WebSocket
        """
        # Build a prototype request and apply authentication to it
        proto_req = requests.Request('GET', url, params=params)
        self.apply_authentication(proto_req)
        # Prepare the request, so params will be put on the url,
        # and authenticators can manipulate headers
        preped_req = proto_req.prepare()
        # Pull the Authorization header, if needed
        header = ["%s: %s" % (k, v)
                  for (k, v) in preped_req.headers.items()
                  if k == 'Authorization']
        # Pull the URL, which includes query params
        url = preped_req.url
        # Requests version 2.0.0 (at least) will no longer form a URL for us
        # for ws scheme types, so we do it manually
        if params:
            joined_params = "&".join(["%s=%s" % (k, v)
                                     for (k, v) in params.items()])
            url += "?%s" % joined_params
        return websocket.create_connection(url, header=header)

    def apply_authentication(self, req):
        if self.authenticator and self.authenticator.matches(req.url):
            self.authenticator.apply(req)
