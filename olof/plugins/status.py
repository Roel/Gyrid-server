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
from twisted.web import resource
from twisted.web import server as tserver
from twisted.web.static import File

import cPickle as pickle
import datetime
import os
import time
import urllib2
import urlparse

import olof.core

def prettydate(d, prefix="", suffix=" ago"):
    t = d
    d = datetime.datetime.fromtimestamp(d)
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days > 7 or diff.days < 0:
        r =  d.strftime('%d %b %y')
    elif diff.days == 1:
        r =  '%s1 day%s' % (prefix, suffix)
    elif diff.days > 1:
        r =  '%s%i days%s' % (prefix, diff.days, suffix)
    elif s <= 1:
        r =  'just now'
    elif s < 60:
        r =  '%s%i seconds%s' % (prefix, s, suffix)
    elif s < 120:
        r =  '%s1 minute%s' % (prefix, suffix)
    elif s < 3600:
        r =  '%s%i minutes%s' % (prefix, s/60, suffix)
    elif s < 7200:
        r =  '%s1 hour%s' % (prefix, suffix)
    else:
        r =  '%s%i hours%s' % (prefix, s/3600, suffix)
    return '<span title="%s">%s</span>' % (time.strftime('%Y%m%d-%H%M%S-%Z',
        time.localtime(t)), r)

class Scanner(object):
    def __init__(self, hostname):
        self.hostname = hostname
        self.host_uptime = None
        self.sensors = {}

        self.conn_ip = None
        self.conn_port = None
        self.conn_time = None
        self.location = None
        self.location_link = None
        self.gyrid_connected = True
        self.gyrid_disconnect_time = None
        self.gyrid_uptime = None

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.last_inquiry = None
        self.last_data = None
        self.connected = False
        self.detections = 0

        self.disconnect_time = None

class RootResource(resource.Resource):
    def __init__(self):
        resource.Resource.__init__(self)

        f = open('olof/plugins/status/html/index.html', 'r')
        self.rendered_page = f.read()
        f.close()

    def render_GET(self, request):
        return self.render_POST(request)

    def render_POST(self, request):
        return self.rendered_page

class ContentResource(resource.Resource):
    def __init__(self, plugin):
        resource.Resource.__init__(self)
        self.plugin = plugin

    def render_server(self):
        html = '<div class="block"><div class="block_title"><h3>Server</h3></div><div class="block_topright"></div>'
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content"><div class="block_data"><img src="static/icons/clock-arrow.png">Uptime<span class="block_data_attr">%s</span></div>' % prettydate(self.plugin.plugin_uptime, suffix="")
        html += '<div class="block_data"><img src="static/icons/puzzle.png">Plugins<span class="block_data_attr">%s</span></div>' % ", ".join(sorted([p.name for p in self.plugin.server.plugins]))
        html += '</div></div>'
        return html

    def render_scanner(self, s):

        def render_location():
            html = '<div class="block_topright">'
            if s.location != None and s.location_link == None:
                html += '%s<img src="static/icons/marker.png">' % s.location
            elif s.location != None:
                html += '<a href="%s">%s</a><img src="static/icons/marker.png">' % (s.location_link, s.location)
            html += '</div>'
            return html

        def render_uptime():
            html = '<div class="block_data"><img src="static/icons/clock-arrow.png">Uptime'
            html += '<span class="block_data_attr"><b>connection</b> %s</span>' % prettydate(int(float(s.conn_time)), suffix="")
            if s.gyrid_uptime != None and s.gyrid_connected == True:
                html += '<span class="block_data_attr"><b>gyrid</b> %s</span>' % prettydate(s.gyrid_uptime, suffix="")
            if s.host_uptime != None:
                html += '<span class="block_data_attr"><b>system</b> %s</span>' % prettydate(s.host_uptime, suffix="")
            html += '</div>'
            return html

        def render_notconnected(disconnect_time, suffix=""):
            html = '<div class="block_data"><img src="static/icons/traffic-cone.png">No connection%s' % suffix
            if disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(disconnect_time)))
            html += '</div>'
            return html

        def render_sensor(sens):
            html = '<div class="block_data">'
            if sens.connected == False:
                html += '<img src="static/icons/plug-disconnect.png">%s' % sens.mac
                if sens.disconnect_time != None:
                    html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(sens.disconnect_time)))
            else:
                html += '<img src="static/icons/bluetooth.png">%s' % sens.mac
                if sens.last_inquiry != None:
                    html += '<span class="block_data_attr"><b>last inquiry</b> %s</span>' % prettydate(int(float(sens.last_inquiry)))
            if sens.last_data != None:
                html += '<span class="block_data_attr"><b>last data</b> %s</span>' % prettydate(int(float(sens.last_data)))
            if sens.detections > 0:
                html += '<span class="block_data_attr"><b>detections</b> %i</span>' % sens.detections
            html += '</div>'
            return html

        html = '<div class="block"><div class="block_title"><h3>%s</h3></div>' % s.hostname
        html += render_location()
        html += '<div style="clear: both;"></div>'

        html += '<div class="block_content">'

        if s.conn_ip != None:
            html += render_uptime()
            if s.gyrid_connected == True:
                for sensor in s.sensors.values():
                    html += render_sensor(sensor)
            else:
                html += render_notconnected(s.gyrid_disconnect_time, " to Gyrid")
        else:
            html += render_notconnected(s.conn_time)

        html += '</div></div>'
        return html

    def render_GET(self, request):
        return self.render_POST(request)

    def render_POST(self, request):
        html = '<div id="title">Gyrid Server status panel</div><div id="updated">%s</div>' % time.strftime('%H:%M:%S')
        html += '<div style="clear: both;"></div>'

        html += self.render_server()

        for s in self.plugin.scanners.values():
            html += self.render_scanner(s)

        return html

