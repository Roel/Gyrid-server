#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.internet import reactor, task

import time
import urllib2
import urlparse

import olof.core

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
    def __init__(self, base_url, username=None, password=None):
        self.base_url = base_url
        self.username = username
        self.url = urlparse.urlparse(base_url)
        
        self.returns = {}
        self.returnCount = 0

        (scheme, netloc, path, query, fragment) = urlparse.urlsplit(base_url)

        self.scheme = scheme
        self.host = netloc
        self.path = path

        if username and password:
            passman = urllib2.HTTPPasswordMgrWithDefaultRealm()
            passman.add_password(None, base_url, username, password)
            authhandler = urllib2.HTTPDigestAuthHandler(passman)
            opener = urllib2.build_opener(authhandler)
            urllib2.install_opener(opener)

    def request_get(self, resource, headers={}):
        return self.request(resource, "get", headers=headers)

    def request_delete(self, resource, headers={}):
        return self.request(resource, "delete", headers=headers)

    def request_head(self, resource, headers={}):
        return self.request(resource, "head", headers=headers)

    def request_post(self, resource, body=None, headers={}):
        return self.request(resource, "post", body=body, headers=headers)

    def request_put(self, resource, body=None, headers={}):
        return self.request(resource, "put", body=body, headers=headers)

    def request(self, resource, method="get", body=None, headers={}):
        if resource.startswith('/'):
            req = ExtRequest(self.base_url+resource)
        else:
            req = ExtRequest(self.base_url+'/'+resource)

        req.set_method(method.upper())
        req.add_data(body)
        for i in headers.iteritems():
            req.add_header(i[0],i[1])

        try:
            resp = urllib2.urlopen(req)
            return resp.readlines()
        except IOError, e:
            return e.readlines()

class Connection(RawConnection):
    def __init__(self, url, user, password):
        RawConnection.__init__(self, url, user, password)
        self.scanners = {}
        self.getScanners()

        self.measurements = {}
        self.measureCount = {'uploads': 0, 'cached': 0, 'uploaded': 0,
            'last_upload': -1}

        t = task.LoopingCall(reactor.callInThread, self.postMeasurements)
        t.start(60, now=False)

    def getScanners(self):
        scanners = self.request_get('scanner')
        for s in scanners:
            ls = s.strip().split(',')
            self.scanners[ls[0]] = True

        return scanners

    def addScanner(self, mac, description):
        self.request_post('scanner', '%s,%s' % (mac, description),
            {'Content-Type': 'text/plain'})

    def addMeasurement(self, sensor, timestamp, mac, deviceclass, rssi):
        if not sensor in self.measurements:
            self.measurements[sensor] = []

        if not sensor in self.scanners:
            self.addScanner(sensor, 'test scanner')
            self.scanners[sensor] = False

        self.measurements[sensor].append(','.join([
            time.strftime('%Y%m%d-%H%M%S-%Z', time.localtime(float(timestamp))),
            mac, str(deviceclass), str(rssi)]))
        self.measureCount['cached'] += 1

    def postMeasurements(self):
        m = ""
        if False in self.scanners.values():        
            self.getScanners()

        to_delete = []
        for scanner in [s for s in self.scanners.keys() if (self.scanners[s] == True \
            and s in self.measurements)]:
            if len(self.measurements[scanner]) > 0:
                m += "==%s\n" % scanner
                m += "\n".join(self.measurements[scanner])
                to_delete.append(scanner)

        if len(m) > 0:
            try:
                self.request_post('measurement', m,
                    {'Content-Type': 'text/plain'})
            except:
                pass
            else:
                self.measureCount['uploads'] += 1
                self.measureCount['last_upload'] = int(time.time())
                for i in to_delete:
                    self.measureCount['uploaded'] += len(self.measurements[i])
                    self.measureCount['cached'] -= len(self.measurements[i])
                    self.measurements[i] = []


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
        self.mac_dc = {}
        self.buffer = []
        self.last_session_id = None


        f = open('olof/plugins/move/move.conf', 'r')
        for l in f:
            ls = l.strip().split(',')
            self.__dict__[ls[0]] = ls[1]
        f.close()

        self.conn = Connection(self.url, self.user, self.password)

    def getStatus(self):
        r = []
        if self.conn.measureCount['last_upload'] > 0:
            r.append({'id': 'last upload', 'time': self.conn.measureCount['last_upload']})

        if self.conn.measureCount['uploaded lines'] > 0:
            r.append({'id': 'uploaded lines', 'str': str(self.conn.measureCount['uploaded'])})

        r.append({'id': 'cached lines', 'str': str(self.conn.measureCount['cached'])})
        return r

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        if move == 'in':
            self.mac_dc[mac] = deviceclass
        elif move == 'out':
            if mac in self.mac_dc:
                del(self.mac_dc[mac])

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        if mac in self.mac_dc:
            deviceclass = self.mac_dc[mac]
        else:
            deviceclass = -1

        self.conn.addMeasurement(sensor_mac, timestamp, mac, deviceclass, rssi)
