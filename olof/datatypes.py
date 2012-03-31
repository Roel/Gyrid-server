#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that defines the datatypes that can be used in data/data.py to define
scanner setups at specific projects, times and locations.
"""

import time

# A reference to the main Olof server object. This reference is made at runtime.
server = None

# Plugins that cannot be disabled by the user in data/data.py
ENABLED_PLUGINS = ['debug', 'status']

def unixtime(timestamp, format='%Y%m%d-%H%M%S-%Z'):
    """
    Convert the given timestamp to UNIX time.

    @param   timestamp (str)   The timestamp to convert.
    @param   format (str)      The format of the timestamp.
    @return  (float)           The equivalent UNIX time of the given timestamp.
    """
    return time.mktime(time.strptime(timestamp, format))

class Location(object):
    """
    Class that represents a location, meaning a scanner at a specific
    geographic location.
    """
    def __init__(self, id, name=None, lat=None, lon=None):
        """
        Initialisation.

        @param   id (str)      The id of the location, i.e. the hostname of the scanner. Unique among Locations.
        @param   name (str)    The name of the location, a short description of the geographical location of the
                                 scanner. Unique among Locations.
        @param   lat (float)   The geographical latitude coördinate in WGS84.
        @param   lon (float)   The geographical longitude coördinate in WGS84.
        """
        self.id = id
        self.name = name
        self.description = None
        self.lat = lat
        self.lon = lon

        self.project = None
        self.sensors = {}

    def addSensor(self, sensor):
        """
        Add a Bluetooth sensor to this location.

        @param   sensor (Sensor)   The Sensor object to add.
        """
        if not sensor.mac in self.sensors:
            self.sensors[sensor.mac] = sensor
            sensor.location = self
            if sensor.lat == None or sensor.lon == None:
                sensor.lat = self.lat
                sensor.lon = self.lon

    def isActive(self, plugin, timestamp=None):
        """
        Check if the given plugin is active for this location at the given timestamp.

        @param   plugin (str)       The name of the plugin.
        @param   timestamp (float)  The timestamp to check in UNIX time.
        @return  (bool)             True if the plugin is active at the given time, else False.
        """
        if timestamp == None:
            timestamp = int(time.time())
        if plugin in ENABLED_PLUGINS:
            return True
        elif self.project == None:
            return False
        elif self.project.isActive(timestamp) and (plugin not in self.project.disabled_plugins):
            return True
        else:
            return False

    def compare(self, location):
        """
        Compare the given Location object to this location. This is used to compare a new instance of the same location
        and push out locationUpdate signals when changes are detected.

        @param   location (Location)   The Location object to compare.
        """
        if False in [self.__dict__[i] == location.__dict__[i] for i in [
            'name', 'description', 'lat', 'lon']]:
            # Something changed in the scanner details

            # Push scanner update
            for p in server.pluginmgr.getPlugins():
                if location.isActive(p.filename):
                    p.locationUpdate(location.id, 'scanner', location)

            # Push sensor updates
            for sensor in location.sensors.values():
                for p in server.pluginmgr.getPlugins():
                    if location.isActive(p.filename):
                        p.locationUpdate(location.id, 'sensor', sensor)

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
                for p in server.pluginmgr.getPlugins():
                    if location.isActive(p.filename):
                        p.locationUpdate(location.id, 'scanner', location)

                # Push sensor updates
                for sensor in location.sensors.values():
                    for p in server.pluginmgr.getPlugins():
                        if location.isActive(p.filename):
                            p.locationUpdate(location.id, 'sensor', sensor)

class Sensor(object):
    """
    Class that represents a Bluetooth sensor.
    """
    def __init__(self, mac):
        """
        Initialisation.

        @param   mac (str)   The MAC-address of the Bluetooth sensor.
        """
        self.mac = mac
        self.location = None
        self.lat = None
        self.lon = None

        self.start = None
        self.end = None

    def __eq__(self, sensor):
        """
        Compare another Sensor object to this sensor.

        @return (bool)  True if all fields are equal, else False.
        """
        return False not in [self.__dict__[i] == sensor.__dict__[i] for i in [
            'mac', 'lat', 'lon', 'start', 'end']]

class Project(object):
    """
    Class that represents a project.
    """
    def __init__(self, name):
        """
        Initialisation.

        @param   name (str)   The name of the project.
        """
        self.name = name

        self.active = True
        self.disabled_plugins = []

        self.locations = {}

        self.start = None
        self.end = None

    def isActive(self, timestamp=None):
        """
        Check if the project is active at the given timestamp.

        @param   timestamp (float)   The timestamp to check, in UNIX time.
        @return  (bool)              True if the project is active, else False.
        """
        if self.active == False:
            return False

        elif self.active == True:
            if timestamp == None:
                timestamp = int(time.time())

            if self.start != None and self.end == None:
                return timestamp >= self.start
            elif self.start == None and self.end != None:
                return timestamp < self.end
            elif self.start != None and self.end != None:
                if self.end <= self.start:
                    raise ValueError("Start should predate end.")
                return self.start <= timestamp < self.end
            else:
                return True

    def addLocation(self, location):
        """
        Add a Location to this project.

        @param   location (Location)   The Location object to add.
        """
        self.locations[location.id] = location
        location.project = self
