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
        self.conn_time = None
        self.location = None
        self.location_link = None

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.last_inquiry = None
        self.last_data = None
        self.datalines = 0

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
        html += '<div class="block_content"><div class="block_data"><img src="static/icons/clock-arrow.png">Started<span class="block_data_attr">%s</span></div>' % prettydate(self.plugin.uptime)
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

        def render_net():
            html = '<img src="static/icons/network-ip.png">'
            if s.conn_ip and s.conn_port:
                html += '%s - %s<span class="block_data_attr"><b>connected</b> %s</span>' % (s.conn_ip, s.conn_port,
                    prettydate(int(float(s.conn_time))))
            elif s.conn_ip == None:
                html += 'No connection.<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(s.conn_time)))
            return html

        def render_sensor(sens):
            html = '<div class="block_data"><img src="static/icons/bluetooth.png">%s' % sens.mac
            if sens.last_inquiry != None:
                html += '<span class="block_data_attr"><b>last inquiry</b> %s</span>' % prettydate(int(float(sens.last_inquiry)))
            if sens.last_data != None:
                html += '<span class="block_data_attr"><b>last data</b> %s</span>' % prettydate(int(float(sens.last_data)))
            if sens.datalines > 0:
                html += '<span class="block_data_attr"><b>datalines</b> %i</span>' % sens.datalines
            html += '</div>'
            return html

        html = '<div class="block"><div class="block_title"><h3>%s</h3></div>' % s.hostname
        html += render_location()
        html += '<div style="clear: both;"></div>'

        html += '<div class="block_content">'
        html += render_net()

        if s.conn_ip != None:
            for sens in s.sensors.values():
                html += render_sensor(sens)

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

        self.scanners = {}
        self.locations = {}
        self.uptime = int(time.time())

        f = open("olof/plugins/status/data/locations.txt", "r")
        for line in f:
            line = line.strip().split(',')
            self.locations[line[0]] = [line[1]]
            if len(line) >= 4:
                self.locations[line[0]].extend(line[2:4])
        f.close()

        reactor.listenTCP(8080, tserver.Site(self.root))

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

    def infoFeed(self, hostname, timestamp, info):
        pass

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        if info == 'new_inquiry':
            sens = self.getSensor(hostname, sensor_mac)
            if sens.last_inquiry == None or timestamp > sens.last_inquiry:
                sens.last_inquiry = timestamp

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        sens = self.getSensor(hostname, sensor_mac)
        sens.datalines += 1
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp
