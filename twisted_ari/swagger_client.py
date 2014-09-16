"""Asynchronous client for swaggerpy

Copyright (c) 2014, Matthew Jordan
Matthew Jordan <mjordan@digium.com>

This program is free software, distributed under the terms of
the MIT License (MIT)

This module provides an asynchronous client for SwaggerPy. The normal
SwaggerClient - unfortunately - assumes that the HTTP client is synchronous,
as it loads all resources in its constructor. This is especially odd
given that the http_client is pluggable... but Loader assumes that all
http_client instances return an object from the requests library.
Refactoring this is not an easy task without breaking existing consumers.

We work around this in this module by querying for the resources
asynchronously using our asynchronous HTTP client, storing them to a file,
then processing things in the SwaggerClient. Our asynchronous Swagger client
does not inherit from SwaggerClient; rather, it encapsulates it.
"""

import urlparse
import json
import logging
import tempfile
import shutil
import os

from swaggerpy.client import SwaggerClient
from twisted.python.failure import Failure
from twisted.internet.defer import Deferred, DeferredList
from twisted.internet.protocol import Protocol

LOGGER = logging.getLogger(__name__)

class JSONBodyReceiver(Protocol):

    def __init__(self, finished_deferred):
        self.finished_deferred = finished_deferred
        self.received = ""

    def dataReceived(self, bytes):
        self.received += bytes

    def connectionLost(self, reason):
        try:
            json_body = json.loads(self.received)
            self.finished_deferred.callback(json_body)
        except ValueError as value_error:
            self.finished_deferred.errback(value_error)

