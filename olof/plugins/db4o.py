#!/usr/bin/python

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver

import time

import olof.core

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
        self.plugin.cached_lines = 0

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
        olof.core.Plugin.__init__(self, server, "db4o")
        self.host = 'localhost'
        self.port = 5001
        self.cache_file = '/var/tmp/gyrid-server-db4o.cache'
        self.cache = open(self.cache_file, 'r')
        self.cached_lines = 0
        for line in self.cache:
            self.cached_lines += 1
        self.cache.close()
        self.cache = open(self.cache_file, 'a')
        self.mac_dc = {}

        self.connected = False
        self.conn_time = None

        self.inet_factory = InetClientFactory(self)
        reactor.connectTCP(self.host, self.port, self.inet_factory)

    def getStatus(self):
        cl = {}
        if self.cached_lines > 0:
            cl = {'id': 'cached lines', 'str': str(self.cached_lines)}
        if self.connected == False and self.conn_time == None:
            r = [{'id': 'no connection'}]
            if len(cl) > 0:
                r.append(cl)
            return r
        elif self.connected == False:
            return [{'id': 'disconnected', 'time': self.conn_time}]
            if len(cl) > 0:
                r.append(cl)
            return r
        elif self.connected == True:
            return [{'id': 'connected', 'time': self.conn_time}]

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        if info == 'new_inquiry':
            self.inet_factory.sendLine(','.join([hostname, 'INFO',
                str(int(float(timestamp)*1000)), 'new_inquiry', sensor_mac]))

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
             move):
        self.inet_factory.sendLine(','.join([hostname, sensor_mac, mac,
            deviceclass, str(int(float(timestamp)*1000)), move]))

        if move == 'in':
            self.mac_dc[mac] = deviceclass
        elif move == 'out' and mac in self.mac_dc:
            del(self.mac_dc[mac])

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        deviceclass = self.mac_dc.get(mac, '-1')
        self.inet_factory.sendLine(','.join([hostname, sensor_mac, mac,
            deviceclass, str(int(float(timestamp)*1000)), rssi]))
