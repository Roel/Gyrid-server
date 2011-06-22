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
    if diff.days < 0:
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
    return '<span title="%s">%s</span>' % (time.strftime('%a %Y%m%d-%H%M%S-%Z',
        time.localtime(t)), r)

class Scanner(object):
    def __init__(self, hostname):
        self.hostname = hostname
        self.host_uptime = None
        self.sensors = {}
        self.warnings = []

        self.conn_ip = None
        self.conn_port = None
        self.conn_time = None
        self.location = None
        self.location_link = None
        self.gyrid_connected = True
        self.gyrid_disconnect_time = None
        self.gyrid_uptime = None

    def render(self):

        def render_location():
            html = '<div class="block_topright">'
            if self.location != None and self.location_link == None:
                html += '%s<img src="static/icons/marker.png">' % self.location
            elif self.location != None:
                html += '<a href="%s">%s</a><img src="static/icons/marker.png">' % (self.location_link, self.location)
            html += '</div>'
            return html

        def render_uptime():
            html = '<div class="block_data"><img src="static/icons/clock-arrow.png">Uptime'
            html += '<span class="block_data_attr"><b>connection</b> %s</span>' % prettydate(int(float(self.conn_time)), suffix="")
            if self.gyrid_uptime != None and self.gyrid_connected == True:
                html += '<span class="block_data_attr"><b>gyrid</b> %s</span>' % prettydate(self.gyrid_uptime, suffix="")
            if self.host_uptime != None:
                html += '<span class="block_data_attr"><b>system</b> %s</span>' % prettydate(self.host_uptime, suffix="")
            html += '</div>'
            return html

        def render_notconnected(disconnect_time, suffix=""):
            html = '<div class="block_data"><img src="static/icons/traffic-cone.png">No connection%s' % suffix
            if disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(disconnect_time)))
            html += '</div>'
            return html

        html = '<div class="block"><div class="block_title"><h3><a name="%(h)s">%(h)s</a></h3></div>' % {'h': self.hostname}
        html += render_location()
        html += '<div style="clear: both;"></div>'

        html += '<div class="block_content">'

        if self.conn_ip != None:
            html += render_uptime()
            if self.gyrid_connected == True:
                for sensor in self.sensors.values():
                    html += sensor.render()
            else:
                html += render_notconnected(self.gyrid_disconnect_time, " to Gyrid")
        else:
            html += render_notconnected(self.conn_time)

        html += '</div></div>'
        return html

