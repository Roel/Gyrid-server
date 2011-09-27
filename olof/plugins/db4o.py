#!/usr/bin/python

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver

import cPickle as pickle
import os
import time

import olof.core
from olof.locationprovider import Location

class InetClient(LineReceiver):
    def __init__(self, factory, plugin):
        self.factory = factory
        self.plugin = plugin

    def connectionMade(self):
        self.plugin.connected = True
        self.plugin.conn_time = int(time.time())
        self.pushCache()

    def connectionLost(self, reason):
        self.plugin.connected = False
        self.plugin.conn_time = int(time.time())
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()
        self.plugin.cache = open(self.plugin.cache_file, 'a')

    def sendLine(self, line):
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
        #self.plugin.cached_lines = 0

class InetClientFactory(ReconnectingClientFactory):
    """
    The factory class of the inet client.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        @param   network   Reference to a Network instance.
        """
        self.plugin = plugin
        self.maxDelay = 120
        self.client = None
        self.buildProtocol(None)

    def sendLine(self, line):
        if 'client' in self.__dict__ and self.client != None:
            self.client.sendLine(line)

    def buildProtocol(self, addr):
        """
        Build the InetClient protocol, return an InetClient instance.
        """
        self.resetDelay()
        self.client = InetClient(self, self.plugin)
        return self.client

class Plugin(olof.core.Plugin):
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server, "Db4o")
        self.host = 'localhost'
        self.port = 5001
        self.cache_file = '/var/tmp/gyrid-server-db4o.cache'
        self.cache = open(self.cache_file, 'r')
        self.cached_lines = 0
        for line in self.cache:
            self.cached_lines += 1
        self.cache.close()
        self.cache = open(self.cache_file, 'a')

        self.connected = False
        self.conn_time = None

        self.locations = []
        if os.path.isfile('olof/plugins/db4o/locations.pickle'):
            f = open('olof/plugins/db4o/locations.pickle', 'rb')
            self.locations = pickle.load(f)
            f.close()

        self.scanSetups = []
        if os.path.isfile('olof/plugins/db4o/scanSetups.pickle'):
            f = open('olof/plugins/db4o/scanSetups.pickle', 'rb')
            self.locations = pickle.load(f)
            f.close()

        self.inet_factory = InetClientFactory(self)
        reactor.connectTCP(self.host, self.port, self.inet_factory)

    def unload(self):
        f = open('olof/plugins/db4o/locations.pickle', 'wb')
        pickle.dump(self.locations, f)
        f.close()

        f = open('olof/plugins/db4o/scanSetups.pickle', 'wb')
        pickle.dump(self.scanSetups, f)
        f.close()

    def getStatus(self):
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
        if not [sensor, id, description, x, y] in self.locations:
            self.server.output('db4o: Adding location %s|%s' % (id, sensor))
            self.locations.append([sensor, id, description, x, y])
            self.inet_factory.sendLine(','.join(['addLocation',
                '%s|%s' % (id, sensor), description, "%0.6f" % x, "%0.6f" % y]))

    def addScanSetup(self, hostname, sensor, id, timestamp):
        if not [hostname, sensor, id, timestamp, 1] in self.scanSetups:
            self.server.output('db4o: Adding ScanSetup for %s at %i: %s' % \
                (hostname, timestamp, '%s|%s' % (id, sensor)))
            self.scanSetups.append([hostname, sensor, id, timestamp, 1])
            self.inet_factory.sendLine(','.join(['installScannerSetup',
                hostname, sensor, '%s|%s' % (id, sensor), str(int(timestamp*1000))]))

    def removeScanSetup(self, hostname, sensor, id, timestamp):
        if not [hostname, sensor, id, timestamp, 0] in self.scanSetups:
            self.server.output('db4o: Removing ScanSetup for %s at %i: %s' % \
                (hostname, timestamp, '%s|%s' % (id, sensor)))
            self.scanSetups.append([hostname, sensor, id, timestamp, 0])
            self.inet_factory.sendLine(','.join(['removeScannerSetup',
                hostname, sensor, '%s|%s' % (id, sensor), str(int(timestamp*1000))]))

    def locationUpdate(self, hostname, module, timestamp, id, description, coordinates):
        if module == 'scanner' and hostname in self.server.location_provider.new_locations:
            for sensor in self.server.location_provider.new_locations[hostname][Location.Sensors]:
                if sensor != Location.Sensor:
                    
                    self.addLocation(sensor, id, description,
                        self.server.location_provider.new_locations[hostname][Location.Sensors][sensor][Location.X],
                        self.server.location_provider.new_locations[hostname][Location.Sensors][sensor][Location.Y])

                    if Location.TimeInstall in self.server.location_provider.new_locations[hostname][Location.Times]:
                        self.addScanSetup(hostname, sensor, id, timestamp)
                    if Location.TimeUninstall in self.server.location_provider.new_locations[hostname][Location.Times]:
                        self.removeScanSetup(hostname, sensor, id, timestamp)

        if module not in ['sensor', 'scanner']:
            if coordinates != None:
                self.addLocation(module, id, description, coordinates[0], coordinates[1])
                self.addScanSetup(hostname, module, id, timestamp)
            else:
                self.removeScanSetup(hostname, module, id, timestamp)

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        if info == 'new_inquiry':
            self.inet_factory.sendLine(','.join([hostname, 'INFO',
                str(int(timestamp*1000)), 'new_inquiry', sensor_mac]))

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
             move):
        self.inet_factory.sendLine(','.join([hostname, sensor_mac, mac,
            str(deviceclass), str(int(timestamp*1000)), move]))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        deviceclass = str(self.server.getDeviceclass(mac))
        self.inet_factory.sendLine(','.join([hostname, sensor_mac, mac,
            deviceclass, str(int(timestamp*1000)), str(rssi)]))
