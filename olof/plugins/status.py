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

import datetime
import time
import urllib2
import urlparse

import olof.core

def prettydate(d):
    d = datetime.datetime.fromtimestamp(d)
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days > 7 or diff.days < 0:
        return d.strftime('%d %b %y')
    elif diff.days == 1:
        return '1 day ago'
    elif diff.days > 1:
        return '%i days ago' % (diff.days)
    elif s <= 1:
        return 'just now'
    elif s < 60:
        return '%i seconds ago' % (s)
    elif s < 120:
        return '1 minute ago'
    elif s < 3600:
        return '%i minutes ago' % (s/60)
    elif s < 7200:
        return '1 hour ago'
    else:
        return '%i hours ago' % (s/3600)

class Scanner(object):
    def __init__(self, hostname):
        self.hostname = hostname
        self.sensors = {}

        self.conn_ip = None
        self.conn_port = None
        self.conn_uptime = None
        self.location = None

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.last_inquiry = None
        self.last_data = None

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

    def render_GET(self, request):
        return self.render_POST(request)

    def render_POST(self, request):
        html = '<div id="title">Gyrid Server status panel</div><div id="updated">%s</div>' % time.strftime('%H:%M:%S')
        html += '<div style="clear: both;"></div>'

        html += '<div class="scanner"><div class="scanner_name"><h3>Server</h3></div>'
        html += '<div style="clear: both;"></div>'
        html += '<div class="scanner_content"><div class="sensor"><img src="static/icons/clock-arrow.png">Started<span class="time">%s</span></div>' % prettydate(self.plugin.uptime)
        html += '<div class="sensor"><img src="static/icons/puzzle.png">Plugins<span class="time">%s</span></div>' % ", ".join(sorted([p.name for p in self.plugin.server.plugins]))
        html += '</div></div>'

        for s in self.plugin.scanners.values():
            html += '<div class="scanner"><div class="scanner_name"><h3>%s</h3></div>' % s.hostname
            if s.location != None:
                html += '<div class="scanner_location">%s <img src="static/icons/marker.png"></div>' % s.location
            html += '<div style="clear: both;"></div>'
            html += '<div class="scanner_content">'
            if s.conn_ip and s.conn_port:
                html += '<img src="static/icons/network-ip.png">%s - %s<span class="time"><b>connected</b> %s</span>' % (s.conn_ip, s.conn_port,
                    prettydate(int(float(s.conn_time))))
            elif s.conn_ip == None:
                html += '<img src="static/icons/network-ip.png">No connection.<span class="time"><b>disconnected</b> %s</span>' % prettydate(int(float(s.conn_time)))
            for sens in s.sensors.values():
                html += '<div class="sensor"><img src="static/icons/bluetooth.png">%s' % sens.mac
                if sens.last_inquiry != None:
                    html += '<span class="time"><b>last inquiry</b> %s</span>' % prettydate(int(float(sens.last_inquiry)))
                if sens.last_data != None:
                    html += '<span class="time"><b>last data</b> %s</span>' % prettydate(int(float(sens.last_data)))
                html += '</div>'
            html += '</div></div>'
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

        self.scanners = {}
        self.locations = {}
        self.uptime = int(time.time())

        reactor.listenTCP(8080, tserver.Site(self.root))

    def getScanner(self, hostname):
        if not hostname in self.scanners:
            s = Scanner(hostname)
            if hostname in self.locations:
                s.location = self.locations[hostname]
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

    def connectionMade(self, hostname, ip, port):
        f = open("olof/plugins/status/data/locations.txt", "r")
        for line in f:
            line = line.strip().split(',')
            self.locations[line[0]] = line[1]
        f.close()

        s = self.getScanner(hostname)
        s.conn_ip = ip
        s.conn_port = port
        s.conn_time = int(time.time())
        if hostname in self.locations:
            s.location = self.locations[hostname]

    def connectionLost(self, hostname, ip, port):
        s = self.getScanner(hostname)
        s.conn_ip = None
        s.conn_port = None
        s.conn_time = int(time.time())

    def infoFeed(self, hostname, timestamp, info):
        pass

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        if info == 'new_inquiry':
            sens = self.getSensor(hostname, sensor_mac)
            sens.last_inquiry = timestamp

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        sens = self.getSensor(hostname, sensor_mac)
        sens.last_data = timestamp