class Sensor(object):
    def __init__(self, mac):
        self.mac = mac
        self.last_inquiry = None
        self.last_data = None
        self.connected = False
        self.detections = 0

        self.disconnect_time = None

    def render(self):
        html = '<div class="block_data">'
        if self.connected == False:
            html += '<img src="static/icons/plug-disconnect.png">%s' % self.mac
            if self.disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(self.disconnect_time)))
        else:
            html += '<img src="static/icons/bluetooth.png">%s' % self.mac
            if self.last_inquiry != None:
                html += '<span class="block_data_attr"><b>last inquiry</b> %s</span>' % prettydate(int(float(self.last_inquiry)))
        if self.last_data != None:
            html += '<span class="block_data_attr"><b>last data</b> %s</span>' % prettydate(int(float(self.last_data)))
        if self.detections > 0:
            html += '<span class="block_data_attr"><b>detections</b> %i</span>' % self.detections
        html += '</div>'
        return html

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

    def render_warnings(self):
        if len(self.plugin.warnings) == 0:
            return ""

        html = '<div class="block"><div class="block_title"><h3>Warnings</h3></div>'
        html += '<div class="block_topright"></div><div style="clear: both;"></div>'
        html += '<div class="block_content">'
        for w in self.plugin.warnings:
            html += w.render(block="warnings")
        html += '</div></div>'
        return html

    def render_server(self):
        html = '<div class="block"><div class="block_title"><h3>Server</h3></div>'
        html += '<div class="block_topright">%s<img src="static/icons/clock-arrow.png"></div>' % prettydate(self.plugin.plugin_uptime, suffix="")
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'
        if (len(self.plugin.load) > 0 and len([i for i in self.plugin.load if float(i) >= 0.8]) > 0) \
            or int(self.plugin.memfree_mb) <= 128 or float(self.plugin.memfree_pct) <= 10 \
            or self.plugin.diskfree_mb <= 1000:
            html += '<div class="block_data">'
            html += '<img src="static/icons/system-monitor.png">Resources'
            html += '<span class="block_data_attr"><b>load</b> %s</span>' % ', '.join(self.plugin.load)
            html += '<span class="block_data_attr"><b>ram free</b> %s</span>' % (self.plugin.memfree_mb + ' MB')
            html += '<span class="block_data_attr"><b>disk free</b> %s</span>' % (str(self.plugin.diskfree_mb) + ' MB')
            html += '</div>'
        for p in self.plugin.server.plugins:
            if p.name != None:
                html += '<div class="block_data">'
                html += '<img src="static/icons/puzzle.png">%s' % p.name
                st = p.getStatus()
                for i in st:
                    if i[1] != None:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i[0], prettydate(i[1]))
                    else:
                        html += '<span class="block_data_attr">%s</span>' % i[0]
                html += '</div>'
        for p in self.plugin.server.plugins_inactive:
            if p.name != None:
                html += '<div class="block_data">'
                html += '<img src="static/icons/puzzle-grey.png">%s' % p.name
                html += '<span class="block_data_attr">disabled</span>'
                html += '</div>'
        html += '</div></div>'
        return html

    def render_footer(self):
        html = '<div id="footer"><p>Gyrid Server version <span title="%s">%s</span>.</p>' % (self.plugin.server.git_commit,
            time.strftime('%Y-%m-%d', time.localtime(self.plugin.server.git_date)))
        html += '<p>© 2011 Universiteit Gent, Roel Huybrechts. '
        html += 'Icons by <a href="http://p.yusukekamiyamane.com/">Yusuke Kamiyamane</a>.</p>'
        html += '</div>'
        return html

    def render_GET(self, request):
        return self.render_POST(request)

    def render_POST(self, request):
        html = '<div id="title">Gyrid Server status panel</div><div id="updated">%s</div>' % time.strftime('%H:%M:%S')
        html += '<div style="clear: both;"></div>'

        html += self.render_server()
        html += self.render_warnings()

        for scanner in self.plugin.scanners.values():
            html += scanner.render()

        html += self.render_footer()

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
        olof.core.Plugin.__init__(self, server)
        self.root = RootResource()
        self.root.putChild("", self.root)

        self.root.putChild("static",
            StaticResource("olof/plugins/status/static/"))

        self.content = ContentResource(self)
        self.root.putChild("content", self.content)
        self.warnings = []

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
                    sens.disconnect_time = None
        else:
            self.scanners = {}


        self.plugin_uptime = int(time.time())

        f = open("olof/plugins/status/data/locations.txt", "r")
        for line in f:
            line = line.strip().split(',')
            if not line[0].startswith('#'):
                s = self.getScanner(line[0])
                s.location = line[1]
                if len(line) >= 4:
                    s.location_link = "http://www.openstreetmap.org/?mlat=%s&mlon=%s&zoom=15&layers=M" % (
                        line[2], line[3])
            else:
                s = self.getScanner(line[0].lstrip('#'), create=False)
                if s != None:
                    s.location = None
                    s.location_link = None
        f.close()

        t = task.LoopingCall(self.check_resources)
        t.start(10)

        reactor.listenTCP(8080, tserver.Site(self.root))

    def check_resources(self):
        f = open('/proc/loadavg', 'r')
        self.load = f.read().strip().split()[0:3]
        f.close()

        f = open('/proc/meminfo', 'r')
        for line in f:
            ls = line.strip().split()
            if 'MemTotal' in ls[0]:
                memtotal = int(ls[1])
            elif 'MemFree' in ls[0]:
                memfree = int(ls[1])
            elif 'Buffers' in ls[0]:
                buffers = int(ls[1])
            elif 'Cached' in ls[0]:
                cached = int(ls[1])
        self.memfree_mb = "%i" % ((memtotal - (memfree + buffers + cached))/1024.0)
        self.memfree_pct = "%0.2f" % (((memfree + buffers + cached)*1.0 / memtotal*1.0) * 100)

        s = os.statvfs('.')
        self.diskfree_mb = (s.f_bavail * s.f_bsize)/1024/1024

    def unload(self):
        f = open("olof/plugins/status/data/obj.pickle", "w")
        pickle.dump(self.scanners, f)
        f.close()

    def getScanner(self, hostname, create=True):
        if not hostname in self.scanners and create:
            s = Scanner(hostname)
            self.scanners[hostname] = s
        elif hostname in self.scanners:
            s = self.scanners[hostname]
        else:
            s = None
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
