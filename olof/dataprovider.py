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
import cPickle as pickle
import imp
import os
import time

import olof.datatypes

class DataProvider(object):
    """
    Class that defines the DataProvider.
    """
    def __init__(self, server):
        """
        Initialisation.

        Read previous pickled data and start looping calls that read new Location and Project data every 10 seconds.

        @param   server (Olof)   Reference to the main Olof server instance.
        """
        self.server = server

        self.projects = {}
        self.locations = {}
        if os.path.isfile("olof/data/data.pickle"):
            f = open("olof/data/data.pickle", "rb")
            self.locations = pickle.load(f)
            f.close()

        t = task.LoopingCall(self.readLocations)
        t.start(10, now=False)

        self.readProjects()
        t = task.LoopingCall(self.readProjects)
        t.start(10, now=False)

    def unload(self):
        """
        Unload this data provider. Saves the current location data to disk.
        """
        f = open("olof/data/data.pickle", "wb")
        pickle.dump(self.locations, f)
        f.close()

    def readLocations(self):
        """
        Read Location data from disk, this is the 'locations' variable of /olof/data/data.py.
        Parse and save the new information.
        """
        self.new_locations = imp.load_source('l', os.getcwd() + "/olof/data/data.py").locations
        self.parseLocations(self.new_locations)
        self.locations = copy.deepcopy(self.new_locations)

    def readProjects(self):
        """
        Read Project information from this, this is the 'projects' variable of /olof/data/data.py.
        Save the new information.
        """
        self.new_projects = imp.load_source('l', os.getcwd() + "/olof/data/data.py").projects
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
        elif (hostname in self.locations) and (self.locations[hostname].is_active(plugin, timestamp)):
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
                for p in self.server.plugins:
                    if scannerobj.is_active(p.filename):
                        p.locationUpdate(scannerobj.name, 'scanner', scannerobj)

                # Push sensor updates
                for sensor in scannerobj.sensors.values():
                    for p in self.server.plugins:
                        if scannerobj.is_active(p.filename):
                            p.locationUpdate(scannerobj.name, 'sensor', sensor)

        for scanner in self.locations:
            if scanner not in locations:
                # Removed scanner
                pass # Nothing should happen
