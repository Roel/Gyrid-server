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
import cPickle as pickle
import os
import time
import urllib2

import olof.configuration
import olof.core
from olof.tools.inotifier import INotifier
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

        self.requestRunning = False
        self.measurements = measurements
        if len(measureCount) == 0:
            self.measureCount = {'uploads': 0, 'cached': 0, 'uploaded': 0,
                'last_upload': -1}
        else:
            self.measureCount = measureCount

        self.locations = locations

        self.task_postM = task.LoopingCall(self.postMeasurements)
        self.task_postM.start(60, now=False)

        self.task_postL = task.LoopingCall(self.postLocations)
        reactor.callLater(40, self.task_postL.start, 60, now=False)

    def getScanners(self):
        """
        Get the list of scanners from the Move database and update local scanner data.

        @return   (str)   Result of the query.
        """
        def process(r):
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
        self.requestPost('scanner', None, '%s,%s' % (mac, description),
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
            self.logger.logInfo("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description,
                coordinates))
        else:
            if not (timestamp, coordinates, description) in [i[0] for i in self.locations[sensor]]:
                self.locations[sensor].append([(timestamp, coordinates, description), False])
                self.logger.logInfo("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description,
                    coordinates))

    def postLocations(self):
        """
        Upload the pending location updates to the Move database.
        """
        def process(r):
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
            self.logger.logInfo("move: Posting location: %s" % l)
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
        self.measurements[sensor].add(','.join([
            time.strftime('%Y%m%d-%H%M%S.%%s-%Z', time.localtime(
            timestamp)) % decSec, mac, str(deviceclass),
            str(rssi)]))
        self.measureCount['cached'] += 1

    def postMeasurements(self):
        """
        Upload pending measurements to the Move database.
        """
        def process(r):
            self.plugin.logger.logInfo("Request done")
            self.requestRunning = False
            if r != None and type(r) is list and len(r) == len(to_delete):
                self.measureCount['uploads'] += 1
                self.measureCount['last_upload'] = int(time.time())
                for i in range(len(r)):
                    scanner = to_delete.pop(0)
                    move_lines = int(r.pop(0).strip().split(',')[1])
                    uploaded_lines = scanner[1]

                    if move_lines == uploaded_lines:
                        self.plugin.logger.logInfo("Upload for scanner %s: OK" % scanner[0])
                        self.measureCount['uploaded'] += uploaded_lines
                        self.measureCount['cached'] -= uploaded_lines
                        for l in self.measurements_uploaded[scanner[0]]:
                            self.measurements[scanner[0]].remove(l)
                    else:
                        self.plugin.logger.logError("Upload for scanner %s: FAIL" % scanner[0])
            else:
                self.plugin.logger.logError("Upload failed: %s" % str(r))

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

        measureCount = {'last_upload': -1,
                        'uploads': 0,
                        'uploaded': 0,
                        'cached': 0}
        measurements = {}
        locations = {}

        if os.path.isfile("olof/plugins/move/measureCount.pickle"):
            f = open("olof/plugins/move/measureCount.pickle", "rb")
            try:
                measureCount = pickle.load(f)
            except:
                pass
            f.close()

        if os.path.isfile("olof/plugins/move/measurements.pickle"):
            f = open("olof/plugins/move/measurements.pickle", "rb")
            try:
                measurements = pickle.load(f)
                for s in measurements:
                    if type(measurements[s]) is not set:
                        measurements[s] = set(measurements[s])
            except:
                pass
            f.close()

        if os.path.isfile("olof/plugins/move/locations.pickle"):
            f = open("olof/plugins/move/locations.pickle", "rb")
            try:
                locations = pickle.load(f)
            except:
                pass
            f.close()

        url = self.config.getValue('url')
        user = self.config.getValue('username')
        password = self.config.getValue('password')

        self.conn = Connection(self, url, user, password, measurements, measureCount, locations)

    def defineConfiguration(self):
        options = set()

        o = olof.configuration.Option('url')
        o.setDescription('Base URL of the MOVE REST API.')
        options.add(o)

        o = olof.configuration.Option('username')
        o.setDescription('Username to use for logging in.')
        options.add(o)

        o = olof.configuration.Option('password')
        o.setDescription('Password to use for logging in.')
        options.add(o)

        o = olof.configuration.Option('upload_enabled')
        o.setDescription('Whether uploading to the MOVE database is enabled.')
        o.addValue(olof.configuration.OptionValue(True, default=True))
        o.addValue(olof.configuration.OptionValue(False))
        options.add(o)

        return options

    def unload(self, shutdown=False):
        """
        Unload. Save cache to disk.
        """
        olof.core.Plugin.unload(self)

        f = open("olof/plugins/move/measureCount.pickle", "wb")
        pickle.dump(self.conn.measureCount, f)
        f.close()

        f = open("olof/plugins/move/measurements.pickle", "wb")
        pickle.dump(self.conn.measurements, f)
        f.close()

        f = open("olof/plugins/move/locations.pickle", "wb")
        pickle.dump(self.conn.locations, f)
        f.close()

    def getStatus(self):
        """
        Return the current status of the Move plugin and cache. For use in the status plugin.
        """
        r = []

        if self.config.getValue('upload_enabled') == False:
            r.append({'status': 'disabled'})
            r.append({'id': 'uploading disabled'})
        elif self.conn.measureCount['last_upload'] < 0:
            r.append({'status': 'error'})
            r.append({'id': 'no upload'})
        else:
            r.append({'status': 'ok'})

        if self.conn.measureCount['last_upload'] > 0:
            r.append({'id': 'last upload', 'time': self.conn.measureCount['last_upload']})

        if self.conn.measureCount['uploaded'] > 0:
            r.append({'id': 'uploaded lines', 'int': self.conn.measureCount['uploaded']})

        if self.conn.measureCount['cached'] > 0:
            r.append({'id': 'cached lines', 'int': self.conn.measureCount['cached']})

        return r

    def locationUpdate(self, hostname, module, obj):
        """
        Handle location updates.
        """
        if module == 'scanner':
            for sensor in obj.sensors.values():
                if sensor.start != None:
                    desc = ' - '.join([i for i in [obj.id, obj.description] if i != None])
                    self.conn.addLocation(sensor.mac, sensor.start, (sensor.lon, sensor.lat), desc)
                if sensor.end != None:
                    desc = ' - '.join([i for i in [obj.id, obj.description] if i != None])
                    self.conn.addLocation(sensor.mac, sensor.end, None, desc)

        elif module == 'sensor':
            if (obj.lat == None or obj.lon == None) and obj.end != None:
                timestamp = obj.end
                desc = ' - '.join([i for i in [obj.location.id, obj.location.description] if i != None])
                self.conn.addLocation(obj.mac, timestamp, (obj.lon, obj.lat), desc)
            elif (obj.lat != None and obj.lon != None) and obj.start != None:
                timestamp = obj.start
                desc = ' - '.join([i for i in [obj.location.id, obj.location.description] if i != None])
                self.conn.addLocation(obj.mac, timestamp, (obj.lon, obj.lat), desc)

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        """
        Add measurements when RSSI data is received.
        """
        deviceclass = self.server.getDeviceclass(mac)
        self.conn.addMeasurement(sensor_mac, timestamp, mac, deviceclass, rssi)
