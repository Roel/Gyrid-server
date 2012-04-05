#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that defines the DataProvider, which regularly reads new Location and Project data from disk and provides
this information to the server.
"""

from twisted.internet import reactor, task, threads

import copy
import imp
import os
import time

import olof.configuration
import olof.datatypes
import olof.storagemanager
from olof.tools.inotifier import INotifier

class DataProvider(object):
    """
    Class that defines the DataProvider.
    """
    def __init__(self, server):
        """
        Initialisation.

        Read previous saved data and initialise the data configuration file.

        @param   server (Olof)   Reference to the main Olof server instance.
        """
        self.server = server

        self.storagemgr = olof.storagemanager.StorageManager(self.server, 'data')
        self.locations = self.storagemgr.loadObject('locations', {})
        self.projects = {}

        self.dataconfig = olof.configuration.Configuration(self.server, 'data')
        self.defineConfiguration()

        self.readLocations()
        self.readProjects()

    def defineConfiguration(self):
        """
        Define the data configuration options.
        """
        def validate(value, datatype):
            if type(value) is not dict:
                raise olof.tools.validation.ValidationError()

            d = {}
            for i in value:
                if type(i) is str and type(value[i]) is datatype:
                    d[i] = value[i]
            return d

        o = olof.configuration.Option('projects')
        o.setDescription('Dictionary mapping project names to olof.datatypes.Project instances.')
        o.setValidation(validate, olof.datatypes.Project)
        o.addValue(olof.configuration.OptionValue({}, default=True))
        o.addCallback(self.readProjects)
        self.dataconfig.addOption(o)

        o = olof.configuration.Option('locations')
        o.setDescription('Dictionary mapping location id\'s to olof.datatypes.Location instances.')
        o.setValidation(validate, olof.datatypes.Location)
        o.addValue(olof.configuration.OptionValue({}, default=True))
        o.addCallback(self.readLocations)
        self.dataconfig.addOption(o)

        self.dataconfig.readConfig()

    def unload(self):
        """
        Unload this data provider. Saves the current location data to disk.
        """
        self.dataconfig.unload()
        self.storagemgr.storeObject(self.locations, 'locations')

    def readLocations(self, value=None):
        """
        Read Location data from disk, this is the 'locations' option in data.conf.py
        Parse and save the new information.
        """
        self.new_locations = value if value != None else self.dataconfig.getValue('locations')
        self.parseLocations(self.new_locations)
        self.locations = copy.deepcopy(self.new_locations)

    def readProjects(self, value=None):
        """
        Read Project information from this, this is the 'projects' option in data.conf.py
        Save the new information.
        """
        self.new_projects = value if value != None else self.dataconfig.getValue('projects')
        self.projects = copy.deepcopy(self.new_projects)

    def getProjectName(self, hostname):
        """
        Return the projectname for a given hostname.

        @param   hostname (str)   The hostname to check.
        @return  (str)            The name of the project the scanner with the given hostname belongs to. None when the
                                    scanner is not attached to a project.
        """
        if hostname in self.locations:
            return self.locations[hostname].project.name
        else:
            return None

    def isActive(self, hostname, plugin, timestamp=None):
        """
        Check if a plugin is active for a hostname at a given timestamp.

        @param   hostname (str)    The hostname to check.
        @param   plugin (str)      The name of the plugin to check.
        @param   timestamp (int)   The timestamp to check. Use the current time when None.
        @return  (bool)            True when the plugin is active, else False.
        """
        if timestamp == None:
            timestamp = int(time.time())

        if plugin in olof.datatypes.ENABLED_PLUGINS:
            return True
        elif (hostname in self.locations) and (self.locations[hostname].isActive(plugin, timestamp)):
            return True
        else:
            return False

    def parseLocations(self, locations):
        """
        Compare the given location data to the saved location data. Push out locationUpdate's when things have changed.

        @param   locations (dict)    New Location data.
        """
        for scanner in locations:
            if scanner in self.locations:
                # Existing scanner
                self.locations[scanner].compare(locations[scanner])
            else:
                # New scanner
                scannerobj = locations[scanner]
                for p in self.server.pluginmgr.getPlugins():
                    if scannerobj.isActive(p.filename):
                        p.locationUpdate(scannerobj.name, 'scanner', scannerobj)

                # Push sensor updates
                for sensor in scannerobj.sensors.values():
                    for p in self.server.pluginmgr.getPlugins():
                        if scannerobj.isActive(p.filename):
                            p.locationUpdate(scannerobj.name, 'sensor', sensor)

        for scanner in self.locations:
            if scanner not in locations:
                # Removed scanner
                pass # Nothing should happen
