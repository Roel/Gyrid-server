#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides the plugin interface.
"""

import olof.configuration
import olof.logger

class Plugin(object):
    """
    This is the superclass interface for Olof plugins.

    All methods have a default empty implementation. This allows for plugins to only implement the methods that are
    needed.
    """
    def __init__(self, server, filename, name=None):
        """
        Initialisation.

        @param   server (Olof)    Reference to the main Olof server instance. This is made automatically when a plugin
                                    is initialised.
        @param   filename (str)   The filename of the plugins module file (without trailing '.py')
        @param   name (str)       The name of the plugin.
        """
        self.server = server
        self.filename = filename
        self.name = name

        self.configmgr = olof.configuration.Configuration(self.server, 'olof/config/%s.conf' % self.filename,
            self.defineConfiguration)
        self.logger = olof.logger.Logger(self.server, self.filename)

    def defineConfiguration(self):
        return []

    def isEnabled(self):
        """
        Check if this plugin is enabled. Set this to False to disable the plugin and thus prevent from loading.

        @return   (bool)   If this plugin is enabled. Default implementation is True.
        """
        return True

    def getStatus(self):
        """
        Used by the status plugin to render the status of this plugin.
        This should return a list of dictionaries.

        The first should only have one key: 'status', and its value should be either 'ok', 'error' or 'disabled'.

        Further status items should be dict's too with at least one key: 'id', with its value being rendered as the name
        of the status item. Additionally (and optionally) a second key can be added with more information for this item.
        The name of the key depends on the type of information given: either 'str' for a string, 'time' for a UNIX
        timestamp or 'int' for an integer value.
        """
        return [{'status': 'ok'}]

    def unload(self, shutdown=False):
        """
        Called when the plugin gets unloaded, f.ex. on server shutdown.

        All actions necessary to perform a clean shutdown should be added here, f.ex. closing network connections
        or saving data to disk.

        @param   shutdown (bool)   True if the server is shutting down, False if only this plugin is unloaded.
                                     Defaults to False.
        """
        pass

    def uptime(self, hostname, host_uptime, gyrid_uptime):
        """
        Called when new uptime information is received from the scanner.

        @param   hostname (str)       The hostname of the scanner.
        @param   host_uptime (int)    The timestamp since when the scanner is last booted up, in UNIX time.
        @param   gyrid_uptime (int)   The timestamp since when the Gyrid daemon in running, in UNIX time.
        """
        pass

    def connectionMade(self, hostname, ip, port):
        """
        Called when a new connection is made with a scanner.

        @param   hostname (str)   The hostname of the connected scanner.
        @param   ip (str)         The IP-address of the connected scanner.
        @param   port (int)       The TCP port from which the scanner is connected.
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
        """
        Called when a new or updated Location is received from the data provider.

        @param   hostname (str)   The hostname of the scanner.
        @param   module (str)     The module of the new or updated location. Currently implemented:
                                    "scanner": A new or updated location for a scanner.
                                    "sensor": A new or updated location for a sensor.
        @param   obj (Location)   The new or updated Location object. Location objects are defined in datatypes.py.
        """
        pass

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        """
        Called when new structured status information is received for a specific sensor.

        @param   hostname (str)      The hostname of the scanner.
        @param   timestamp (float)   The timestamp of the status update, in UNIX time.
        @param   sensor_mac (str)    The MAC-address of the respective Bluetooth sensor.
        @param   info (str)          The status info. Currently implemented:
                                       "new_inquiry": A new inquiry started on the sensor.
                                       "started_scanning": Started scanning with the sensor.
                                       "stopped_scanning": Stopped scanning with the sensor.
        """
        pass

    def sysStateFeed(self, hostname, module, info):
        """
        Called when new structured general status information is received.

        @param   hostname (str)   The hostname of the scanner.
        @param   module (str)     The module the status info is valid for. Currently implemented:
                                    "gyrid": Status info from the Gyrid daemon.
        @param   info (str)       The status info. Currently implemented:
                                    "connected": The Gyrid daemon connected to the networking middleware.
                                    "disconnected": The Gyrid daemon disconnected from the networking middleware.
        """
        pass

    def infoFeed(self, hostname, timestamp, info):
        """
        Called when a textual information message is received.

        @param   hostname (str)      The hostname of the scanner.
        @param   timestamp (float)   The timestamp of the info, in UNIX time.
        @param   info (str)          The info that was received.
        """
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
