#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
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
import urlparse

import olof.core
from olof.locationprovider import Location

class ExtRequest(urllib2.Request):
    method = None

    def set_method(self, method):
        self.method = method

    def get_method(self):
        if self.method is None:
            if self.has_data():
                return "POST"
            else:
                return "GET"
        else:
            return self.method

class RawConnection(object):
    def __init__(self, base_url, timeout=40, username=None, password=None, authHandler=None):
        self.base_url = base_url
        self.timeout = timeout
        self.username = username
        self.url = urlparse.urlparse(base_url)

        if username and password and authHandler:
            passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
            passman.add_password(None, self.base_url, username, password)
            self.opener = urllib2.build_opener(authHandler(passman))
        else:
            self.opener = None

        self.returns = {}
        self.returnCount = 0

        (scheme, netloc, path, query, fragment) = urlparse.urlsplit(base_url)

        self.scheme = scheme
        self.host = netloc
        self.path = path

    def request_get(self, resource, cb=None, headers={}):
        self.request(cb, resource, "get", headers=headers)

    def request_delete(self, resource, cb=None, headers={}):
        self.request(cb, resource, "delete", headers=headers)

    def request_head(self, resource, cb=None, headers={}):
        self.request(cb, resource, "head", headers=headers)

    def request_post(self, resource, cb=None, body=None, headers={}):
        self.request(cb, resource, "post", body=body, headers=headers)

    def request_put(self, resource, cb=None, body=None, headers={}):
        self.request(cb, resource, "put", body=body, headers=headers)

    def request(self, callback, resource, method="get", body=None, headers={}):
        d = threads.deferToThread(self.__request, resource, method, body, headers)
        if callback != None:
            d.addCallback(callback)

    def __request(self, resource, method="get", body=None, headers={}):
        if resource.startswith('/'):
            req = ExtRequest(self.base_url+resource)
        else:
            req = ExtRequest(self.base_url+'/'+resource)

        req.set_method(method.upper())
        req.add_data(body)
        for i in headers.iteritems():
            req.add_header(i[0],i[1])

        try:
            if self.opener:
                resp = self.opener.open(req, timeout=self.timeout)
            else:
                resp = urllib2.urlopen(req, timeout=self.timeout)
            return resp.readlines()
        except:
            return None

class Connection(RawConnection):
    def __init__(self, server, url, user, password, measurements={}, measureCount={},
        locations={}):
        RawConnection.__init__(self, url, 180, user, password, urllib2.HTTPDigestAuthHandler)
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
            self.measurements[sensor] = []

        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        tm = str(timestamp)
        decSec = tm[tm.find('.')+1:]
        decSec += "0" * (3-len(decSec))
        self.measurements[sensor].append(','.join([
            time.strftime('%Y%m%d-%H%M%S.%%s-%Z', time.localtime(
            timestamp)) % decSec, mac, str(deviceclass),
            str(rssi)]))
        self.measureCount['cached'] += 1

    def postMeasurements(self):
        def process(r):
            self.requestRunning = False
            if r != None and type(r) is list and len(r) == len(to_delete):
                self.measureCount['uploads'] += 1
                self.measureCount['last_upload'] = int(time.time())
                for i in range(len(r)):
                    scanner = to_delete.pop(0)
                    move_lines = int(r.pop(0).strip().split(',')[1])
                    uploaded_lines = scanner[1]

                    if move_lines == uploaded_lines:
                        self.measureCount['uploaded'] += uploaded_lines
                        self.measureCount['cached'] -= uploaded_lines
                        for l in self.measurements_uploaded[scanner[0]]:
                            self.measurements[scanner[0]].remove(l)

        if self.requestRunning:
            return

        m = ""
        if False in self.scanners.values():
            self.getScanners()

        to_delete = []
        m_scanner = []
        self.measurements_uploaded = {}
        for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
            and s in self.measurements)]:
            self.measurements_uploaded[scanner] = copy.deepcopy(self.measurements[scanner])
            if len(self.measurements_uploaded[scanner]) > 0:
                m_scanner.append("==%s" % scanner)
                m_scanner.append("\n".join(self.measurements_uploaded[scanner]))
                to_delete.append((scanner, len(self.measurements_uploaded[scanner])))

        m = '\n'.join(m_scanner)
        if len(m) > 0:
            self.requestRunning = True
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

        f = open('olof/plugins/move/move.conf', 'r')
        for l in f:
            ls = l.strip().split(',')
            self.__dict__[ls[0]] = ls[1]
        f.close()

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

        self.conn = Connection(self.server, self.url, self.user, self.password,
            measurements, measureCount, locations)

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

        if self.conn.measureCount['last_upload'] < 0:
            r.append({'status': 'error'})
            r.append({'id': 'no upload'})

        if self.conn.measureCount['last_upload'] > 0:
            r.append({'id': 'last upload', 'time': self.conn.measureCount['last_upload']})

        if self.conn.measureCount['uploaded'] > 0:
            r.append({'id': 'uploaded lines', 'int': self.conn.measureCount['uploaded']})

        if self.conn.measureCount['cached'] > 0:
            r.append({'id': 'cached lines', 'int': self.conn.measureCount['cached']})

        return r

    def locationUpdate(self, hostname, module, timestamp, id, description, coordinates):
        if module == 'sensor':
            return

        elif module == 'scanner':
            for sensor in self.server.location_provider.new_locations[hostname][Location.Sensors]:
                if sensor != Location.Sensor:
                    if Location.TimeInstall in self.server.location_provider.new_locations[hostname][Location.Times]:
                        self.conn.addLocation(sensor, float(time.strftime('%s', time.strptime(
                            self.server.location_provider.new_locations[hostname][Location.Times][Location.TimeInstall],
                            '%Y%m%d-%H%M%S-%Z'))),
                            (self.server.location_provider.new_locations[hostname][Location.Sensors][sensor][Location.X],
                             self.server.location_provider.new_locations[hostname][Location.Sensors][sensor][Location.Y]),
                            '%s - %s' % (self.server.location_provider.new_locations[hostname][Location.ID],
                            self.server.location_provider.new_locations[hostname][Location.Description]))
                    if Location.TimeUninstall in self.server.location_provider.new_locations[hostname][Location.Times]:
                        self.conn.addLocation(sensor,
                            float(time.strftime('%s', time.strptime(
                            self.server.location_provider.new_locations[hostname][Location.Times][Location.TimeUninstall],
                            '%Y%m%d-%H%M%S-%Z'))),
                            None, '%s - %s' % (self.server.location_provider.new_locations[hostname][Location.ID],
                            self.server.location_provider.new_locations[hostname][Location.Description]))

        else:
            self.conn.addLocation(module, timestamp, coordinates, '%s - %s' % (id, description))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        deviceclass = self.server.getDeviceclass(mac)
        self.conn.addMeasurement(sensor_mac, timestamp, mac, deviceclass, rssi)
