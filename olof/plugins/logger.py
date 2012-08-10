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

import olof.configuration
import olof.core
import olof.tools.validation

class Logger(object):
    """
    Base logger superclass. Serves as common superclass for both Scanner and ScanSetup classes.
    Not intended to be instanciated directly.
    """
    def __init__(self, plugin, hostname, projectname):
        """
        Initialisation. Sets the base logging directory and creates the full path if it doesn't exist yet.

        @param   plugin (Plugin)  Reference to main Logger plugin instance.
        @param   hostname (str)   Hostname of the scanner where the log data originates from.
        """
        self.plugin = plugin
        self.hostname = hostname
        self.logBase = self.plugin.config.getValue('log_directory')
        self.project = projectname if projectname != None else 'No-project'
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
    def __init__(self, plugin, hostname, projectname):
        """
        Initialisation.
        """
        Logger.__init__(self, plugin, hostname, projectname)

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
    def __init__(self, plugin, hostname, projectname, sensorMac):
        """
        Initialisation.

        @param   sensorMac (str)   The MAC-address of the Bluetooth sensor.
        """
        Logger.__init__(self, plugin, hostname, projectname)
        self.sensor = sensorMac

        self.logFiles = ['scan', 'rssi']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s-%s.log' % (self.hostname, self.sensor, i)]),
            'a') for i in self.logFiles]))

        self.enableLagLog(plugin.config.getValue('enable_lag_logging'))

    def enableLagLog(self, value):
        """
        Enable or disable detailed logging of connection lag.

        @param   value (bool)   True to enable, False to disable lag logging.
        """
        self.enableLagLogging = value
        if value == True:
            if 'lag' not in self.logs or self.logs['lag'].closed:
                self.logs['lag'] = open('/'.join([self.logDir, '%s-%s-%s.log' % (
                    self.hostname, self.sensor, 'lag')]), 'a')
        elif value == False:
            if 'lag' in self.logs and not self.logs['lag'].closed:
                self.logs['lag'].close()

    def logRssi(self, rxtime, txtime, mac, rssi):
        """
        Write the given RSSI data to the log.

        @param   rxtime (int)   UNIX timestamp when the detection was received.
        @param   txtime (int)   UNIX timestamp when the detection was registered.
        @param   mac (str)      The Bluetooth MAC-address of the detected device.
        @param   rssi (int)     The value of the Received Signal Strength Indication of the detection.
        """
        self.logs['rssi'].write(','.join([str(i) for i in [
            self.formatTimestamp(txtime), mac, rssi]]) + '\n')
        self.logs['rssi'].flush()

        if self.enableLagLogging:
            self.logs['lag'].write(','.join([str(i) for i in [
                self.formatTimestamp(txtime), mac, rssi,
                '%0.4f' % rxtime,
                '%0.4f' % txtime,
                '%0.4f' % (rxtime-txtime)]]) + '\n')
            self.logs['lag'].flush()

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
        self.updateLagConfig()

    def defineConfiguration(self):
        """
        Define the configuration options for this plugin.
        """
        def validatePath(value):
            v = olof.tools.validation.parseString(value)
            return v.rstrip().rstrip('/')

        options = []

        o = olof.configuration.Option('log_directory')
        o.setDescription('Path of the directory where the data will be stored. This can be absolute or relative.')
        o.addValue(olof.configuration.OptionValue('olof/plugins/logger', default=True))
        o.setValidation(validatePath)
        o.addCallback(self.clearScanSetups)
        options.append(o)

        o = olof.configuration.Option('enable_lag_logging')
        o.setDescription('Write a separate logfile with detailed timestamps when a detection was registered and ' + \
            'received. Useful for analysing connection lag or performance.')
        o.addValue(olof.configuration.OptionValue(False, default=True))
        o.addValue(olof.configuration.OptionValue(True))
        o.addCallback(self.updateLagConfig)
        options.append(o)

        return options

    def clearScanSetups(self, value=None):
        """
        Close and clear all saved scanSetups, they will be recreated when necessary.
        """
        for ss in self.scanSetups.values():
            ss.unload()
        self.scanSetups = {}

    def updateLagConfig(self, value=None):
        """
        Update lag config for all registered scan setups.
        """
        if value == None:
            value = self.config.getValue('enable_lag_logging')

        for ss in self.scanSetups.values():
            if isinstance(ss, ScanSetup):
                ss.enableLagLog(value)

    def unload(self, shutdown=False):
        """
        Unload. Unload all Logger instances.
        """
        olof.core.Plugin.unload(self)
        for ss in self.scanSetups.values():
            ss.unload()

    def getScanSetup(self, hostname, projectname, sensorMac):
        """
        Get the ScanSetup for the given hostname and sensor. Create a new one when none available.

        @param    hostname (str)    The hostname of the scanner.
        @param    sensorMac (str)   The MAC-address of the Bluetooth sensor.
        @return   (ScanSetup)       The corresponding ScanSetup.
        """
        if not (projectname, hostname, sensorMac) in self.scanSetups:
            ss = ScanSetup(self, hostname, projectname, sensorMac)
            self.scanSetups[(projectname, hostname, sensorMac)] = ss
        else:
            ss = self.scanSetups[(projectname, hostname, sensorMac)]
        return ss

    def getScanner(self, hostname, projectname):
        """
        Get the Scanner for the given hostname. Create a new one when none available.

        @param    hostname (str)   The hostname of the scanner.
        @return   (Scanner)        The corresponding Scanner.
        """
        if not (projectname, hostname, None) in self.scanSetups:
            sc = Scanner(self, hostname, projectname)
            self.scanSetups[(projectname, hostname, None)] = sc
        else:
            sc = self.scanSetups[(projectname, hostname, None)]
        return sc

    def connectionMade(self, hostname, projects, ip, port):
        """
        Pass the information to the corresponding Scanner to be saved to the connection log.
        """
        for project in [i.id for i in projects if i != None]:
            sc = self.getScanner(hostname, project)
            sc.logConnection(time.time(), ip, port, 'made')

    def connectionLost(self, hostname, projects, ip, port):
        """
        Pass the information to the corresponding Scanner to be saved to the connection log.
        """
        for project in [i.id for i in projects if i != None]:
            sc = self.getScanner(hostname, project)
            try:
                sc.logConnection(time.time(), ip, port, 'lost')
            except ValueError:
                pass

    def infoFeed(self, hostname, projects, timestamp, info):
        """
        Pass the information to the corresponding Scanner to be saved to the info log.
        """
        for project in [i.id for i in projects if i != None]:
            sc = self.getScanner(hostname, project)
            sc.logInfo(timestamp, info)

    def dataFeedCell(self, hostname, projects, timestamp, sensorMac, mac, deviceclass, move):
        """
        Pass the information to the corresponding ScanSetup to be saved to the cell-data log.
        """
        for project in [i.id for i in projects if i != None]:
            ss = self.getScanSetup(hostname, project, sensorMac)
            ss.logCell(timestamp, mac, deviceclass, move)

    def dataFeedRssi(self, hostname, projects, timestamp, sensorMac, mac, rssi):
        """
        Pass the information to the corresponding ScanSetup to be saved to the RSSI-data log.
        """
        t = time.time()
        for project in [i.id for i in projects if i != None]:
            ss = self.getScanSetup(hostname, project, sensorMac)
            ss.logRssi(t, timestamp, mac, rssi)
