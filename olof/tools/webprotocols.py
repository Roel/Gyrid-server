#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Provider implementations for different web protocols, currently only REST.
"""

from twisted.internet import threads

import urllib2
import urlparse

class ExtRequest(urllib2.Request):
    """
    Class that extends the default urllib2.Request.
    """
    method = None

    def set_method(self, method):
        self.method = method

    def get_method(self):
        if self.method is None:
            if self.has_data():
                return "POST"
            else:
                return "GET"
        else:
            return self.method

class RESTConnection(object):
    """
    Class that defines a REST connection.
    """
    def __init__(self, baseUrl, timeout=40, username=None, password=None, authHandler=None):
        """
        Initialisation. Username, password and authHandler are optional, but depend on each other.

        @param   baseUrl (str)    The base URL to connect to.
        @param   timeout (int)    The timeout of the connection, in seconds. Defaults to 40.
        @param   username (str)   The username to log in. Optional.
        @param   password (str)   The password to log in. Optional.
        @param   authHandler      A urllib2 authenication handler object. Optional.
        """
        self.baseUrl = baseUrl
        self.timeout = float(timeout)
        self.username = username
        self.url = urlparse.urlparse(baseUrl)

        if username and password and authHandler:
            passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
            passman.add_password(None, self.baseUrl, username, password)
            self.opener = urllib2.build_opener(authHandler(passman))
        else:
            self.opener = None

        self.returns = {}
        self.returnCount = 0

        (scheme, netloc, path, query, fragment) = urlparse.urlsplit(baseUrl)

        self.scheme = scheme
        self.host = netloc
        self.path = path

    def requestGet(self, resource, cb=None, headers={}):
        """
        Perform a GET request.

        @param   resource (str)   The resource to call.
        @param   cb (method)      A callback method to call when to request is done. Optional.
                                    This method should take one argument which will be the result of the request.
        @param   headers (dict)   Additional header to send with the request. Optional.
        """
        self.request(cb, resource, "get", headers=headers)

    def requestDelete(self, resource, cb=None, headers={}):
        """
        Perform a DELETE request.

        @param   resource (str)   The resource to call.
        @param   cb (method)      A callback method to call when to request is done. Optional.
                                    This method should take one argument which will be the result of the request.
        @param   headers (dict)   Additional header to send with the request. Optional.
        """
        self.request(cb, resource, "delete", headers=headers)

    def requestHead(self, resource, cb=None, headers={}):
        """
        Perform a HEAD request.

        @param   resource (str)   The resource to call.
        @param   cb (method)      A callback method to call when to request is done. Optional.
                                    This method should take one argument which will be the result of the request.
        @param   headers (dict)   Additional header to send with the request. Optional.
        """
        self.request(cb, resource, "head", headers=headers)

    def requestPost(self, resource, cb=None, body=None, headers={}):
        """
        Perform a POST request.

        @param   resource (str)   The resource to call.
        @param   cb (method)      A callback method to call when to request is done. Optional.
                                    This method should take one argument which will be the result of the request.
        @param   body (str)       The data to send with the request. Optional.
        @param   headers (dict)   Additional header to send with the request. Optional.
        """
        self.request(cb, resource, "post", body=body, headers=headers)

    def requestPut(self, resource, cb=None, body=None, headers={}):
        """
        Perform a PUT request.

        @param   resource (str)   The resource to call.
        @param   cb (method)      A callback method to call when to request is done. Optional.
                                    This method should take one argument which will be the result of the request.
        @param   body (str)       The data to send with the request. Optional.
        @param   headers (dict)   Additional header to send with the request. Optional.
        """
        self.request(cb, resource, "put", body=body, headers=headers)

    def request(self, callback, resource, method="get", body=None, headers={}):
        """
        Wrapper to perform a request with a callback. Should not be called directly.
        """
        d = threads.deferToThread(self.__request, resource, method, body, headers)
        if callback != None:
            d.addCallback(callback)

    def __request(self, resource, method="get", body=None, headers={}):
        """
        Perform the actual HTTP request. Should not be called directly.
        """
        if resource.startswith('/'):
            req = ExtRequest(self.baseUrl+resource)
        else:
            req = ExtRequest(self.baseUrl+'/'+resource)

        req.set_method(method.upper())
        req.add_data(body)
        for i in headers.iteritems():
            req.add_header(i[0],i[1])

        try:
            if self.opener:
                resp = self.opener.open(req, timeout=self.timeout)
            else:
                resp = urllib2.urlopen(req, timeout=self.timeout)
            return resp.readlines()
        except urllib2.HTTPError as e:
            return e
        except:
            return None
