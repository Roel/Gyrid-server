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

    def parseLocations(self, locations):
        for scanner in locations:
            if scanner in self.locations:
                # Existing scanner
                self.locations[scanner].compare(locations[scanner])
            else:
                # New scanner
                scannerobj = locations[scanner]
                args = {'hostname': str(scannerobj.name),
                        'id': str(scannerobj.id),
                        'description': str(scannerobj.description)}

                if None not in [scannerobj.lon, scannerobj.lat] and scannerobj.sensors.values()[0].start != None:
                    args['coordinates'] = (float(scannerobj.lon), float(scannerobj.lat))
                    args['timestamp'] = scannerobj.sensors.values()[0].start
                elif None in [scannerobj.lon, scannerobj.lat] or scannerobj.sensors.values()[0].end != None:
                    args['coordinates'] = None
                    args['timestamp'] = scannerobj.sensors.values()[0].end

                # Push scanner update
                args['module'] = 'scanner'
                print "LU 1"
                for p in self.server.plugins:
                    p.locationUpdate(**args)
                    p.newLocationUpdate(scannerobj.name, 'scanner', scannerobj)

                # Push sensor updates
                for sensor in scannerobj.sensors.values():
                    args['module'] = str(sensor.mac)
                    if None in [sensor.lat, sensor.lon]:
                        args['coordinates'] = None
                    else:
                        args['coordinates'] = (float(sensor.lon), float(sensor.lat))
                    print "LU 2"
                    for p in self.server.plugins:
                        p.locationUpdate(**args)
                        p.newLocationUpdate(scannerobj.name, 'sensor', sensor)

        for scanner in self.locations:
            if scanner not in locations:
                # Removed scanner
                pass # Nothing should happen
