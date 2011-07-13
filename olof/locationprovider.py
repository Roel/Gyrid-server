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

class Location:
    ID, X, Y, Description, Sensors, Sensor, Times, \
    TimeInstall, TimeUninstall = range(9)

class LocationProvider(object):
    def __init__(self, server):
        self.server = server

        self.locations = {}
        if os.path.isfile("olof/data/locations.pickle"):
            f = open("olof/data/locations.pickle", "rb")
            self.locations = pickle.load(f)
            f.close()

        self.task = task.LoopingCall(self.readLocations)
        self.task.start(10, now=False)

    def unload(self):
        f = open("olof/data/locations.pickle", "wb")
        pickle.dump(self.locations, f)
        f.close()

    def readLocations(self):
        self.new_locations = imp.load_source('l', os.getcwd() + "/olof/data/locations.py").locations
        self.parseLocations(self.new_locations)
        self.locations = copy.deepcopy(self.new_locations)

    def parseLocations(self, locations):
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
        self.server.output('locationprovider: push location update for %s' % hostname)
        #hostname, timestamp, id, description, coordinates
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
