#!/usr/bin/python

from twisted.internet import reactor
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import LineReceiver

import time

import olof.core

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

    def buildProtocol(self, addr):
        """
        Build the InetClient protocol, return an InetClient instance.
        """
        self.resetDelay()
        self.client = LineReceiver()

        self.plugin.output("db4o: Connected to server")
        return self.client

class Plugin(olof.core.Plugin):
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server, "db4o")
        self.host = 'localhost'
        self.port = 5000
        self.mac_dc = {}

        self.inet_factory = InetClientFactory(self)
        reactor.connectTCP(self.host, self.port, self.inet_factory)

    def getStatus(self):
        return [['no connection', None]]

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
             move):
        if 'client' in self.inet_factory.__dict__ and \
            self.inet_factory.client != None:
            self.inet_factory.client.sendLine(','.join([hostname, sensor_mac,
                 mac, deviceclass, str(int(float(timestamp))), move]))

        if move == 'in':
            self.mac_dc[mac] = deviceclass
        elif move == 'out' and mac in self.mac_dc:
            del(self.mac_dc[mac])

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        if 'client' in self.inet_factory.__dict__ and \
            self.inet_factory.client != None:
            deviceclass = self.mac_dc.get(mac, '-1')
            self.inet_factory.client.sendLine(','.join([hostname, sensor_mac,
                mac, deviceclass, str(int(float(timestamp))), rssi]))
