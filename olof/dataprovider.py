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
from threading import Lock

import olof.configuration
import olof.datatypes
import olof.storagemanager
import olof.protocol.network as proto
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
        self.lock = Lock()

        self.storagemgr = olof.storagemanager.StorageManager(self.server, 'data')
        self.locations = self.storagemgr.loadObject('locations', {})
        self.scan_patterns = self.storagemgr.loadObject('scan_patterns', {})
        self.patterns_to_push = self.storagemgr.loadObject('patterns_to_push', {})

        self.storagemgr.repeatedStoreObject(self.locations, 'locations')
        self.storagemgr.repeatedStoreObject(self.scan_patterns, 'scan_patterns')
        self.storagemgr.repeatedStoreObject(self.patterns_to_push, 'patterns_to_push')

        self.projects = {}

        self.dataconfig = olof.configuration.Configuration(self.server, 'data')
        self.scanconfig = olof.configuration.Configuration(self.server, 'scan')
        self.defineConfiguration()

        self.readLocations()
        self.readProjects()
        self.readPatterns()

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

        o = olof.configuration.Option('scan_patterns')
        o.setDescription('Dictionary mapping hostnames to iterables of scan pattern dictionaries.')
        o.addValue(olof.configuration.OptionValue({}, default=True))
        o.addCallback(self.readPatterns)
        self.scanconfig.addOption(o)

        self.dataconfig.readConfig()
        self.scanconfig.readConfig()

    def unload(self):
        """
        Unload this data provider. Saves the current location data to disk.
        """
        self.dataconfig.unload()
        self.scanconfig.unload()
        self.storagemgr.unload()
        self.storagemgr.storeObject(self.locations, 'locations')
        self.storagemgr.storeObject(self.scan_patterns, 'scan_patterns')
        self.storagemgr.storeObject(self.patterns_to_push, 'patterns_to_push')

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

    def readPatterns(self, value=None):
        """
        Read pattern information from this, this is the 'scan_patterns' option in scan.conf.py
        Save the new information.
        """
        self.new_patterns = value if value != None else self.scanconfig.getValue('scan_patterns')
        self.parsePatterns(self.new_patterns)
        self.scan_patterns = copy.deepcopy(self.new_patterns)

    def isActive(self, hostname, plugin, projectname=None, timestamp=None):
        """
        Check if a plugin is active for a hostname at a given timestamp.

        @param   hostname (str)      The hostname to check.
        @param   plugin (str)        The name of the plugin to check.
        @param   projectname (str)   The name of the project to check.
        @param   timestamp (int)     The timestamp to check. Use the current time when None.
        @return  (bool)              True when the plugin is active, else False.
        """
        if timestamp == None:
            timestamp = int(time.time())

        if plugin in olof.datatypes.ENABLED_PLUGINS:
            return True
        elif (projectname != None) and (hostname in self.locations) and \
            (self.locations[hostname].isActive(self.projects[projectname], plugin, timestamp)):
            return True
        else:
            return False

    def getActivePlugins(self, hostname, timestamp=None):
        """
        Get the active plugins for the given hostname at the given timestamp.

        @param    hostname (str)    The hostname to check.
        @param    timestamp (int)   The UNIX timestamp to check.
        @return   (dict)            A dictionary mapping plugins to projects.
        """
        if hostname in self.locations:
            return self.locations[hostname].getActivePlugins(timestamp=timestamp)
        else:
            activePlugins = {}
            for plugin in self.server.pluginmgr.getPlugins():
                if self.isActive(hostname, plugin.filename, timestamp=timestamp):
                    activePlugins[plugin] = set([None])
            return activePlugins

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
                activePlugins = scannerobj.getActivePlugins()
                for plugin in activePlugins:
                    plugin.locationUpdate(scannerobj.id, activePlugins[plugin], 'scanner', scannerobj)

                # Push sensor updates
                for sensor in scannerobj.sensors.values():
                    for plugin in activePlugins:
                        plugin.locationUpdate(scannerobj.id, activePlugins[plugin], 'sensor', sensor)

        for scanner in self.locations:
            if scanner not in locations:
                # Removed scanner
                pass # Nothing should happen

    def getAllPatterns(self, scanner):
        r = []
        for p in self.scan_patterns.get(scanner, []):
            m = proto.Msg()
            m.type = m.Type_SCAN_PATTERN
            s = m.scanPattern
            s.action = s.Action_ADD
            for attr in p:
                s.__setattr__(attr, p[attr])
            r.append(m)
        return r

    def parsePatterns(self, patterns):
        def pushPattern(scanner, pattern):
            if scanner not in self.patterns_to_push:
                self.patterns_to_push[scanner] = []
            with self.lock:
                self.patterns_to_push[scanner].append(pattern)

        def removeAllPatterns(scanner):
            m = proto.Msg()
            m.type = m.Type_SCAN_PATTERN
            m.scanPattern.action = m.scanPattern.Action_REMOVEALL
            pushPattern(scanner, m)

        def addPattern(scanner, pattern):
            m = proto.Msg()
            m.type = m.Type_SCAN_PATTERN
            s = m.scanPattern
            s.action = s.Action_ADD
            for attr in pattern:
                s.__setattr__(attr, pattern[attr])
            pushPattern(scanner, m)

        def removePattern(scanner, pattern):
            m = proto.Msg()
            m.type = m.Type_SCAN_PATTERN
            s = m.scanPattern
            s.action = s.Action_REMOVE
            for attr in pattern:
                s.__setattr__(attr, pattern[attr])
            pushPattern(scanner, m)

        for scanner in patterns:
            if scanner in self.scan_patterns:
                # Existing scanner
                for p in patterns[scanner]:
                    if p not in self.scan_patterns[scanner]:
                        addPattern(scanner, p)

                for p in self.scan_patterns[scanner]:
                    if p not in patterns[scanner]:
                        removePattern(scanner, p)
            else:
                # New scanner
                for p in patterns[scanner]:
                    addPattern(scanner, p)

        for scanner in self.scan_patterns:
            if scanner not in patterns:
                # Removed scanner
                removeAllPatterns(scanner)
