#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides the plugin interface.
"""

class Plugin(object):
    """
    This is the superclass interface for Olof plugins.
    """
    def __init__(self, server, name=None):
        """
        Initialisation.

        @param   server (Olof)   Reference to the main Olof server instance. This is made automatically when a plugin
                                   is initialised.
        @param   name (str)      The name of the plugin.
        """
        self.server = server
        self.filename = None
        self.name = name
        self.output = self.server.output

    def getStatus(self):
        return []

    def unload(self):
        """
        Called when the plugin gets unloaded, f.ex. on server shutdown.

        All actions necessary to perform a clean shutdown should be added here, f.ex. closing network connections
        or saving data to disk.
        """
        pass

    def uptime(self, hostname, host_uptime, gyrid_uptime):
        pass

    def connectionMade(self, hostname, ip, port):
        """
        Called when a new connection is made with a scanner.

        @param   hostname (str)  The hostname of the connected scanner.
        @param   ip (str)        The IP-address of the connected scanner.
        @param   port (int)      The TCP port from which the scanner is connected.
        """
        pass

    def connectionLost(self, hostname, ip, port):
        """
        Called when a connection to a scanner is lost.

        @param   hostname (str)  The hostname of the scanner that lost a connection.
        @param   ip (str)        The IP-address the scanner was connected from.
        @param   port (int)      The TCP port the scanner was connected from.
        """
        pass

    def locationUpdate(self, hostname, module, obj):
        pass

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        pass

    def sysStateFeed(self, hostname, module, info):
        pass

    def infoFeed(self, hostname, timestamp, info):
        pass

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        """
        Called when new cell data is received.

        @param   hostname (str)      The hostname of the scanner that detected the device.
        @param   timestamp (float)   The timestamp at which the device was first or last detected, depending on the
                                       move. In UNIX time.
        @param   sensor_mac (str)    The MAC-address of the Bluetooth sensor that discovered the device. Representation
                                       without colons, f.ex. 001122334455
        @param   mac (str)           The Bluetooth MAC-address of the detected device. Representation without colons,
                                       f.ex. 001122334455
        @param   deviceclass (int)   The Bluetooth deviceclass of the detected device.
        @param   move (str)          Either 'in' or 'out', depending on whether the device move in or out the range of
                                       the sensor.
        """
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        """
        Called when new RSSI data is received.

        @param   hostname (str)      The hostname of the scanner that detected the device.
        @param   timestamp (float)   The timestamp at which the device was detected. In UNIX time.
        @param   sensor_mac (str)    The MAC-address of the Bluetooth sensor that discovered the device. Representation
                                       without colons, f.ex. 001122334455
        @param   mac (str)           The Bluetooth MAC-address of the detected device. Representation without colons,
                                       f.ex. 001122334455
        @param   rssi (int)          The value of the Received Signal Strength Indication of the detection.
        """
        pass
