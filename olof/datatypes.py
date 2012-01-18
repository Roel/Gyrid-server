#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

import time

server = None

def unixtime(timestamp, format='%Y%m%d-%H%M%S-%Z'):
    return time.mktime(time.strptime(timestamp, format))

class Location(object):
    def __init__(self, name, id, lat, lon):
        self.name = name
        self.id = id
        self.description = None
        self.lat = lat
        self.lon = lon

        self.project = None
        self.sensors = {}

    def add_sensor(self, sensor):
        if not sensor.mac in self.sensors:
            self.sensors[sensor.mac] = sensor
            sensor.location = self
            if sensor.lat == None or sensor.lon == None:
                sensor.lat = self.lat
                sensor.lon = self.lon

    def is_active(self, plugin):
        if self.project == None:
            return False
        elif self.project.is_active and (plugin not in self.project.disabled_plugins):
            return True
        else:
            return False

    def compare(self, location):
        if False in [self.__dict__[i] == location.__dict__[i] for i in [
            'id', 'description', 'lat', 'lon']]:
            # Something changed in the scanner details

            # Push scanner update
            for p in server.plugins:
                if location.is_active(p.filename):
                    p.locationUpdate(location.name, 'scanner', location)

            # Push sensor updates
            for sensor in location.sensors.values():
                for p in server.plugins:
                    if location.is_active(p.filename):
                        p.locationUpdate(location.name, 'sensor', sensor)

        else:
            # Scanner details identical, compare sensors
            update = False

            for sensor in self.sensors:
                if sensor in location.sensors:
                    if not self.sensors[sensor] == location.sensors[sensor]:
                        update = True
                else:
                    update = True

            for sensor in location.sensors:
                if sensor in self.sensors:
                    if not self.sensors[sensor] == location.sensors[sensor]:
                        update = True
                else:
                    update = True

            if update:
                # Push scanner update
                for p in server.plugins:
                    if location.is_active(p.filename):
                        p.locationUpdate(location.name, 'scanner', location)

                # Push sensor updates
                for sensor in location.sensors.values():
                    for p in server.plugins:
                        if location.is_active(p.filename):
                            p.locationUpdate(location.name, 'sensor', sensor)

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.location = None
        self.lat = None
        self.lon = None

        self.start = None
        self.end = None

    def __eq__(self, sensor):
        return False not in [self.__dict__[i] == sensor.__dict__[i] for i in [
            'mac', 'lat', 'lon', 'start', 'end']]

class Project(object):
    def __init__(self, name):
        self.name = name

        self.active = True
        self.disabled_plugins = []

        self.locations = {}

        self.start = None
        self.end = None

    def is_active(self):
        if self.active == False:
            return False

        elif self.active == True:
            now = int(time.time())

            if self.start != None and self.end == None:
                return now >= self.start
            elif self.start == None and self.end != None:
                return now < self.end
            elif self.start != None and self.end != None:
                if self.end <= self.start:
                    raise ValueError("Start should predate end.")
                return self.start <= now < self.end
            else:
                return True

    def add_location(self, location):
        self.locations[location.name] = location
        location.project = self
