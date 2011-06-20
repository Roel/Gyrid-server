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

    def sendLine(self, line):
        if 'client' in self.__dict__ and self.client != None:
            self.client.sendLine(line.strip())

    def clientConnectionLost(self, connector, reason):
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)
        self.plugin.connected = False
        self.plugin.conn_time = int(time.time())

    def buildProtocol(self, addr):
        """
        Build the InetClient protocol, return an InetClient instance.
        """
        self.resetDelay()
        self.plugin.connected = True
        self.plugin.conn_time = int(time.time())
        self.client = LineReceiver()

        return self.client

class Plugin(olof.core.Plugin):
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server, "db4o")
        self.host = 'localhost'
        self.port = 5001
        self.mac_dc = {}

        self.connected = False
        self.conn_time = None

        self.inet_factory = InetClientFactory(self)
        reactor.connectTCP(self.host, self.port, self.inet_factory)

    def getStatus(self):
        if self.connected == False and self.conn_time == None:
            return [['no connection', None]]
        elif self.connected == False:
            return [['disconnected', self.conn_time]]
        elif self.connected == True:
            return [['connected', self.conn_time]]

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
