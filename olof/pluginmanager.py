#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles the loading, unloading and dynamically reloading of plugins and their dependencies.
"""

import imp
import os
import sys
import traceback

import pyinotify
from pyinotify import WatchManager, Notifier, ThreadedNotifier, EventsCodes, ProcessEvent

from twisted.internet import reactor

class PluginManager(object):
    """
    Class that represents the plugin manager.
    """
    def __init__(self, server):
        """
        Initialisation.

        @param   server (Olof)   Reference to main Olof server instance.
        """
        self.server = server

        self.plugin_dirs = ['olof/plugins']

        self.plugins = {}
        self.plugins_with_errors = {}

        self.loadAllPlugins()

        wm = WatchManager()
        wm.add_watch('olof/plugins/', pyinotify.ALL_EVENTS)
        self.inotifier = ThreadedNotifier(wm, self.processINotify)
        self.inotifier.start()

    def processINotify(self, event):
        """
        Process an INotify event, unloading and reloading plugins when applicable.
        """
        if not event.name.startswith('.') and event.name.endswith('.py'):
            if event.mask == pyinotify.IN_CLOSE_WRITE:
                self.unloadPlugin(event.name.rstrip('.py'))
                self.loadPlugin(event.pathname)
            elif event.mask == pyinotify.IN_DELETE:
                self.unloadPlugin(event.name.rstrip('.py'))

    def loadPlugin(self, path):
        """
        Load a plugin.

        @param   path (str)   Path of the Python file of the plugin.
        """
        name = os.path.basename(path)[:-3]
        try:
            plugin = imp.load_source(name, path).Plugin(self.server)
            if not plugin.isEnabled():
                return
            plugin.filename = name
        except Exception, e:
            self.plugins_with_errors[name] = (e, traceback.format_exc())
            self.server.output("Error while loading plugin %s: %s" % (name, e), sys.stderr)
        else:
            self.server.output("Loaded plugin: %s" % name)
            self.plugins[name] = plugin

    def loadAllPlugins(self):
        """
        Load all the plugins. Called automatically on initialisation.
        """
        home = os.getcwd()

        for path in self.plugin_dirs:
            for filename in os.listdir(path):
                if filename.endswith('.py') and not filename == '__init__.py':
                    self.loadPlugin(os.path.join(home, path, filename))

    def unload(self):
        """
        Unload the plugin manager and all plugins.
        """
        self.inotifier.stop()
        self.unloadAllPlugins()

    def unloadAllPlugins(self):
        """
        Unload all the plugins.
        """
        for p in self.plugins.values():
            p.unload()
            del(p)

    def unloadPlugin(self, name):
        """
        Unload the plugin with the given name.

        @param   name (str)   Name of the plugin to unload. This is the filename, without the trailing '.py'.
        """
        p = self.getPlugin(name)
        if p != None:
            self.server.output('Unloaded plugin: %s' % p.filename)
            p.unload()
            del(self.plugins[name])

    def getPlugin(self, name):
        """
        Get the plugin with the given name.

        @param    name (str)           Name of the plugin. This is the filename, without the trailing '.py'.
        @return   (olof.core.Plugin)   The Plugin with given name, None if none exists with such a name.
        """
        return self.plugins.get(name, None)

    def getPlugins(self):
        """
        Get a list of all loaded plugins.

        @return   (list(olof.core.Plugin))   A List of all loaded plugins
        """
        return self.plugins.values()
