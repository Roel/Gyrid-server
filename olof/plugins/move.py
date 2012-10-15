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
import re
import time
import urllib2

import olof.configuration
import olof.core
import olof.storagemanager

from olof.tools.datetimetools import getRelativeTime
from olof.tools.webprotocols import RESTConnection

class Connection(RESTConnection):
    """
    Class that implements the REST connection with the Move database.
    """
    def __init__(self, plugin, url, user, password, scanners={}, projects={}, measurements={}, measureCount={},
                 locations={}):
        """
        Initialisation.

        Start looping calls that upload measurements and locations.

        @param   plugin (Plugin)       Reference to main Move plugin instance.
        @param   url (str)             Base URL of the Move REST interface.
        @param   user (str)            Username to log in on the server.
        @param   password (str)        Password to log in on the server.
        @param   scanners (dict)       Cached scanners. Optional.
        @param   projects (dict)       Cached projects. Optional.
        @param   measurements (dict)   Cached measurements. Optional.
        @param   measureCount (dict)   Cache statistics. Optional.
        @param   locations (dict)      Cached location data. Optional.
        """
        RESTConnection.__init__(self, url, 180, user, password, urllib2.HTTPDigestAuthHandler)
        self.plugin = plugin
        self.server = self.plugin.server
        self.scanners = scanners
        self.projects = projects
        self.requestRunning = False
        self.lastError = None
        self.measurements = measurements
        self.getProjects(self.getScanners, self.getLocations)

        if len(measureCount) == 0:
            self.measureCount = {'uploads': 0, 'uploaded': 0, 'last_upload': -1, 'failed_uploads': 0,
                'recent_uploads': []}
        else:
            self.measureCount = measureCount
            self.measureCount['recent_uploads'] = self.measureCount['recent_uploads'][-self.plugin.maxRecent:]

        self.locations = locations

        self.task_postM = task.LoopingCall(self.postMeasurements)
        self.task_postL = task.LoopingCall(self.postLocations)
        self.init()

    def init(self):
        """
        Start the looping calls for uploads.
        """
        self.uploadInterval = self.plugin.config.getValue('upload_interval')
        self.task_postM.start(self.uploadInterval, now=False)
        reactor.callLater(int(self.uploadInterval * (2.0/3.0)), self.task_postL.start,
            self.uploadInterval, now=False)

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

    def getScanners(self, callback=None, *args):
        """
        Get the list of scanners from the Move database and update local scanner data.

        @param    callback   Function to call on succesfull request.
        @param    *args      Arguments to pass to the callback function.
        @return   (str)      Result of the query.
        """
        def process(r):
            self.requestRunning = False
            alertPlugin = self.plugin.server.pluginmgr.getPlugin('alert')
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("GET/scanner request failed: %s" % str(r))
                if callback != None:
                    self.measureCount['failed_uploads'] += 1
                    if alertPlugin != None:
                        a = alertPlugin.mailer.getAlerts(self.plugin.filename,
                            [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                        if len(a) < 1 and sum(len(self.measurements[i]) for i in self.measurements) > 0:
                            alertPlugin.mailer.addAlert(olof.plugins.alert.Alert(self.plugin.filename, [],
                                olof.plugins.alert.Alert.Type.MoveUploadFailed, autoexpire=False, message=str(r),
                                info=1, warning=5, alert=10, fire=20))
                return
            else:
                self.lastError = None
            if r != None:
                for s in r:
                    ls = s.strip().split(',')
                    self.scanners[ls[0]] = True
                if callback != None:
                    callback(*args)
            return r

        if self.requestRunning:
            return

        self.requestRunning = True
        self.requestGet('scanner', process)

    def getProjects(self, callback=None, *args):
        """
        Get the list of projects from the Move database and update local project data.

        @param    callback   Function to call on succesfull request.
        @param    *args      Arguments to pass to the callback function.
        @return   (str)      Result of the query.
        """
        def process(r):
            self.requestRunning = False
            alertPlugin = self.plugin.server.pluginmgr.getPlugin('alert')
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("GET/project request failed: %s" % str(r))
                if callback != None:
                    self.measureCount['failed_uploads'] += 1
                    if alertPlugin != None:
                        a = alertPlugin.mailer.getAlerts(self.plugin.filename,
                            [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                        if len(a) < 1 and sum(len(self.measurements[i]) for i in self.measurements) > 0:
                            alertPlugin.mailer.addAlert(olof.plugins.alert.Alert(self.plugin.filename, [],
                                olof.plugins.alert.Alert.Type.MoveUploadFailed, autoexpire=False, message=str(r),
                                info=1, warning=5, alert=10, fire=20))
                return
            else:
                self.lastError = None
            if r != None:
                for s in r:
                    ls = s.strip().split(',')
                    self.projects[ls[0]] = True
                if callback != None:
                    callback(*args)
            return r

        self.requestRunning = True
        self.requestGet('project', process)

    def getLocations(self, callback=None, *args):
        """
        Get the list of locations from the Move database and update local location data.

        @param    callback   Function to call on succesfull request.
        @param    *args      Arguments to pass to the callback function.
        @return   (str)      Result of the query.
        """
        def process(r):
            self.requestRunning = False
            alertPlugin = self.plugin.server.pluginmgr.getPlugin('alert')
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("GET/scanner/location request failed: %s" % str(r))
                if callback != None:
                    self.measureCount['failed_uploads'] += 1
                    if alertPlugin != None:
                        a = alertPlugin.mailer.getAlerts(self.plugin.filename,
                            [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                        if len(a) < 1 and sum(len(self.measurements[i]) for i in self.measurements) > 0:
                            alertPlugin.mailer.addAlert(olof.plugins.alert.Alert(self.plugin.filename, [],
                                olof.plugins.alert.Alert.Type.MoveUploadFailed, autoexpire=False, message=str(r),
                                info=1, warning=5, alert=10, fire=20))
                return
            else:
                self.lastError = None
            if r != None:
                for s in r:
                    ls = s.strip().split(',')
                    t = ls[1]
                    if '.' in t:
                        t = "".join([t[:t.find('.')], t[t.find('.')+4:]])
                    timestamp = time.strftime("%s", time.strptime(t, "%Y%m%d-%H%M%S-%Z"))
                    coord = tuple([float(i) for i in re.split(r'\((.*)\)', ls[2])[1].split()[::-1]])
                    if ls[0] not in self.locations:
                        self.locations[ls[0]] = [[(timestamp, coord, ls[4], ls[5]), True]]
                    else:
                        self.locations[ls[0]].append([(timestamp, coord, ls[4], ls[5]), True])
                if callback != None:
                    callback(*args)
            return r

        self.requestRunning = True
        self.requestGet('scanner/location', process)

    def addScanner(self, mac, description):
        """
        Add a scanner to the Move database.

        @param   mac (str)           Bluetooth MAC-address of the scanner.
        @param   description (str)   Description of the scanner.
        """
        def process(r):
            self.requestRunning = False
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("POST/scanner request failed: %s" % str(r))
            else:
                self.lastError = None
            self.getScanners()

        self.requestRunning = True
        self.requestPost('scanner', process, '%s,%s' % (mac, description.replace(',', '')),
            {'Content-Type': 'text/plain'})

    def addProject(self, id, name):
        """
        Add a project to the Move database.

        @param   id (str)           ID of the project.
        @param   name (str)         Name of the project.
        """
        def process(r):
            self.requestRunning = False
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("POST/project request failed: %s" % str(r))
            else:
                self.lastError = None
            self.getProjects()

        self.requestRunning = True
        self.requestPost('project', process, '%s,%s' % (id, name.replace(',', '')),
            {'Content-Type': 'text/plain'})

    def addLocation(self, sensor, project, timestamp, coordinates, description):
        """
        Add a location to the local location list.

        @param   sensor (str)          MAC-address of the Bluetooth sensor.
        @param   project (Project)     Project of this location.
        @param   timestamp (int)       Timestamp of the time the scanner was added/removed. In UNIX time.
        @param   coordinates (tuple)   Tuple containing the X and Y coordinates of the location respectively.
        @param   description (str)     Description of the location.
        """
        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        if not project.id in self.projects:
            self.addProject(project.id, project.name)
            self.projects[project.id] = False

        if not sensor in self.locations:
            self.locations[sensor] = [[(timestamp, coordinates, description, project.id), False]]
            self.plugin.logger.debug("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description,
                coordinates))
        else:
            if not (timestamp, coordinates, description, project.id) in [i[0] for i in self.locations[sensor]]:
                self.locations[sensor].append([(timestamp, coordinates, description, project.id), False])
                self.plugin.logger.debug("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp,
                    description, coordinates))

    def postLocations(self):
        """
        Upload the pending location updates to the Move database.
        """
        def process(r):
            self.requestRunning = False
            if type(r) is IOError:
                self.lastError = str(r)
                self.plugin.logger.logError("POST/scanner/location request failed: %s" % str(r))
                return
            else:
                self.lastError = None
            if r != None and not 'error' in str(r).lower():
                for scanner in to_delete:
                    for l in self.locations[scanner]:
                        l[1] = True

        if self.requestRunning:
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
                        'EWKT', location[2], location[3]]))
                else:
                    loc.append(','.join([time.strftime('%Y%m%d-%H%M%S-%Z',
                        time.localtime(location[0])), 'NULL', 'NULL', '', 'NULL']))
            l_scanner.append("\n".join(loc))

        l = '\n'.join(l_scanner)
        if len(l) > 0:
            self.plugin.logger.debug("move: Posting location: %s" % l)
            self.requestRunning = True
            self.requestPost('scanner/location', process, l,
                {'Content-Type': 'text/plain'})

    def addMeasurement(self, sensor, project, timestamp, mac, deviceclass, rssi):
        """
        Add a measurement to the local measurement list.

        @param   sensor (str)        MAC-address of the Bluetooth sensor that detected the device.
        @param   project (Project)   Project of the sensor that detected the device.
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

        if not project.id in self.projects:
            self.addProject(project.id, project.name)
            self.projects[project.id] = project.name

        tm = "%0.3f" % timestamp
        decSec = tm[tm.find('.')+1:]
        decSec += "0" * (3-len(decSec))
        self.measurements[sensor].add(','.join([time.strftime('%Y%m%d-%H%M%S.%%s-%Z',
            time.localtime(timestamp)) % decSec, mac, str(deviceclass), str(rssi)]))

    def postMeasurements(self):
        """
        Upload pending measurements to the Move database.
        """
        def upload(*args):
            m = ""
            m_scanner = []
            self.plugin.logger.debug("Posting measurements")
            linecount = 0
            for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
                and s in self.measurements and s in self.locations and \
                (False not in [i[1] for i in self.locations[s]]))]:
                if linecount < max_request_size:
                    mc = copy.deepcopy(self.measurements[scanner])
                    measurements_uploaded[scanner] = set()
                    for l in mc:
                        if linecount < max_request_size:
                            measurements_uploaded[scanner].add(l)
                            linecount += 1

                    if len(measurements_uploaded[scanner]) > 0:
                        self.plugin.logger.debug("Adding %i measurements for scanner %s" % (len(
                            measurements_uploaded[scanner]), scanner))
                        m_scanner.append("==%s" % scanner)
                        m_scanner.append("\n".join(measurements_uploaded[scanner]))
                        to_delete.append((scanner, len(measurements_uploaded[scanner])))

            m = '\n'.join(m_scanner)
            if len(m) > 0:
                self.requestRunning = True
                self.timeRequestStart = time.time()
                self.requestSize = linecount
                self.plugin.logger.debug("Sending request with %i lines" % linecount)
                self.requestPost('measurement', process, m,
                    {'Content-Type': 'text/plain'})

        def process(r):
            self.plugin.logger.debug("Request done")
            self.timeRequestFinish = time.time()
            self.requestRunning = False
            if type(r) is IOError:
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
                        self.plugin.logger.debug("Upload for scanner %s: OK" % scanner[0])
                        uploadSize += uploaded_lines
                        for l in measurements_uploaded[scanner[0]]:
                            self.measurements[scanner[0]].remove(l)
                    else:
                        self.plugin.logger.logError("Upload for scanner %s: FAIL" % scanner[0])
                if len(self.measureCount['recent_uploads']) > (self.plugin.maxRecent - 1):
                    self.measureCount['recent_uploads'].pop(0)
                self.measureCount['recent_uploads'].append(uploadSize)
                self.measureCount['uploaded'] += uploadSize
                success = True
                if alertPlugin != None:
                    a = alertPlugin.mailer.getAlerts(self.plugin.filename,
                        [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                    alertPlugin.mailer.removeAlerts(a)
                    alertPlugin.mailer.addAlert(olof.plugins.alert.Alert(self.plugin.filename, [],
                        olof.plugins.alert.Alert.Type.MoveUploadRestored, info=1, warning=None, alert=None,
                        fire=None))
            else:
                self.plugin.logger.logError("Upload failed: %s" % str(r))
                self.measureCount['failed_uploads'] += 1
                success = False
                if alertPlugin != None:
                    a = alertPlugin.mailer.getAlerts(self.plugin.filename,
                        [olof.plugins.alert.Alert.Type.MoveUploadFailed])
                    if len(a) < 1:
                        alertPlugin.mailer.addAlert(olof.plugins.alert.Alert(self.plugin.filename, [],
                            olof.plugins.alert.Alert.Type.MoveUploadFailed, autoexpire=False, message=str(r),
                            info=1, warning=5, alert=10, fire=20))

            if self.plugin.config.getValue('performance_log'):
                rS = time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(self.timeRequestStart))
                rF = time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(self.timeRequestFinish))
                rD = '%0.3f' % (self.timeRequestFinish - self.timeRequestStart)
                rR = "finished" if success else "failed"
                self.plugin.logger.logInfo("Upload %s: " % rR + ','.join([str(i) for i in \
                    rS, rF, '%0.3f' % self.timeRequestStart, '%0.3f' % self.timeRequestFinish,
                    rD, self.requestSize]))

        if self.requestRunning or not self.plugin.config.getValue('upload_enabled'):
            return

        if sum(len(self.measurements[i]) for i in self.measurements) > 0:
            if self.plugin.config.getValue('performance_log'):
                self.timeRequestStart = self.timeRequestFinish = 0
            to_delete = []
            measurements_uploaded = {}
            max_request_size = self.plugin.config.getValue('max_request_size')
            self.getScanners(upload)

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
        self.maxRecent = 60

        measureCount = {'last_upload': -1,
                        'uploads': 0,
                        'uploaded': 0,
                        'failed_uploads': 0,
                        'recent_uploads': []}

        self.measureCount = self.storage.loadObject('measureCount', measureCount)
        self.measurements = self.storage.loadObject('measurements', {})
        self.locations = self.storage.loadObject('locations', {})
        self.scanners = self.storage.loadObject('scanners', {})
        self.projects = self.storage.loadObject('projects', {})

        self.setupConnection()

    def setupConnection(self, value=None):
        """
        Setup the Move API REST connection.
        """
        url = self.config.getValue('url')
        user = self.config.getValue('username')
        password = self.config.getValue('password')
        scanners = dict(zip(self.scanners.keys(), [False] * len(self.scanners)))
        projects = dict(zip(self.projects.keys(), [False] * len(self.projects)))

        if None not in [url, user, password]:
            self.conn = Connection(self, url, user, password, scanners, projects, self.measurements, self.measureCount,
                self.locations)
        else:
            self.conn = None

    def restartUploads(self, value=None):
        """
        Restart the uploads looping calls, f.ex. after updating the upload interval.
        """
        if value == None:
            value = self.config.getValue('upload_interval')

        if self.conn:
            self.logger.debug("Restarting uploads; using an interval of %i seconds" % value)
            self.conn.unload()
            self.conn.init()

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

        o = olof.configuration.Option('max_request_size')
        o.setDescription('The maximum number of detections that can be uploaded in one request.')
        o.addValue(olof.configuration.OptionValue(200000, default=True))
        options.append(o)

        o = olof.configuration.Option('upload_interval')
        o.setDescription('The amount of seconds between two successive uploads; i.e. the time ' + \
            'between the start of an upload and the start of the next one.')
        o.addValue(olof.configuration.OptionValue(60, default=True))
        o.addCallback(self.restartUploads)
        options.append(o)

        o = olof.configuration.Option('upload_enabled')
        o.setDescription('Whether uploading detections to the MOVE database is enabled.')
        o.addValue(olof.configuration.OptionValue(True, default=True))
        o.addValue(olof.configuration.OptionValue(False))
        options.append(o)

        o = olof.configuration.Option('caching_enabled')
        o.setDescription('Whether adding detections to the cache and the MOVE database is enabled. ' + \
            'When this is False, only location and scanner updates are stored and pushed. ' + \
            'This is potentially dangerous, be careful!')
        o.addValue(olof.configuration.OptionValue(True, default=True))
        o.addValue(olof.configuration.OptionValue(False))
        options.append(o)

        o = olof.configuration.Option('performance_log')
        o.setDescription('Whether the performance (i.e. the time it takes for an upload request to finish) ' + \
            'should be logged.')
        o.addValue(olof.configuration.OptionValue(True))
        o.addValue(olof.configuration.OptionValue(False, default=True))
        options.append(o)

        return options

    def unload(self, shutdown=False):
        """
        Unload. Save cache to disk.
        """
        olof.core.Plugin.unload(self, shutdown)
        if self.conn != None:
            self.conn.unload()
            self.storage.storeObject(self.conn.measureCount, 'measureCount')
            self.storage.storeObject(self.conn.measurements, 'measurements')
            self.storage.storeObject(self.conn.locations, 'locations')
            self.storage.storeObject(self.conn.scanners, 'scanners')
            self.storage.storeObject(self.conn.projects, 'projects')

    def getStatus(self):
        """
        Return the current status of the Move plugin and cache. For use in the status plugin.
        """
        r = []

        if self.conn == None:
            r.append({'status': 'error'})
            r.append({'id': 'error', 'str': 'API details missing'})
            return r

        m = self.conn.measureCount
        cache = sum(len(self.measurements[i]) for i in self.measurements)
        now = time.time()

        if self.config.getValue('upload_enabled') == False or self.config.getValue('caching_enabled') == False:
            r.append({'status': 'disabled'})
            if self.config.getValue('upload_enabled') == False:
                r.append({'id': 'upload', 'str': 'disabled'})
            if self.config.getValue('caching_enabled') == False:
                r.append({'id': 'caching', 'str': 'disabled'})

        elif cache > 0 and (now - m['last_upload']) > (self.conn.uploadInterval*5):
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
            r.append({'id': '<span title="%i out of %i uploads failed">hitrate</span>' % (
                                m['failed_uploads'], tU),
                      'str': '%0.2f %%' % (((m['uploads'] * 1.0) / tU) * 100)})

        firstData = None
        if cache <= (self.config.getValue('max_request_size') / 4): # Too CPU intensive for big cache.
            firstData = time.localtime()
            for s in self.measurements.values():
                for l in s:
                    t = time.strptime(l[:15] + l[19:l.find(',')], "%Y%m%d-%H%M%S-%Z")
                    firstData = min(t, firstData)

        if cache > 0:
            if firstData != None:
                r.append({'id': '<span title="Data since: %s – %s">cached</span>' % (
                                    time.strftime("%a %Y-%m-%d %H:%M:%S", firstData),
                                    getRelativeTime(int(time.strftime("%s", firstData)))),
                          'int': cache})
            else:
                r.append({'id': 'cached', 'int': cache})


        if self.conn.lastError == None and self.config.getValue('upload_enabled') == True:
            if m['uploads'] > 0:
                r.append({'id': '<span title="Average upload size; total number of uploads">average upload</span>',
                          'int': (m['uploaded'] / m['uploads'])})

            if len(m['recent_uploads']) > 0:
                r.append(
                    {'id': '<span title="Average upload size; %i most recent uploads">recent average upload</span>' % \
                                self.maxRecent,
                     'int': (sum(m['recent_uploads']) / len(m['recent_uploads']))})

        return r

    def locationUpdate(self, hostname, projects, module, obj):
        """
        Handle location updates.
        """
        if self.conn == None:
            return

        for project in projects:
            if module == 'scanner':
                for sensor in obj.sensors.values():
                    if sensor.start != None:
                        desc = ' - '.join([i for i in [obj.name, obj.description] if i != None])
                        self.conn.addLocation(sensor.mac, project, sensor.start, (sensor.lon, sensor.lat), desc)
                    if sensor.end != None:
                        desc = ' - '.join([i for i in [obj.name, obj.description] if i != None])
                        self.conn.addLocation(sensor.mac, project, sensor.end, None, desc)

            elif module == 'sensor' and obj.mac != None:
                if (obj.lat == None or obj.lon == None) and obj.end != None:
                    timestamp = obj.end
                    desc = ' - '.join([i for i in [obj.location.name, obj.location.description] if i != None])
                    self.conn.addLocation(obj.mac, project, timestamp, (obj.lon, obj.lat), desc)
                elif (obj.lat != None and obj.lon != None) and obj.start != None:
                    timestamp = obj.start
                    desc = ' - '.join([i for i in [obj.location.name, obj.location.description] if i != None])
                    self.conn.addLocation(obj.mac, project, timestamp, (obj.lon, obj.lat), desc)

    def dataFeedRssi(self, hostname, projects, timestamp, sensorMac, mac, rssi):
        """
        Add measurements when RSSI data is received.
        """
        if self.conn != None and self.config.getValue('caching_enabled') == True:
            deviceclass = self.server.getDeviceclass(mac)
            for project in projects:
                self.conn.addMeasurement(sensorMac, project, timestamp, mac, deviceclass, rssi)
