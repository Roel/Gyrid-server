#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

import urllib2
import urlparse

class ExtRequest(urllib2.Request):
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

class RestConnection(object):
    def __init__(self, base_url, timeout=40, username=None, password=None, authHandler=None):
        self.base_url = base_url
        self.timeout = float(timeout)
        self.username = username
        self.url = urlparse.urlparse(base_url)

        if username and password and authHandler:
            passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
            passman.add_password(None, self.base_url, username, password)
            self.opener = urllib2.build_opener(authHandler(passman))
        else:
            self.opener = None

        self.returns = {}
        self.returnCount = 0

        (scheme, netloc, path, query, fragment) = urlparse.urlsplit(base_url)

        self.scheme = scheme
        self.host = netloc
        self.path = path

    def request_get(self, resource, cb=None, headers={}):
        self.request(cb, resource, "get", headers=headers)

    def request_delete(self, resource, cb=None, headers={}):
        self.request(cb, resource, "delete", headers=headers)

    def request_head(self, resource, cb=None, headers={}):
        self.request(cb, resource, "head", headers=headers)

    def request_post(self, resource, cb=None, body=None, headers={}):
        self.request(cb, resource, "post", body=body, headers=headers)

    def request_put(self, resource, cb=None, body=None, headers={}):
        self.request(cb, resource, "put", body=body, headers=headers)

    def request(self, callback, resource, method="get", body=None, headers={}):
        d = threads.deferToThread(self.__request, resource, method, body, headers)
        if callback != None:
            d.addCallback(callback)

    def __request(self, resource, method="get", body=None, headers={}):
        if resource.startswith('/'):
            req = ExtRequest(self.base_url+resource)
        else:
            req = ExtRequest(self.base_url+'/'+resource)

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

