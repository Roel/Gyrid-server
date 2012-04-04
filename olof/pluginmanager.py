#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles the loading, unloading and dynamically reloading of plugins.
"""

import imp
import os
import pyinotify
import random
import sys
import traceback

from olof.tools.inotifier import INotifier

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
        self.loadAllPlugins()

        self.inotifier = INotifier('olof/plugins')
        self.inotifier.addCallback(INotifier.Write, self.__processINotifyWrite)
        self.inotifier.addCallback(INotifier.Delete, self.__processINotifyDelete)

    def __processINotifyWrite(self, event):
        """
        Process an INotify Write event, reloading plugins when applicable.
        """
        if not event.name.startswith('.') and event.name.endswith('.py') and not event.name == '__init__.py':
            self.unloadPlugin(event.name.rstrip('.py'))
            self.loadPlugin(event.pathname)

    def __processINotifyDelete(self, event):
        """
        Process an INotify Delete event, unloading plugins when applicable.
        """
        if not event.name.startswith('.') and event.name.endswith('.py') and not event.name == '__init__.py':
            self.unloadPlugin(event.name.rstrip('.py'))

    def loadPlugin(self, path):
        """
        Load a plugin.

        @param   path (str)   Path of the Python file of the plugin.
        """
        name = os.path.basename(path)[:-3]
        try:
            r = str(random.random())
            pluginModule = imp.load_source('dynamic-plugin-module-' + r[r.find('.')+1:], path)
            if 'ENABLED' in pluginModule.__dict__ and pluginModule.ENABLED == False:
                return
            else:
                plugin = pluginModule.Plugin(self.server, name)
        except Exception, e:
            self.server.logger.logError("Error while loading plugin %s: %s" % (name, e))
            self.server.logger.logError(traceback.format_exc())
        else:
            self.server.logger.logInfo("Loaded plugin: %s" % name)
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

    def unload(self, shutdown=False):
        """
        Unload the plugin manager and all plugins.

        @param   shutdown (bool)   True if the server is shutting down, else False.
        """
        self.inotifier.unload()
        self.unloadAllPlugins(shutdown)

    def unloadAllPlugins(self, shutdown=False):
        """
        Unload all the plugins.

        @param   shutdown (bool)   True if the server is shutting down, else False.
        """
        for p in self.plugins.values():
            p.unload(shutdown)
            del(p)

    def unloadPlugin(self, name):
        """
        Unload the plugin with the given name.

        @param   name (str)   Name of the plugin to unload. This is the filename, without the trailing '.py'.
        """
        p = self.getPlugin(name)
        if p != None:
            self.server.logger.logInfo('Unloaded plugin: %s' % p.filename)
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
