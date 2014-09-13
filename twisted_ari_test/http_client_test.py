#!/usr/bin/env python

#
# Copyright (c) 2013, Digium, Inc.
#

"""HTTP client tests
"""

import unittest

from base64 import b64encode

from twisted_ari.http_client import Request, BasicAuthenticator, ApiKeyAuthenticator, \
    ARIWebSocketClientProtocol

class RequestTest(unittest.TestCase):
    """Basic tests for the Request object
    """

    def test_http_url(self):
        req = Request('GET', 'http://foobar.com:8088/foo')
        self.assertEqual('GET', req.method)
        self.assertEqual('http://foobar.com:8088/foo', req.url)
        self.assertEqual('http://foobar.com:8088/foo', req.build_url())

    def test_http_url_params(self):
        req = Request('GET', 'http://foobar.com:8088/foo',
                      {'api_key': 'blah', 'app': 'my_app'})
        self.assertEqual('GET', req.method)
        self.assertEqual('http://foobar.com:8088/foo', req.url)
        self.assertEqual({'api_key': 'blah', 'app': 'my_app'}, req.params)
        self.assertEqual('http://foobar.com:8088/foo?app=my_app&api_key=blah', req.build_url())

    def test_ws_url_params(self):
        req = Request('GET', 'ws://foobar.com:8088/foo',
                      {'api_key': 'blah', 'app': 'my_app'})
        self.assertEqual('GET', req.method)
        self.assertEqual('ws://foobar.com:8088/foo', req.url)
        self.assertEqual({'api_key': 'blah', 'app': 'my_app'}, req.params)
        self.assertEqual('ws://foobar.com:8088/foo?app=my_app&api_key=blah', req.build_url())

class BasicAuthenticatorTest(unittest.TestCase):
    """Tests for the BasicAuthenticator class
    """

    def test_constructor(self):
        auth = BasicAuthenticator('http://localhost', 'foo', 'secret')
        self.assertEqual(b64encode(b'foo:secret'), auth.userpass)

    def test_apply(self):
        auth = BasicAuthenticator('http://localhost', 'foo', 'secret')
        req = Request('GET', 'http://foobar.com:8088/foo')
        auth.apply(req)
        header = req.headers.getRawHeaders('Authorization')[0]
        self.assertEqual('Basic %s' % b64encode(b'foo:secret'), header)

class ApiKeyAuthenticatorTest(unittest.TestCase):
    """Tests for the ApiKeyAuthenticator class
    """

    def test_constructor(self):
        auth = ApiKeyAuthenticator('http://localhost', 'secret')
        self.assertEqual('api_key', auth.param_name)
        self.assertEqual('secret', auth.api_key)

        auth = ApiKeyAuthenticator('http://localhost', 'secret', param_name='my_key')
        self.assertEqual('my_key', auth.param_name)
        self.assertEqual('secret', auth.api_key)

    def test_apply(self):
        auth = ApiKeyAuthenticator('http://localhost', 'secret')
        req = Request('GET', 'http://foobar.com:8088/foo')
        auth.apply(req)
        self.assertEqual('secret', req.params.get('api_key'))

class ARIWebSocketClientProtocolTest(unittest.TestCase):
    """Tests for ARIWebSocketClientProtocol
    """

    class MockReceiver(object):

        def __init__(self):
            self.opens = 0
            self.closes = 0
            self.events = 0
            self.last_event = None

        def on_open(self):
            self.opens += 1

        def on_close(self):
            self.closes += 1

        def on_event(self, ev):
            self.events += 1
            self.last_event = ev

    def test_onMessage_nominal(self):
        receiver = ARIWebSocketClientProtocolTest.MockReceiver()
        protocol = ARIWebSocketClientProtocol(receiver)
        json_msg = '["foo",{"bar":["baz",null,1.0,2]}]'
        protocol.onMessage(json_msg, None)
        self.assertEqual(1, receiver.events)
        self.assertEqual('foo', receiver.last_event[0])
        self.assertEqual(['baz', None, 1.0, 2], receiver.last_event[1].get('bar'))

    def test_onMessage_off_nominal(self):
        receiver = ARIWebSocketClientProtocolTest.MockReceiver()
        protocol = ARIWebSocketClientProtocol(receiver)
        invalid_json_msg = '["foo",{"bar":0}'
        protocol.onMessage(invalid_json_msg, None)
        self.assertEqual(0, receiver.events)

if __name__ == '__main__':
    unittest.main()

