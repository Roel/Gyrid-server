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

class Connection:
    def __init__(self, base_url, username=None, password=None):
        self.base_url = base_url
        self.username = username

        self.url = urlparse.urlparse(base_url)

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

    def request_post(self, resource, body = None, headers={}):
        return self.request(resource, "post", body = body, headers=headers)

    def request_put(self, resource, body = None, headers={}):
        return self.request(resource, "put", body = body, headers=headers)

    def request(self, resource, method = "get", body = None, headers={}):
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

class Plugin(object):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server):
        """
        Initialisation.

        @param   mgr   Reference to ScanManager instance.
        """
        self.server = server
        self.mac_dc = {}
        self.buffer = []
        self.last_session_id = None

        url = 'http://move.ugent.be:8080/bluemap/api'
        self.conn = Connection(url, '00:00:00:00:00:00', '3fe0b7f12634e47f')

        l = task.LoopingCall(reactor.callInThread, self.send)
        l.start(60, now=False)

    def connectionMade(self, hostname, ip, port):
        pass

    def connectionLost(self, hostname, ip, port):
        pass

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        if move == 'in':
            self.mac_dc[mac] = deviceclass
        elif move == 'out':
            if mac in self.mac_dc:
                del(self.mac_dc[mac])

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        self.buffer.append(','.join([time.strftime('%Y%m%d-%H%M%S-%Z',
            time.localtime(float(timestamp))), mac, self.mac_dc.get(
            mac, "-1"), str(rssi)]))

    def send(self):
        if len(self.buffer) > 0:
            self.server.prints("Sending data:")
            for i in self.buffer:
                self.server.prints("  > %s" % i)
            try:
                buff = list(self.buffer)
                res = self.conn.request_post('measurement',
                    body = '\n'.join(buff),
                    headers = {'Content-Type': 'text/plain'})
                self.server.prints("Upload to Move..." % res)
                if len(res) == 1:
                    res = res[0].split(',')
                    #if (self.last_session_id != None and \
                    #res[0] == self.last_session_id + 1) and \
                    if int(res[1]) == len(buff):
                        #self.last_session_id = int(res[0])
                        self.server.prints("Upload succeeded, clearing buffer.")
                        [self.buffer.remove(i) for i in buff]
                    else:
                        self.server.prints("Upload failed, not everyting is transferred.")
                    #elif self.last_session_id == None:
                    #    self.last_session_id = int(res[0])
                    #    [self.buffer.remove(i) for i in buff]
                else:
                    self.server.prints("Upload failed.")
            except IOError:
                self.server.prints("Upload failed, IOError.")
            except:
                self.server.prints("Upload failed, exception raised.")

        #self.buffer[:] = []
