#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that defines the datatypes that can be used in data.conf.py to define
scanner setups at specific projects, times and locations.
"""

import time

# A reference to the main Olof server object. This reference is made at runtime.
server = None

# Plugins that cannot be disabled by the user.
ENABLED_PLUGINS = ['dashboard', 'debug']

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

        self.projects = set()
        self.sensors = {}

    def addSensor(self, sensor):
        """
        Add a Bluetooth sensor to this location.

        @param   sensor (Sensor)   The Sensor object to add.
        """
        id = sensor.mac if sensor.mac != None else sensor.__hash__()
        if not id in self.sensors:
            self.sensors[id] = sensor
            sensor.location = self
            if sensor.lat == None or sensor.lon == None:
                sensor.lat = self.lat
                sensor.lon = self.lon

    def addSensors(self, sensors):
        """
        Add multiple Bluetooth sensors.

        @param   sensors (int or iterable(Sensor))   Either an integer, in which case this number of default Sensors
                                                       will be added, or an iterable (list, set) of Sensor objects, in
                                                       which case these Sensors will be added.
        """
        if type(sensors) is int:
            for i in range(sensors):
                self.addSensor(Sensor())
        else:
            for i in sensors:
                self.addSensor(i)

    def isActive(self, plugin, project=None, timestamp=None):
        """
        Check if the given plugin is active for this location at the given timestamp.

        @param   plugin (str)        The name of the plugin.
        @param   project (Project)   The project to check.
        @param   timestamp (float)   The timestamp to check in UNIX time.
        @return  (bool)              True if the plugin is active at the given time, else False.
        """
        if timestamp == None:
            timestamp = int(time.time())
        if plugin in ENABLED_PLUGINS:
            return True
        elif project != None and project.isActive(timestamp) and (plugin not in project.disabled_plugins):
            return True
        else:
            return False

    def getActivePlugins(self, location=None, timestamp=None):
        """
        Get a set of active plugins for the location at the given timestamp.

        @param    location (Location)   The location to check. Use this location when None.
        @param    timestamp (int)       The UNIX timestamp to check. Use current time when None.
        @return   set(tuple)            A set of tuples mapping active projects to plugins.
                                          Project can be None for plugins that are active without project.
        """
        ap = {}
        if location == None:
            location = self
        if len(location.projects) == 0:
            for p in server.pluginmgr.getPlugins():
                if p.filename in ENABLED_PLUGINS:
                    if not p in ap:
                        ap[p] = set()
                    ap[p].add(None)
        else:
            for pr in location.projects:
                for p in server.pluginmgr.getPlugins():
                    if p.filename in ENABLED_PLUGINS:
                        if not p in ap:
                            ap[p] = set()
                        ap[p].add(pr.name)
                    elif location.isActive(p.filename, pr, timestamp):
                        if not p in ap:
                            ap[p] = set()
                        ap[p].add(pr.name)
        return ap

    def compare(self, location):
        """
        Compare the given Location object to this location. This is used to compare a new instance of the same location
        and push out locationUpdate signals when changes are detected.

        @param   location (Location)   The Location object to compare.
        """
        c = [self.__dict__[i] == location.__dict__[i] for i in ['name', 'description', 'lat', 'lon']]
        c.append(set([p.name for p in self.projects]) == set([p.name for p in location.projects]))

        if False in c:
            # Something changed in the scanner details

            # Push scanner update
            activePlugins = self.getActivePlugins(location)
            for plugin in activePlugins:
                plugin.locationUpdate(location.id, activePlugins[plugin], 'scanner', location)

            # Push sensor updates
            for sensor in location.sensors.values():
                for plugin in activePlugins:
                    plugin.locationUpdate(location.id, activePlugins[plugin], 'sensor', sensor)

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
                activePlugins = self.getActivePlugins(location)
                for plugin in activePlugins:
                    plugin.locationUpdate(location.id, activePlugins[plugin], 'scanner', location)

                # Push sensor updates
                for sensor in location.sensors.values():
                    for plugin in activePlugins:
                        plugin.locationUpdate(location.id, activePlugins[plugin], 'sensor', sensor)

class Sensor(object):
    """
    Class that represents a Bluetooth sensor.
    """
    def __init__(self, mac=None):
        """
        Initialisation.

        @param   mac (str)   The MAC-address of the Bluetooth sensor. Optional.
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
        location.projects.add(self)