class StaticResource(File):
    def __init__(self, path, defaultType='text/html', ignoredExts=(),
        registry=None, allowExt=0):

        File.__init__(self, path, defaultType, ignoredExts, registry, allowExt)

    def directoryListing(self):
        class NoneRenderer:
            def render(self, arg):
                return ""
        return NoneRenderer()

class Plugin(olof.core.Plugin):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server, "Status panel")
        self.root = RootResource()
        self.root.putChild("", self.root)

        self.root.putChild("static",
            StaticResource("olof/plugins/status/static/"))

        self.content = ContentResource(self)
        self.root.putChild("content", self.content)

        if os.path.isfile("olof/plugins/status/data/obj.pickle"):
            f = open("olof/plugins/status/data/obj.pickle", "r")
            self.scanners = pickle.load(f)
            f.close()
            for s in self.scanners.values():
                s.conn_ip = None
                s.conn_port = None
                s.conn_time = None
                for sens in s.sensors.values():
                    sens.connected = False
                    self.disconnect_time = None
        else:
            self.scanners = {}

        self.locations = {}
        self.plugin_uptime = int(time.time())

        f = open("olof/plugins/status/data/locations.txt", "r")
        for line in f:
            line = line.strip().split(',')
            self.locations[line[0]] = [line[1]]
            if len(line) >= 4:
                self.locations[line[0]].extend(line[2:4])
        f.close()

        reactor.listenTCP(8080, tserver.Site(self.root))

    def unload(self):
        f = open("olof/plugins/status/data/obj.pickle", "w")
        pickle.dump(self.scanners, f)
        f.close()

    def getScanner(self, hostname):
        if not hostname in self.scanners:
            s = Scanner(hostname)
            if hostname in self.locations:
                s.location = self.locations[hostname][0]
                if len(self.locations[hostname]) >= 3:
                    s.location_link = "http://www.openstreetmap.org/?mlat=%s&mlon=%s&zoom=15&layers=M" % (
                        self.locations[hostname][1], self.locations[hostname][2])
            self.scanners[hostname] = s
        else:
            s = self.scanners[hostname]
        return s

    def getSensor(self, hostname, mac):
        s = self.getScanner(hostname)
        if not mac in s.sensors:
            sens = Sensor(mac)
            s.sensors[mac] = sens
        else:
            sens = s.sensors[mac]
        return sens

    def uptime(self, hostname, host_uptime, gyrid_uptime):
        s = self.getScanner(hostname)
        s.host_uptime = int(float(host_uptime))
        s.gyrid_uptime = int(float(gyrid_uptime))

    def connectionMade(self, hostname, ip, port):
        s = self.getScanner(hostname)
        s.conn_ip = ip
        s.conn_port = port
        s.conn_time = int(time.time())

    def connectionLost(self, hostname, ip, port):
        s = self.getScanner(hostname)
        s.conn_ip = None
        s.conn_port = None
        s.conn_time = int(time.time())
        for sens in s.sensors.values():
            sens.connected = False

    def sysStateFeed(self, hostname, module, info):
        s = self.getScanner(hostname)
        if module == 'gyrid':
            if info == 'connected':
                s.gyrid_connected = True
            elif info == 'disconnected':
                s.gyrid_connected = False
                s.gyrid_disconnect_time = int(time.time())

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        sens = self.getSensor(hostname, sensor_mac)
        if info == 'new_inquiry':
            sens.connected = True
            if sens.last_inquiry == None or timestamp > sens.last_inquiry:
                sens.last_inquiry = timestamp
        elif info == 'started_scanning':
            sens.connected = True
        elif info == 'stopped_scanning':
            sens.connected = False
            sens.disconnect_time = int(float(timestamp))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        sens = self.getSensor(hostname, sensor_mac)
        sens.detections += 1
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp
