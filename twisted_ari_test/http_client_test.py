#!/usr/bin/env python

#
# Copyright (c) 2013, Digium, Inc.
#

"""HTTP client tests
"""

import unittest

from twisted_ari.http_client import Request

class RequestTest(unittest.TestCase):
    """
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



if __name__ == '__main__':
    unittest.main()

