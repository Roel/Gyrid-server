#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

from twisted.internet import reactor, task, threads

import copy
import cPickle as pickle
import imp
import os
import time

class Project:
    Active, Plugins, Start, End = range(4)

class Location:
    ID, X, Y, Description, Sensors, Sensor, Times, \
    TimeInstall, TimeUninstall, Project = range(10)

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
        to_update = set()
        #locationUpdate(self, hostname, module, timestamp, id, description, coordinates)

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
        
        for scanner in self.locations:
            if scanner not in locations:
                # Removed scanner
                pass # Nothing should happen

    def parseLocations_old(self, locations):
        to_update = set()

        for scanner in locations:
            update = False
            for attr in locations[scanner]:
                if scanner in self.locations \
                   and attr in self.locations[scanner] \
                   and locations[scanner][attr] == self.locations[scanner][attr]:
                    pass
                else:
                    update = True

            if update:
                to_update.add(scanner)

        for scanner in self.locations:
            update = False
            for attr in self.locations[scanner]:
                if scanner in locations \
                   and attr in locations[scanner] \
                   and locations[scanner][attr] == self.locations[scanner][attr]:
                    pass
                else:
                    update = True

            if update:
               to_update.add(scanner)

        for scanner in to_update:
            if scanner in locations:
                self.pushLocationUpdate(scanner, locations[scanner])
            else:
                self.pushLocationUpdate(scanner, None)

    def pushLocationUpdate(self, hostname, location):
        if location == None:
            return

        args = {'hostname': str(hostname),
                'id': str(location[Location.ID]),
                'description': str(location[Location.Description]),
                'coordinates': (float(location[Location.X]),
                                float(location[Location.Y]))}

        if Location.TimeInstall in location[Location.Times]:
            args['timestamp'] = float(time.strftime('%s', time.strptime(
                location[Location.Times][Location.TimeInstall],
                '%Y%m%d-%H%M%S-%Z')))

            # Push scanner update
            args['module'] = 'scanner'
            if hostname not in self.locations or \
                False in [self.locations[hostname][i] == location[i] for i in [
                Location.ID, Location.Description, Location.X, Location.Y, Location.Times] \
                if hostname in self.locations]:
                for p in self.server.plugins:
                    p.locationUpdate(**args)

            # Push sensor updates
            for s in location[Location.Sensors]:
                args['module'] = s if s != Location.Sensor else 'sensor'
                if hostname not in self.locations or \
                    s not in self.locations[hostname][Location.Sensors] or \
                    False in [self.locations[hostname][Location.Sensors][s][i] == \
                        location[Location.Sensors][s][i] for i in [
                            Location.X, Location.Y]]:
                    for p in self.server.plugins:
                        p.locationUpdate(**args)

        if Location.TimeUninstall in location[Location.Times]:
            args['timestamp'] = float(time.strftime('%s', time.strptime(
                location[Location.Times][Location.TimeUninstall],
                '%Y%m%d-%H%M%S-%Z')))
            args['coordinates'] = None

            # Push scanner update
            args['module'] = 'scanner'
            for p in self.server.plugins:
                p.locationUpdate(**args)

            # Push sensor updates
            for s in location[Location.Sensors]:
                args['module'] = s if s != Location.Sensor else 'sensor'
                for p in self.server.plugins:
                    p.locationUpdate(**args)
