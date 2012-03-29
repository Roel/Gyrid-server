#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin that handles on-disk logging of received scanner data.
"""

import os
import time

import olof.core

class Logger(object):
    """
    Base logger superclass. Serves as common superclass for both Scanner and ScanSetup classes.
    Not intended to be instanciated directly.
    """
    def __init__(self, plugin, hostname):
        """
        Initialisation. Sets the base logging directory and creates the full path if it doesn't exist yet.

        @param   plugin (Plugin)  Reference to main Logger plugin instance.
        @param   hostname (str)   Hostname of the scanner where the log data originates from.
        """
        self.plugin = plugin
        self.hostname = hostname
        self.logBase = 'olof/plugins/logger'
        self.project = self.plugin.getProject(self.hostname)
        self.logDir = '/'.join([self.logBase, self.project, self.hostname])
        self.logs = {}

        if not os.path.exists(self.logDir):
            os.makedirs(self.logDir, mode=0755)

    def unload(self):
        """
        Unload the logger, closing all logfiles.
        """
        for f in self.logs.values():
            f.close()

    def formatTimestamp(self, timestamp):
        """
        Format the given UNIX timestamp in the '%Y%m%d-%H%M%S-%Z' format.

        @param   timestamp (int)   The timestamp to convert.
        @return  (str)             The converted timestamp.
        """
        return time.strftime('%Y%m%d-%H%M%S-%Z', time.localtime(timestamp))

class Scanner(Logger):
    """
    Class that represents a logger for a specific scanner, logging only scanner-wide data, such as informational
    messages and connection data.
    """
    def __init__(self, plugin, hostname):
        """
        Initialisation.
        """
        Logger.__init__(self, plugin, hostname)

        self.logFiles = ['messages', 'connections']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s.log' % (self.hostname, i)]),
            'a') for i in self.logFiles]))

        self.host = None
        self.port = None

    def unload(self):
        """
        Unload. Write a 'server shutdown' message to the connection log.
        """
        self.logConnection(time.time(), self.host, self.port, 'server shutdown')
        Logger.unload(self)

    def logInfo(self, timestamp, info):
        """
        Write the given information to the info log.

        @param   timestamp (int)   UNIX timestamp of the information.
        @param   info (str)        The actual information to log.
        """
        self.logs['messages'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), info]]) + '\n')
        self.logs['messages'].flush()

    def logConnection(self, timestamp, host, port, action):
        """
        Write the given information to the connection log.

        @param   timestamp (int)   UNIX timestamp of the information.
        @param   host (str)        The IP-address of the scanner that made or lost a connection.
        @param   port (int)        The originating TCP port of the scanner that made or lost a connection.
        @param   action (str)      Either 'made' or 'lost', respective to a connection being made or lost.
        """
        if action == 'made':
            self.host = host
            self.port = port

        self.logs['connections'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), host, port, action]]) + '\n')
        self.logs['connections'].flush()

class ScanSetup(Logger):
    """
    Class that represents a logger for a scanner-setup, i.e. a combination of a scanner and a Bluetooth sensor.
    This logger logs all Bluetooth data, such as cell-based and RSSI data.
    """
    def __init__(self, plugin, hostname, sensor_mac):
        """
        Initialisation.

        @param   sensor_mac (str)   The MAC-address of the Bluetooth sensor.
        """
        Logger.__init__(self, plugin, hostname)
        self.sensor = sensor_mac

        self.logFiles = ['scan', 'rssi']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s-%s.log' % (self.hostname, self.sensor, i)]),
            'a') for i in self.logFiles]))

    def logRssi(self, timestamp, mac, rssi):
        """
        Write the given RSSI data to the log.

        @param   timestamp (int)   Timestamp, in UNIX time the detected was received.
        @param   mac (str)         The Bluetooth MAC-address of the detected device.
        @param   rssi (int)        The value of the Received Signal Strength Indication of the detection.
        """
        self.logs['rssi'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), mac, rssi]]) + '\n')
        self.logs['rssi'].flush()

    def logCell(self, timestamp, mac, deviceclass, move):
        """
        Write the given cell data to the log.

        @param   timestamp (int)     Timestamp, in UNIX time the detected was received.
        @param   mac (str)           The Bluetooth MAC-address of the detected device.
        @param   deviceclass (int)   The Bluetooth deviceclass of the detected device.
        @param   move (str)          Whether the device moved 'in' or 'out' the sensor's range.
        """
        self.logs['scan'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), mac, deviceclass, move]]) + '\n')
        self.logs['scan'].flush()

class Plugin(olof.core.Plugin):
    """
    Main Logger plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation.
        """
        olof.core.Plugin.__init__(self, server, filename)

        self.scanSetups = {}

    def unload(self, shutdown=False):
        """
        Unload. Unload all Logger instances.
        """
        for ss in self.scanSetups.values():
            ss.unload()

    def getProject(self, hostname):
        """
        Get the name of the project associated with the given hostname.

        @param    hostname (str)   The hostname to check.
        @return   (str)            The name of the project the scanner with the given hostname belongs to.
                                     'No-project' when the scanner is not attached to a project.
        """
        project = self.server.dataprovider.getProjectName(hostname)
        return project if project != None else 'No-project'

    def getScanSetup(self, hostname, sensor_mac):
        """
        Get the ScanSetup for the given hostname and sensor. Create a new one when none available.

        @param    hostname (str)     The hostname of the scanner.
        @param    sensor_mac (str)   The MAC-address of the Bluetooth sensor.
        @return   (ScanSetup)        The corresponding ScanSetup.
        """
        project = self.getProject(hostname)
        if not (project, hostname, sensor_mac) in self.scanSetups:
            ss = ScanSetup(self, hostname, sensor_mac)
            self.scanSetups[(project, hostname, sensor_mac)] = ss
        else:
            ss = self.scanSetups[(project, hostname, sensor_mac)]
        return ss

    def getScanner(self, hostname):
        """
        Get the Scanner for the given hostname. Create a new one when none available.

        @param    hostname (str)   The hostname of the scanner.
        @return   (Scanner)        The corresponding Scanner.
        """
        project = self.getProject(hostname)
        if not (project, hostname, None) in self.scanSetups:
            sc = Scanner(self, hostname)
            self.scanSetups[(project, hostname, None)] = sc
        else:
            sc = self.scanSetups[(project, hostname, None)]
        return sc

    def connectionMade(self, hostname, ip, port):
        """
        Pass the information to the corresponding Scanner to be saved to the connection log.
        """
        sc = self.getScanner(hostname)
        sc.logConnection(time.time(), ip, port, 'made')

    def connectionLost(self, hostname, ip, port):
        """
        Pass the information to the corresponding Scanner to be saved to the connection log.
        """
        sc = self.getScanner(hostname)
        try:
            sc.logConnection(time.time(), ip, port, 'lost')
        except ValueError:
            pass

    def infoFeed(self, hostname, timestamp, info):
        """
        Pass the information to the corresponding Scanner to be saved to the info log.
        """
        sc = self.getScanner(hostname)
        sc.logInfo(timestamp, info)

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass, move):
        """
        Pass the information to the corresponding ScanSetup to be saved to the cell-data log.
        """
        ss = self.getScanSetup(hostname, sensor_mac)
        ss.logCell(timestamp, mac, deviceclass, move)

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        """
        Pass the information to the corresponding ScanSetup to be saved to the RSSI-data log.
        """
        ss = self.getScanSetup(hostname, sensor_mac)
        ss.logRssi(timestamp, mac, rssi)
