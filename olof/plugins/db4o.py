#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin that handles the connection with the Db4O database.
"""

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver

import os
import time

import olof.configuration
import olof.core
import olof.storagemanager

class Db4OClient(LineReceiver):
    """
    The class handling the connection with the Db4O server.
    """
    def __init__(self, factory, plugin):
        """
        Initialisation.

        @param   factory (t.i.p.ClientFactory)   Reference to a Twisted ClientFactory.
        @param   plugin (olof.core.Plugin)       Reference to the main Db4O Plugin instance.
        """
        self.delimiter = '\n'
        self.factory = factory
        self.plugin = plugin

    def connectionMade(self):
        """
        Push through the cache.
        """
        self.plugin.connected = True
        self.plugin.conn_time = int(time.time())
        self.pushCache()

    def connectionLost(self, reason):
        """
        Open the cache.
        """
        self.plugin.connected = False
        self.plugin.conn_time = int(time.time())
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()
        self.plugin.cache = open(self.plugin.cache_file, 'a')

    def sendLine(self, line):
        """
        Try to send the line to the Db4O server. When not connected, cache the line.
        """
        if self.transport != None and self.plugin.connected:
            LineReceiver.sendLine(self, line.strip())
        elif not self.plugin.connected and not self.plugin.cache.closed:
            self.plugin.cache.write(line.strip() + '\n')
            self.plugin.cache.flush()
            self.plugin.cached_lines += 1

    def pushCache(self):
        """
        Push trough the cached data. Clears the cache afterwards.
        """
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        self.plugin.cache = open(self.plugin.cache_file, 'r')
        for line in self.plugin.cache:
            line = line.strip()
            self.sendLine(line)
            self.plugin.cached_lines -= 1
        self.plugin.cache.close()

        self.clearCache()

    def clearCache(self):
        """
        Clears the cache file.
        """
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        self.plugin.cache = open(self.plugin.cache_file, 'w')
        self.plugin.cache.truncate()
        self.plugin.cache.close()

class Db4OClientFactory(ReconnectingClientFactory):
    """
    The factory class of the Db4O client.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        @param   plugin (olof.core.Plugin)   Reference to the main Db4O Plugin instance.
        """
        self.plugin = plugin
        self.maxDelay = 120
        self.client = None
        self.buildProtocol(None)

    def sendLine(self, line):
        """
        Send a line via the Db4O client.

        @param   line (str)   The line to send.
        """
        if 'client' in self.__dict__ and self.client != None:
            self.client.sendLine(line)

    def buildProtocol(self, addr):
        """
        Build the Db4OClient protocol, return an Db4OClient instance.
        """
        self.resetDelay()
        self.client = Db4OClient(self, self.plugin)
        return self.client

class Plugin(olof.core.Plugin):
    """
    Main Db4O plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation. Set up connection details and open cache file.
        Read saved location and scansetup data from disk.

        Connect to the Db4O server.
        """
        olof.core.Plugin.__init__(self, server, filename, "Db4o")
        self.host = self.config.getValue('host')
        self.port = self.config.getValue('port')
        self.cache_file = self.config.getValue('cache_file')
        self.cached_lines = 0
        if os.path.isfile(self.cache_file):
            self.cache = open(self.cache_file, 'r')
            for line in self.cache:
                self.cached_lines += 1
            self.cache.close()

        self.server.checkDiskAccess([self.cache_file])
        self.cache = open(self.cache_file, 'a')

        self.connected = False
        self.conn_time = None

        self.locations = self.storage.loadVariable('locations', [])
        self.scanSetups = self.storage.loadVariable('scanSetups', [])

        self.db4o_factory = Db4OClientFactory(self)
        reactor.connectTCP(self.host, self.port, self.db4o_factory)

    def defineConfiguration(self):
        options = []

        o = olof.configuration.Option('host')
        o.setDescription('Hostname or IP-address of the Db4O database server.')
        o.addValue(olof.configuration.OptionValue('localhost', default=True))
        options.append(o)

        o = olof.configuration.Option('port')
        o.setDescription('TCP port to use on the database server.')
        o.setValidation(olof.tools.validation.parseInt)
        o.addValue(olof.configuration.OptionValue(5001, default=True))
        options.append(o)

        o = olof.configuration.Option('cache_file')
        o.setDescription('Location of the file to use for caching data when the connection with the database ' + \
            'fails or is lost.')
        o.addValue(olof.configuration.OptionValue('/var/cache/gyrid-server/db4o.cache', default=True))
        options.append(o)

        return options

    def unload(self, shutdown=False):
        """
        Unload. Save locations and scansetups to disk.
        """
        olof.core.Plugin.unload(self)
        self.storage.saveVariable(self.locations, 'locations')
        self.storage.saveVariable(self.scanSetups, 'scanSetups')

    def getStatus(self):
        """
        Return the current status of the Db4O connection and cache. For use in the status plugin.
        """
        cl = {}
        if self.cached_lines > 0:
            cl = {'id': 'cached lines', 'int': self.cached_lines}

        r = []
        if self.connected == False and self.conn_time == None:
            r = [{'status': 'error'}, {'id': 'no connection'}]
        elif self.connected == False:
            r = [{'status': 'error'},
                {'id': 'disconnected', 'time': self.conn_time}]
        elif self.connected == True:
            r = [{'status': 'ok'},
                {'id': 'connected', 'time': self.conn_time}]

        if len(cl) > 0:
            r.append(cl)
        return r

    def addLocation(self, sensor, id, description, x, y):
        """
        Add a new location to the database. Only add if it is actually new.

        @param   sensor (str)        The MAC-address of the Bluetooth sensor.
        @param   id (str)            Unique ID (name) of the location.
        @param   description (str)   Description of the location.
        @param   x (float)           X-coordinate of the location.
        @param   y (float)           Y-coordinate of the location.
        """
        if not [sensor, id, description, x, y] in self.locations:
            self.logger.logInfo('db4o: Adding location %s|%s' % (id, sensor))
            self.locations.append([sensor, id, description, x, y])
            self.db4o_factory.sendLine(','.join(['addLocation',
                '%s|%s' % (id, sensor), str(description), "%0.6f" % x, "%0.6f" % y]))

    def addScanSetup(self, hostname, sensor, id, timestamp):
        """
        Add a new scansetup to the database.

        @param   hostname (str)      Hostname of the scanner.
        @param   sensor (str)        The MAC-address of the Bluetooth sensor.
        @param   id (str)            Unique ID (name) of the location.
        @param   timestamp (float)   Timestamp at which the scansetup is installed. In UNIX time.
        """
        if not [hostname, sensor, id, timestamp, 1] in self.scanSetups:
            self.logger.logInfo('db4o: Adding ScanSetup for %s at %i: %s' % \
                (hostname, timestamp, '%s|%s' % (id, sensor)))
            self.scanSetups.append([hostname, sensor, id, timestamp, 1])
            self.db4o_factory.sendLine(','.join(['installScannerSetup',
                hostname, sensor, '%s|%s' % (id, sensor), str(int(timestamp*1000))]))

    def removeScanSetup(self, hostname, sensor, id, timestamp):
        """
        Remove a scansetup from the database.

        @param   hostname (str)      Hostname of the scanner.
        @param   sensor (str)        The MAC-address of the Bluetooth sensor.
        @param   id (str)            Unique ID (name) of the location.
        @param   timestamp (float)   Timestamp at which the scansetup is installed. In UNIX time.
        """
        if not [hostname, sensor, id, timestamp, 0] in self.scanSetups:
            self.logger.logInfo('db4o: Removing ScanSetup for %s at %i: %s' % \
                (hostname, timestamp, '%s|%s' % (id, sensor)))
            self.scanSetups.append([hostname, sensor, id, timestamp, 0])
            self.db4o_factory.sendLine(','.join(['removeScannerSetup',
                hostname, sensor, '%s|%s' % (id, sensor), str(int(timestamp*1000))]))

    def locationUpdate(self, hostname, module, obj):
        """
        Perform a location update. Add and remove locations and scansetups accordingly.
        """
        if module == 'scanner':
            for sensor in obj.sensors.values():
                self.addLocation(sensor.mac, obj.id, obj.description, sensor.lon, sensor.lat)
                if sensor.start != None:
                    self.addScanSetup(hostname, sensor.mac, obj.id, sensor.start)
                if sensor.end != None:
                    self.removeScanSetup(hostname, sensor.mac, obj.id, sensor.end)

        elif module == 'sensor':
            if (obj.lat == None or obj.lon == None) and obj.end != None:
                self.removeScanSetup(hostname, obj.mac, obj.location.id, obj.end)
            elif (obj.lat != None and obj.lon != None) and obj.start != None:
                self.addLocation(obj.mac, obj.location.id, obj.location.description, obj.lon, obj.lat)
                self.addScanSetup(hostname, obj.mac, obj.location.id, obj.start)

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        """
        Send new_inquiry status messages to the Db4O server.
        """
        dp = self.server.dataprovider
        if info == 'new_inquiry':
            self.db4o_factory.sendLine(','.join([str(dp.getProjectName(hostname)),
                hostname, 'INFO', str(int(timestamp*1000)), 'new_inquiry',
                sensor_mac]))

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass, move):
        """
        Send cell data to the Db4O server.
        """
        dp = self.server.dataprovider
        self.db4o_factory.sendLine(','.join([str(dp.getProjectName(hostname)),
            hostname, sensor_mac, mac, str(deviceclass),
            str(int(timestamp*1000)), move]))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        """
        Send RSSI data to the Db4O server.
        """
        dp = self.server.dataprovider
        deviceclass = str(self.server.getDeviceclass(mac))
        self.db4o_factory.sendLine(','.join([str(dp.getProjectName(hostname)),
            hostname, sensor_mac, mac, str(deviceclass),
            str(int(timestamp*1000)), str(rssi)]))
