#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

from twisted.internet import reactor, task, threads

import copy
import cPickle as pickle
import imp
import os
import time

import olof.datatypes

class DataProvider(object):
    def __init__(self, server):
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
        f = open("olof/data/data.pickle", "wb")
        pickle.dump(self.locations, f)
        f.close()

    def readLocations(self):
        self.new_locations = imp.load_source('l', os.getcwd() + "/olof/data/data.py").locations
        self.parseLocations(self.new_locations)
        self.locations = copy.deepcopy(self.new_locations)

    def readProjects(self):
        self.new_projects = imp.load_source('l', os.getcwd() + "/olof/data/data.py").projects
        self.projects = copy.deepcopy(self.new_projects)

    def getProjectName(self, hostname):
        if hostname in self.locations:
            return self.locations[hostname].project.name
        else:
            return None

    def isActive(self, hostname, plugin):
        if plugin in olof.datatypes.ENABLED_PLUGINS:
            return True
        elif (hostname in self.locations) and (self.locations[hostname].is_active(plugin)):
            return True
        else:
            return False

    def parseLocations(self, locations):
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
