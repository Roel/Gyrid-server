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

        self.plugins = []
        self.plugins_inactive = []
        self.plugins_with_errors = {}

        self.loadPlugins()

    def loadPlugins(self):
        """
        Load the plugins. Called automatically on initialisation.
        """
        def load(filename, list):
            name = os.path.basename(filename)[:-3]
            try:
                plugin = imp.load_source(name, filename).Plugin(self.server)
                plugin.filename = name
            except Exception, e:
                self.plugins_with_errors[name] = (e, traceback.format_exc())
                sys.stderr.write("Error while loading plugin %s: %s\n" % (name, e))
                traceback.print_exc()
            else:
                self.server.output("Loaded plugin: %s" % name)
                list.append(plugin)

        home = os.getcwd()

        filenames = []
        for filename in os.listdir(os.path.join(home, 'olof', 'plugins')):
            if filename.endswith('.py') and not filename.startswith('_'):
                load(os.path.join(home, 'olof', 'plugins', filename), self.plugins)
            elif filename.endswith('.py') and not filename.startswith('__'):
                load(os.path.join(home, 'olof', 'plugins', filename), self.plugins_inactive)

    def unload(self):
        """
        Unload the plugin manager and all plugins.
        """
        self.unloadPlugins()

    def unloadPlugins(self):
        """
        Unload all the plugins.
        """
        for p in self.plugins:
            p.unload()

    def getPlugins(self):
        """
        Get a list of all loaded plugins.

        @return   (list(olof.core.Plugin))   A List of all loaded plugins
        """
        return self.plugins
