#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.internet import reactor, task

import copy
import os
import time
import urllib2

import olof.configuration
import olof.core
import olof.storagemanager
from olof.tools.webprotocols import RESTConnection

class Connection(RESTConnection):
    """
    Class that implements the REST connection with the Move database.
    """
    def __init__(self, plugin, url, user, password, measurements={}, measureCount={}, locations={}):
        """
        Initialisation.

        Start looping calls that upload measurements and locations.

        @param   plugin (Plugin)       Reference to main Move plugin instance.
        @param   url (str)             Base URL of the Move REST interface.
        @param   user (str)            Username to log in on the server.
        @param   password (str)        Password to log in on the server.
        @param   measurements (dict)   Cached measurements. Optional.
        @param   measureCount (dict)   Cache statistics. Optional.
        @param   locations (dict)      Cached location data. Optional.
        """
        RESTConnection.__init__(self, url, 180, user, password, urllib2.HTTPDigestAuthHandler)
        self.plugin = plugin
        self.server = self.plugin.server
        self.scanners = {}
        self.getScanners()
        self.lastError = None

        self.requestRunning = False
        self.measurements = measurements
        if len(measureCount) == 0:
            self.measureCount = {'uploads': 0, 'uploaded': 0, 'last_upload': -1, 'failed_uploads': 0,
                'recent_uploads': []}
        else:
            self.measureCount = measureCount

        self.locations = locations

        self.task_postM = task.LoopingCall(self.postMeasurements)
        self.task_postM.start(60, now=False)

        self.task_postL = task.LoopingCall(self.postLocations)
        reactor.callLater(40, self.task_postL.start, 60, now=False)

    def unload(self, shutdown=False):
        """
        Unload the connection, stopping looping calls.
        """
        try:
            self.task_postM.stop()
        except AssertionError:
            pass

        try:
            self.task_postL.stop()
        except AssertionError:
            pass

    def getScanners(self):
        """
        Get the list of scanners from the Move database and update local scanner data.

        @return   (str)   Result of the query.
        """
        def process(r):
            if type(r) is urllib2.HTTPError:
                self.lastError = str(r)
                return
            else:
                self.lastError = None
            if r != None:
                for s in r:
                    ls = s.strip().split(',')
                    self.scanners[ls[0]] = True
            return r

        self.requestGet('scanner', process)

    def addScanner(self, mac, description):
        """
        Add a scanner to the Move database.

        @param   mac (str)           Bluetooth MAC-address of the scanner.
        @param   description (str)   Description of the scanner.
        """
        def process(r):
            if type(r) is urllib2.HTTPError:
                self.lastError = str(r)
            else:
                self.lastError = None

        self.requestPost('scanner', process, '%s,%s' % (mac, description),
            {'Content-Type': 'text/plain'})

    def addLocation(self, sensor, timestamp, coordinates, description):
        """
        Add a location to the local location list.

        @param   sensor (str)          MAC-address of the Bluetooth sensor.
        @param   timestamp (int)       Timestamp of the time the scanner was added/removed. In UNIX time.
        @param   coordinates (tuple)   Tuple containing the X and Y coordinates of the location respectively.
        @param   description (str)     Description of the location.
        """
        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        if not sensor in self.locations:
            self.locations[sensor] = [[(timestamp, coordinates, description), False]]
            self.plugin.logger.logInfo("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description,
                coordinates))
        else:
            if not (timestamp, coordinates, description) in [i[0] for i in self.locations[sensor]]:
                self.locations[sensor].append([(timestamp, coordinates, description), False])
                self.plugin.logger.logInfo("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp,
                    description, coordinates))

    def postLocations(self):
        """
        Upload the pending location updates to the Move database.
        """
        def process(r):
            if type(r) is urllib2.HTTPError:
                self.lastError = str(r)
                return
            else:
                self.lastError = None
            if r != None and not 'error' in str(r).lower():
                for scanner in to_delete:
                    for l in self.locations[scanner]:
                        l[1] = True

        if self.requestRunning or not self.plugin.config.getValue('upload_enabled'):
            return

        l = ""
        to_delete = []
        l_scanner = []

        for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
            and s in self.locations)]:
            if len([True for l in self.locations[scanner] if l[1] == False]) == 0:
                continue
            l_scanner.append("==%s" % scanner)
            to_delete.append(scanner)
            loc = []
            for location in [l[0] for l in self.locations[scanner] if l[1] == False]:
                if location[1] != None:
                    loc.append(','.join([time.strftime('%Y%m%d-%H%M%S-%Z',
                        time.localtime(location[0])),
                        'SRID=4326;POINT(%0.6f %0.6f)' % location[1],
                        'EWKT', location[2]]))
                else:
                    loc.append(','.join([time.strftime('%Y%m%d-%H%M%S-%Z',
                        time.localtime(location[0])), 'NULL', 'NULL', 'NULL']))
            l_scanner.append("\n".join(loc))

        l = '\n'.join(l_scanner)
        if len(l) > 0:
            self.plugin.logger.logInfo("move: Posting location: %s" % l)
            self.requestPost('scanner/location', process, l,
                {'Content-Type': 'text/plain'})

    def addMeasurement(self, sensor, timestamp, mac, deviceclass, rssi):
        """
        Add a measurement to the local measurement list.

        @param   sensor (str)        MAC-address of the Bluetooth sensor that detected the device.
        @param   timestamp (int)     Timestamp of the detection. In UNIX time.
        @param   mac (str)           Bluetooth MAC-address of the detected device.
        @param   deviceclass (int)   Deviceclass of the detected Bluetooth device.
        @param   rssi (int)          Value for the Received Signal Strength Indication for the detection.
        """
        if not sensor in self.measurements:
            self.measurements[sensor] = set()

        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        tm = "%0.3f" % timestamp
        decSec = tm[tm.find('.')+1:]
        decSec += "0" * (3-len(decSec))
        self.measurements[sensor].add(','.join([time.strftime('%Y%m%d-%H%M%S.%%s-%Z',
            time.localtime(timestamp)) % decSec, mac, str(deviceclass), str(rssi)]))

    def postMeasurements(self):
        """
        Upload pending measurements to the Move database.
        """
        def process(r):
            self.plugin.logger.logInfo("Request done")
            self.requestRunning = False
            if type(r) is urllib2.HTTPError:
                self.lastError = str(r)
            else:
                self.lastError = None
            alertPlugin = self.plugin.server.pluginmgr.getPlugin('alert')
            if r != None and type(r) is list and len(r) == len(to_delete):
                self.measureCount['uploads'] += 1
                self.measureCount['last_upload'] = int(time.time())
                uploadSize = 0
                for i in range(len(r)):
                    scanner = to_delete.pop(0)
                    move_lines = int(r.pop(0).strip().split(',')[1])
                    uploaded_lines = scanner[1]

                    if move_lines == uploaded_lines:
                        self.plugin.logger.logInfo("Upload for scanner %s: OK" % scanner[0])
                        uploadSize += uploaded_lines
                        for l in self.measurements_uploaded[scanner[0]]:
                            self.measurements[scanner[0]].remove(l)
                    else:
                        self.plugin.logger.logError("Upload for scanner %s: FAIL" % scanner[0])
                if len(self.measureCount['recent_uploads']) > 99:
                    self.measureCount['recent_uploads'].pop(0)
                self.measureCount['recent_uploads'].append(uploadSize)
                self.measureCount['uploaded'] += uploadSize
                if alertPlugin != None:
                    a = alertPlugin.mailer.getAlerts('Server', [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                    alertPlugin.mailer.removeAlerts(a)
                    alertPlugin.mailer.addAlert(olof.plugins.alert.Alert('Server', [],
                        olof.plugins.alert.Alert.Type.MoveUploadRestored, info=1, warning=None, alert=None,
                        fire=None))
            else:
                self.plugin.logger.logError("Upload failed: %s" % str(r))
                self.measureCount['failed_uploads'] += 1
                if alertPlugin != None:
                    a = alertPlugin.mailer.getAlerts('Server', [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                    if len(a) < 1:
                        alertPlugin.mailer.addAlert(olof.plugins.alert.Alert('Server', [],
                            olof.plugins.alert.Alert.Type.MoveUploadFailed, message=str(r)))

        if self.requestRunning or not self.plugin.config.getValue('upload_enabled'):
            return

        m = ""
        if False in self.scanners.values():
            self.getScanners()

        to_delete = []
        m_scanner = []
        self.measurements_uploaded = {}
        self.plugin.logger.logInfo("Posting measurements")
        linecount = 0
        for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
            and s in self.measurements)]:
            self.measurements_uploaded[scanner] = copy.deepcopy(self.measurements[scanner])

            if len(self.measurements_uploaded[scanner]) > 0:
                self.plugin.logger.logInfo("Adding %i measurements for scanner %s" % (len(
                    self.measurements_uploaded[scanner]), scanner))
                linecount += len(self.measurements_uploaded[scanner])
                m_scanner.append("==%s" % scanner)
                m_scanner.append("\n".join(self.measurements_uploaded[scanner]))
                to_delete.append((scanner, len(self.measurements_uploaded[scanner])))

        m = '\n'.join(m_scanner)
        if len(m) > 0:
            self.requestRunning = True
            self.plugin.logger.logInfo("Sending request with %i lines" % linecount)
            self.requestPost('measurement', process, m,
                {'Content-Type': 'text/plain'})

class Plugin(olof.core.Plugin):
    """
    Main Move plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation. Read previously saved data from disk and create Connection.

        @param   server (Olof)   Reference to main Olof server instance.
        """
        olof.core.Plugin.__init__(self, server, filename, "Move")
        self.buffer = []
        self.last_session_id = None
        self.conn = None

        measureCount = {'last_upload': -1,
                        'uploads': 0,
                        'uploaded': 0,
                        'failed_uploads': 0,
                        'recent_uploads': []}

        self.measureCount = self.storage.loadObject('measureCount', measureCount)
        self.measurements = self.storage.loadObject('measurements', {})
        self.locations = self.storage.loadObject('locations', {})

        self.setupConnection()

    def setupConnection(self, value=None):
        """
        Setup the Move API REST connection.
        """
        url = self.config.getValue('url')
        user = self.config.getValue('username')
        password = self.config.getValue('password')

        if None not in [url, user, password]:
            self.conn = Connection(self, url, user, password, self.measurements, self.measureCount, self.locations)
        else:
            self.conn = None

    def defineConfiguration(self):
        options = []

        o = olof.configuration.Option('url')
        o.setDescription('Base URL of the MOVE REST API.')
        o.addCallback(self.setupConnection)
        options.append(o)

        o = olof.configuration.Option('username')
        o.setDescription('Username to use for logging in.')
        o.addCallback(self.setupConnection)
        options.append(o)

        o = olof.configuration.Option('password')
        o.setDescription('Password to use for logging in.')
        o.addCallback(self.setupConnection)
        options.append(o)

        o = olof.configuration.Option('upload_enabled')
        o.setDescription('Whether uploading to the MOVE database is enabled.')
        o.addValue(olof.configuration.OptionValue(True, default=True))
        o.addValue(olof.configuration.OptionValue(False))
        options.append(o)

        return options

    def unload(self, shutdown=False):
        """
        Unload. Save cache to disk.
        """
        olof.core.Plugin.unload(self)
        if self.conn != None:
            self.conn.unload()
            self.storage.storeObject(self.conn.measureCount, 'measureCount')
            self.storage.storeObject(self.conn.measurements, 'measurements')
            self.storage.storeObject(self.conn.locations, 'locations')

    def getStatus(self):
        """
        Return the current status of the Move plugin and cache. For use in the status plugin.
        """
        r = []
        now = time.time()
        m = self.conn.measureCount

        if self.conn == None:
            r.append({'status': 'error'})
            r.append({'id': 'error', 'str': 'API details missing'})
            return r

        if self.config.getValue('upload_enabled') == False:
            r.append({'status': 'disabled'})
            r.append({'id': 'uploading disabled'})
        elif m['last_upload'] < 0:
            r.append({'status': 'error'})
        elif (now - m['last_upload']) > 60*2:
            r.append({'status': 'error'})
        elif self.conn.lastError != None:
            r.append({'status': 'error'})
        else:
            r.append({'status': 'ok'})

        if self.conn.lastError != None:
            r.append({'id': 'error', 'str': self.conn.lastError.lower()})

        if m['last_upload'] > 0:
            r.append({'id': 'last upload', 'time': m['last_upload']})
        elif m['last_upload'] < 0 and self.conn.lastError == None:
            r.append({'id': 'no upload'})

        tU = m['uploads'] + m['failed_uploads']
        if tU > 0:
            r.append({'id': 'hitrate',
                      'str': '%0.2f %%' % (((m['uploads'] * 1.0) / tU) * 100)})

        cache = sum(len(self.measurements[i]) for i in self.measurements)
        if cache > 0:
            r.append({'id': 'cached', 'int': cache})

        if self.conn.lastError == None:
            if m['uploads'] > 0:
                r.append({'id': '<span title="Average upload size; total number of uploads">average upload</span>',
                          'int': (m['uploaded'] / m['uploads'])})

            if len(m['recent_uploads']) > 0:
                r.append(
                    {'id': '<span title="Average upload size; 100 most recent uploads">recent average upload</span>',
                     'int': (sum(m['recent_uploads']) / len(m['recent_uploads']))})

        return r

    def locationUpdate(self, hostname, projects, module, obj):
        """
        Handle location updates.
        """
        if self.conn == None:
            return

        if module == 'scanner':
            for sensor in obj.sensors.values():
                if sensor.start != None:
                    desc = ' - '.join([i for i in [obj.name, obj.description] if i != None])
                    self.conn.addLocation(sensor.mac, sensor.start, (sensor.lon, sensor.lat), desc)
                if sensor.end != None:
                    desc = ' - '.join([i for i in [obj.name, obj.description] if i != None])
                    self.conn.addLocation(sensor.mac, sensor.end, None, desc)

        elif module == 'sensor' and obj.mac != None:
            if (obj.lat == None or obj.lon == None) and obj.end != None:
                timestamp = obj.end
                desc = ' - '.join([i for i in [obj.location.name, obj.location.description] if i != None])
                self.conn.addLocation(obj.mac, timestamp, (obj.lon, obj.lat), desc)
            elif (obj.lat != None and obj.lon != None) and obj.start != None:
                timestamp = obj.start
                desc = ' - '.join([i for i in [obj.location.name, obj.location.description] if i != None])
                self.conn.addLocation(obj.mac, timestamp, (obj.lon, obj.lat), desc)

    def dataFeedRssi(self, hostname, projects, timestamp, sensorMac, mac, rssi):
        """
        Add measurements when RSSI data is received.
        """
        if self.conn != None:
            deviceclass = self.server.getDeviceclass(mac)
            self.conn.addMeasurement(sensorMac, timestamp, mac, deviceclass, rssi)
