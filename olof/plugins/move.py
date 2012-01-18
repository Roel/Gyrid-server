#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.internet import reactor, task, threads

import copy
import os
import cPickle as pickle
import time
import urllib2

import olof.core
import olof.tools.RestConnection

class Connection(olof.tools.RestConnection):
    def __init__(self, plugin, server, url, user, password, measurements={}, measureCount={},
        locations={}):
        olof.tools.RestConnection.__init__(self, url, 180, user, password, urllib2.HTTPDigestAuthHandler)
        self.plugin = plugin
        self.server = server
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
        def process(r):
            if r != None:
                for s in r:
                    ls = s.strip().split(',')
                    self.scanners[ls[0]] = True
            return r

        self.request_get('scanner', process)

    def addScanner(self, mac, description):
        self.request_post('scanner', None, '%s,%s' % (mac, description),
            {'Content-Type': 'text/plain'})

    def addLocation(self, sensor, timestamp, coordinates, description):
        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        if not sensor in self.locations:
            self.locations[sensor] = [[(timestamp, coordinates, description), False]]
            self.server.output("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description, coordinates))
        else:
            if not (timestamp, coordinates, description) in [i[0] for i in self.locations[sensor]]:
                self.locations[sensor].append([(timestamp, coordinates, description), False])
                self.server.output("move: Adding location for %s at %s: %s (%s)" % (sensor, timestamp, description, coordinates))

    def postLocations(self):
        def process(r):
            if r != None and not 'error' in str(r).lower():
                for scanner in to_delete:
                    for l in self.locations[scanner]:
                        l[1] = True

        if self.requestRunning or not self.plugin.upload_enabled:
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
                        time.localtime(location[0])), '', 'NULL', '']))
            l_scanner.append("\n".join(loc))

        l = '\n'.join(l_scanner)
        if len(l) > 0:
            self.server.output("move: Posting location: %s" % l)
            self.request_post('scanner/location', process, l,
                {'Content-Type': 'text/plain'})

    def addMeasurement(self, sensor, timestamp, mac, deviceclass, rssi):
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
        def process(r):
            print "Request done."
            self.requestRunning = False
            if r != None and type(r) is list and len(r) == len(to_delete):
                self.measureCount['uploads'] += 1
                self.measureCount['last_upload'] = int(time.time())
                for i in range(len(r)):
                    scanner = to_delete.pop(0)
                    move_lines = int(r.pop(0).strip().split(',')[1])
                    uploaded_lines = scanner[1]

                    if move_lines == uploaded_lines:
                        print "Upload for scanner %s: OK" % scanner[0]
                        self.measureCount['uploaded'] += uploaded_lines
                        self.measureCount['cached'] -= uploaded_lines
                        for l in self.measurements_uploaded[scanner[0]]:
                            self.measurements[scanner[0]].remove(l)
                    else:
                        print "Upload for scanner %s: FAIL" % scanner[0]
            else:
                print "Upload failed: %s" % str(r)

        if self.requestRunning or not self.plugin.upload_enabled:
            return

        m = ""
        if False in self.scanners.values():
            self.getScanners()

        to_delete = []
        m_scanner = []
        self.measurements_uploaded = {}
        print "---"
        print "Posting measurements..."
        linecount = 0
        for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
            and s in self.measurements)]:
            self.measurements_uploaded[scanner] = copy.deepcopy(self.measurements[scanner])

            if len(self.measurements_uploaded[scanner]) > 0:
                print "  Adding %i measurements for scanner %s..." % (len(self.measurements_uploaded[scanner]), scanner)
                linecount += len(self.measurements_uploaded[scanner])
                m_scanner.append("==%s" % scanner)
                m_scanner.append("\n".join(self.measurements_uploaded[scanner]))
                to_delete.append((scanner, len(self.measurements_uploaded[scanner])))

        m = '\n'.join(m_scanner)
        if len(m) > 0:
            self.requestRunning = True
            print "Sending request with %i lines..." % linecount
            self.request_post('measurement', process, m,
                {'Content-Type': 'text/plain'})

class Plugin(olof.core.Plugin):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        olof.core.Plugin.__init__(self, server, "Move")
        self.buffer = []
        self.last_session_id = None
        self.upload_enabled = False

        t = task.LoopingCall(self.readConf)
        t.start(10)

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

        self.conn = Connection(self, self.server, self.url, self.user, self.password,
            measurements, measureCount, locations)

    def readConf(self):
        f = open('olof/plugins/move/move.conf', 'r')
        m = {'True': True, 'False': False, 'true': True, 'false': False, '1': True, '0': False}
        for l in f:
            ls = l.strip().split(',')
            ls[1] = m.get(ls[1], ls[1])
            self.__dict__[ls[0]] = ls[1]
        f.close()

    def unload(self):
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
        r = []

        if self.upload_enabled == False:
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
        deviceclass = self.server.getDeviceclass(mac)
        self.conn.addMeasurement(sensor_mac, timestamp, mac, deviceclass, rssi)
