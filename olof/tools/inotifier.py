#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Provide an easy wrapper for listening to INotify kernel events.
"""

import os

import pyinotify
from pyinotify import WatchManager, Notifier, ThreadedNotifier, EventsCodes, ProcessEvent

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
