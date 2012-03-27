#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides a few useful classes for use in plugins or the server.
"""

import os

from twisted.internet import threads

import pyinotify
from pyinotify import WatchManager, Notifier, ThreadedNotifier, EventsCodes, ProcessEvent

import urllib2
import urlparse

class INotifier(object):
    """
    Class providing an easy wrapper for listing to INotify kernel events.
    """
    Write, Delete = range(2)

    def __init__(self, path):
        """
        Initialisation.

        @param   path (str)   Full path to watch.
        """
        self.path = path

        if os.path.isdir(self.path):
            self.path_dir = self.path
            self.path_file = None
        else:
            self.path_dir = os.path.dirname(self.path)
            self.path_file = os.path.basename(self.path)

        self.callbacks = {}

        wm = WatchManager()
        wm.add_watch(self.path_dir, pyinotify.ALL_EVENTS)
        self.inotifier = ThreadedNotifier(wm, self.__processINotify)
        self.inotifier.start()

    def __del__(self):
        """
        Destruction. Unload (i.e. stop) the inotifier.
        """
        self.unload()

    def unload(self):
        """
        Call this to stop listening for events. Should be called on shutdown.
        """
        self.inotifier.stop()

    def __processINotify(self, event):
        """
        Called when an INotify was received. Call the applicable callback method based on the event type.
        """
        if event.mask == pyinotify.IN_DELETE:
            if self.path_file == None or (self.path_file and event.name == self.path_file):
                for c in self.__getCallbacks(INotifier.Delete):
                    c(event)
        elif event.mask == pyinotify.IN_CLOSE_WRITE:
            if self.path_file == None or (self.path_file and event.name == self.path_file):
                for c in self.__getCallbacks(INotifier.Write):
                    c(event)

    def __getCallbacks(self, type):
        """
        Get the current callback methods for the given type.

        @param   type (INotifier.Write or INotifier.Delete)   Type of callback get.
        """
        return self.callbacks.get(type, [])

    def addCallback(self, type, callback):
        """
        Add a callback function to handle an event.

        @param   type (INotifier.Write or INotifier.Delete)   Type of callback to add. Write is called on file writes,
                                                                Delete on file deletion.
        @param   callback (method)                            Method to call, should accept one parameter: the pyinotify
                                                                event.
        """
        if not type in self.callbacks:
            self.callbacks[type] = set()
        self.callbacks[type].add(callback)

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
    def __init__(self, base_url, timeout=40, username=None, password=None, authHandler=None):
        """
        Initialisation. Username, password and authHandler are optional, but depend on each other.

        @param   base_url (str)   The base URL to connect to.
        @param   timeout (int)    The timeout of the connection, in seconds. Defaults to 40.
        @param   username (str)   The username to log in. Optional.
        @param   password (str)   The password to log in. Optional.
        @param   authHandler      A urllib2 authenication handler object. Optional.
        """
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