class AsyncSwaggerClient(object):


    def __init__(self, base_url):
        self._swagger_client = None
        self._base_url = base_url

        self._temp_dir = tempfile.mkdtemp()
        os.mkdir(os.path.join(self._temp_dir, 'api-docs'))

    def load_resources(self, http_client):
        """Load the resources for this Swagger client

        This routine will load the resources located at base_url. It does this
        in the following way:
        (1) Retrieve resources.json, saving it to a temporary file
        (2) For each API in resources.json, retrieve the API and save it to a
            temporary file.
        (3) If all succeed, pass the resource files to the underlying SwaggerPy
            client

        Args:
        http_client: The twisted HTTP client to use to get the resources

        Returns:
        A twisted.internet.defer.Deferred that is called on success or failure
        """

        def write_resource_file(json_body):
            """Writes a Swagger resource out to disk

            Args:
            json_body: The JSON representation of the resource
            """
            if 'basePath' in json_body:
                json_body['basePath'] = 'file:///{0}'.format(self._temp_dir)
            if 'resourcePath' in json_body:
                api_file = str(json_body['resourcePath'])
                api_file = api_file.replace('{format}', 'json')
                api_file.strip('/')
                full_path = '{}/{}'.format(self._temp_dir, api_file)
            else:
                full_path = '{}/{}'.format(self._temp_dir, 'resources.json')
            with open(full_path, 'w') as resource_file:
                resource_file.write(json.dumps(json_body))

        def create_http_failure(url, response):
            """Create a twisted.python.failure.Failure from a bad HTTP response

            Args:
            url: The url that failed
            response: The twisted.web.client.Response object

            Returns:
            A twisted.python.failure.Failure representing the failure
            """
            msg = 'While requesting {0}: {1} - {2}'.format(url,
                response.code,
                response.phrase)
            fail = Failure(Exception(msg))
            return fail        

        url = urlparse.urljoin(self._base_url, "ari/api-docs/resources.json")
        resource_finished = Deferred()

        def on_error(failure):
            """Generic deferred error callback

            This ensures that our top most deferred gets called if any nested
            deferred errors out

            Args:
            failure: The twisted.python.failure.Failure object

            Returns:
            failure
            """
            shutil.rmtree(self._temp_dir)
            resource_finished.errback(failure)
            return failure

        def on_resource_finished(response):
            """Success callback for when resources.json is parsed

            Args:
            response: The twisted.web.client.Response for the HTTP request

            Returns:
            response if the request was successful
            A twisted.python.failure.Failure object if the request failed
            """

            if response.code / 100 != 2:
                fail = self._create_http_failure(url, response)
                resource_finished.errback(fail)
                return fail

            finished_deferred = Deferred()

            def on_resource_body_read(resource_json_body):
                """Success callback for reading the body of resources.json

                Args:
                resource_json_body: The JSON body of resources.json

                Returns:
                A twisted.internet.defer.Deferred that is fired when all API
                    resources are processed on success
                A twisted.python.failure.Failure on error
                """

                write_resource_file(resource_json_body)

                def on_api_finished(response, url):
                    """Success callback when an API response is received

                    Args:
                    response: The twisted.web.client.Response for the HTTP
                              request
                    url: The url for this API request

                    Returns:
                    A twisted.internet.defer.Deferred that is fired when the API
                        body is processed
                    A twisted.python.failure.Failure on error
                    """

                    if response.code / 100 != 2:
                        return self._create_http_failure(url, response)

                    api_finished_deferred = Deferred()

                    def on_api_body_read(api_json_body):
                        """Success callback for reading the body of an API

                        Args:
                        api_json_body: The JSON body for the API

                        Returns:
                        api_json_body
                        """
                        write_resource_file(api_json_body)
                        return api_json_body

                    api_finished_deferred.addCallbacks(on_api_body_read,
                        on_error)
                    response.deliverBody(JSONBodyReceiver(api_finished_deferred))
                    return api_finished_deferred

                api_deferreds = []

                for api in resource_json_body.get('apis'):
                    path = api.get('path').replace('{format}', 'json')
                    api_url = urlparse.urljoin(self._base_url + '/', 'ari')
                    api_url = urlparse.urljoin(api_url + '/', path.strip('/'))
                    try:
                        api_deferred = http_client.request('GET', api_url)
                        api_deferred.addCallback(on_api_finished, api_url)
                        api_deferred.addErrback(on_error)
                        api_deferreds.append(api_deferred)
                    except Exception as e:
                        fail = Failure(e)
                        resource_finished.errback(fail)
                        return fail

                def apis_processed(results):
                    """Callback called when all API resources are processed

                    Args:
                    results: The list of (success, result) tuples returned from
                        the API request callbacks

                    Returns:
                    results on success
                    twisted.python.failure.Failure on error
                    """
                    if any([result for result in results if not result[0]]):
                        msg = "Failed to process all API resources"
                        fail = Failure(Exception(msg))
                        finished_deferred.errback(fail)
                        return fail
                    resource_finished.callback(None)
                    return results

                apis_finished = DeferredList(api_deferreds)
                apis_finished.addCallback(apis_processed)
                return apis_finished

            finished_deferred.addCallbacks(on_resource_body_read, on_error)
            response.deliverBody(JSONBodyReceiver(finished_deferred))
            return finished_deferred

        http_client.request('GET', url).addCallbacks(on_resource_finished,
            on_error)

        def on_resources_finished(result):
            resource_file = 'file://{}/resources.json'.format(self._temp_dir)
            self._swagger_client = SwaggerClient(resource_file)
            print self._swagger_client
            shutil.rmtree(self._temp_dir)
            print "NIFTY"

        resource_finished.addCallback(on_resources_finished)
        return resource_finished

    def __repr__(self):
        return self._swagger_client.__repr__()

    def __getattr__(self, item):
        """Promote resource objects to be client fields.

        :param item: Name of the attribute to get.
        :return: Resource object.
        """
        return self._swagger_client.__getattr__(item)

    def close(self):
        """Close the SwaggerClient, and underlying resources.
        """
        self._swagger_client.close()

    def get_resource(self, name):
        """Gets a Swagger resource by name.

        :param name: Name of the resource to get
        :rtype: Resource
        :return: Resource, or None if not found.
        """
        return self._swagger_client.resources.get(name)
