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
            self.unloadPlugin(event.name.rstrip('.py'), dynamic=True)
            self.loadPlugin(event.pathname, dynamic=True)

    def __processINotifyDelete(self, event):
        """
        Process an INotify Delete event, unloading plugins when applicable.
        """
        if not event.name.startswith('.') and event.name.endswith('.py') and not event.name == '__init__.py':
            self.unloadPlugin(event.name.rstrip('.py'), dynamic=True)

    def loadPlugin(self, path, dynamic=False):
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
            elif dynamic and 'DYNAMIC_LOADING' in pluginModule.__dict__ and pluginModule.DYNAMIC_LOADING == False:
                return
            else:
                plugin = pluginModule.Plugin(self.server, name)
                plugin.dynamicLoading = not ('DYNAMIC_LOADING' in pluginModule.__dict__ and \
                    pluginModule.DYNAMIC_LOADING == False)
        except Exception as e:
            self.server.logger.logException(e, "Failed to load plugin %s" % name)
        else:
            self.server.logger.logInfo("Loaded plugin: %s" % name)
            self.plugins[name] = plugin

    def loadAllPlugins(self, dynamic=False):
        """
        Load all the plugins. Called automatically on initialisation.
        """
        home = os.getcwd()

        for path in self.plugin_dirs:
            for filename in os.listdir(path):
                if filename.endswith('.py') and not filename == '__init__.py':
                    self.loadPlugin(os.path.join(home, path, filename), dynamic)

    def unload(self, shutdown=False):
        """
        Unload the plugin manager and all plugins.

        @param   shutdown (bool)   True if the server is shutting down, else False.
        """
        self.inotifier.unload()
        self.unloadAllPlugins(shutdown)

    def unloadAllPlugins(self, shutdown=False, dynamic=False):
        """
        Unload all the plugins.

        @param   shutdown (bool)   True if the server is shutting down, else False.
        """
        for p in self.plugins.values():
            if not (dynamic and not p.dynamicLoading):
                self.server.logger.logInfo('Unloaded plugin: %s' % p.filename)
                p.unload(shutdown)
                del(p)

    def unloadPlugin(self, name, dynamic=False):
        """
        Unload the plugin with the given name.

        @param    name (str)   Name of the plugin to unload. This is the filename, without the trailing '.py'.
        @return   (bool)       Whether the plugin was unloaded.
        """
        p = self.getPlugin(name)
        if p != None and not (dynamic and not p.dynamicLoading):
            self.server.logger.logInfo('Unloaded plugin: %s' % p.filename)
            p.unload()
            del(self.plugins[name])
            del(sys.modules[p.__module__])

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
