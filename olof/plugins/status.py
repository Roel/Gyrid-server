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
from twisted.web import resource
from twisted.web import server as tserver
from twisted.web.static import File

import cPickle as pickle
import datetime
import math
import os
import subprocess
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
        self.lagData = []

        self.connected = False
        self.location = None
        self.lat = None
        self.lon = None
        self.gyrid_connected = True
        self.gyrid_disconnect_time = None
        self.gyrid_uptime = None

        self.conn_ip = None
        self.conn_provider = None
        self.conn_netname = None

        self.init()

    def init(self):
        self.conn_port = None
        self.conn_time = None
        self.connected = False
        self.lag = {1: [0, 0], 5: [0, 0], 15: [0, 0]}

        self.checkLag_call = task.LoopingCall(reactor.callInThread,
            self.checkLag)

    def checkLagCall(self, action):
        if action == 'start':
            if not 'checkLag_call' in self.__dict__:
                self.checkLag_call = task.LoopingCall(reactor.callInThread,
                    self.checkLag)
            try:
                self.checkLag_call.start(10, now=False)
            except AssertionError:
                print self.hostname + ": AssertionError starting call"

        elif action == 'stop':
            if 'checkLag_call' in self.__dict__:
                try:
                    self.checkLag_call.stop()
                except AssertionError:
                    print self.hostname + ": AssertionError stopping call"

    def checkLag(self):
        t = time.time()
        lag = {1: [0, 0], 5: [0, 0], 15: [0, 0]}
        for i in self.lagData:
            if (t - i[0]) > (sorted(lag.keys())[-1]*60):
                try:
                    self.lagData.remove(i)
                except:
                    pass
                continue

            for j in lag.keys():
                if (t - i[0]) <= j*60:
                    lag[j][0] += abs(i[0] - i[1])
                    lag[j][1] += 1

        self.lag = lag

    def getProvider(self, ip=None):
        def run(ip):
            p = subprocess.Popen(["/usr/bin/whois", ip], stdin=subprocess.PIPE,
                stdout=subprocess.PIPE)

            stdout, stderr = p.communicate()

            netname = ""
            descr = ""
            for line in stdout.split('\n'):
                l = line.strip()
                if l.lower().startswith('netname:'):
                    netname = ' '.join(l.split()[1:]).replace(';', ',')
                elif l.lower().startswith('descr:') and descr == "":
                    descr = ' '.join(l.split()[1:]).replace(';', ',')

            return (netname, descr)

        def process(v):
            self.conn_provider = v[1]
            self.conn_netname = v[0]

        if ip == None and self.conn_ip != None:
            ip = self.conn_ip

        if ip != None:
            d = threads.deferToThread(run, ip)
            d.addCallback(process)

    def render(self):

        def render_location():
            html = '<div class="block_topright">'
            if self.location != None and (self.lat == None or self.lon == None):
                html += '%s<img src="static/icons/marker.png">' % self.location
            elif self.location != None:
                #html += '<a href="%s">%s</a><img src="static/icons/marker.png">' % (
                #    ("http://www.openstreetmap.org/?mlat=%s&mlon=%s&zoom=15&layers=M" % (self.lat, self.lon)), self.location)
                html += '<a href="%s">%s</a><img src="static/icons/marker.png">' % (
                    ("http://maps.google.be/maps?f=q&source=s_q&hl=nl&geocode=&q=loc:%s,%s(%s)" % (self.lat, self.lon, self.hostname)), self.location)
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

        def render_lag():
            lag = [(self.lag[i][0]/self.lag[i][1]) for i in sorted(
                self.lag.keys()) if (i <= 15 and self.lag[i][1] > 0)]
            if len([i for i in lag[1:] if i >= 5]) > 0:
                html = '<div class="block_data"><img src="static/icons/network-cloud.png">Network'
                html += '<span class="block_data_attr"><b>ip</b> %s</span>' % self.conn_ip
                l = []
                for i in sorted(self.lag.keys()):
                    if i <= 15:
                        if self.lag[i][1] == 0:
                            l.append('nd')
                        else:
                            l.append(formatNumber(float("%0.2f" % (self.lag[i][0]/self.lag[i][1]))))
                if len([i for i in l if i != 'nd']) > 0:
                    html += '<span class="block_data_attr"><b>lag</b> %s</span>' %  ', '.join(l)
                if self.conn_provider:
                    html += '<span class="block_data_attr"><b>provider</b> %s</span>' % self.conn_provider
                if self.conn_netname:
                    html += '<span class="block_data_attr"><b>netname</b> %s</span>' % self.conn_netname
                html += '</div>'
                return html
            else:
                return ''

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

        if self.connected:
            html += render_uptime()
            if self.gyrid_connected == True:
                html += render_lag()
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
        self.detections = 0

        self.init()

    def init(self):
        self.connected = False
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
            html += '<span class="block_data_attr"><b>detections</b> %s</span>' % formatNumber(self.detections)
        html += '</div>'
        return html

class RootResource(resource.Resource):
    def __init__(self):
        resource.Resource.__init__(self)

        f = open('olof/plugins/status/static/index.html', 'r')
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
        if (len(self.plugin.load) > 0 and len([i for i in self.plugin.load[1:] if float(i) >= (self.plugin.cpuCount*0.8)]) > 0) \
            or int(self.plugin.memfree_mb) <= 256 or self.plugin.diskfree_mb <= 1000:
            html += '<div class="block_data">'
            html += '<img src="static/icons/system-monitor.png">Resources'
            html += '<span class="block_data_attr"><b>load</b> %s</span>' % ', '.join(self.plugin.load)
            html += '<span class="block_data_attr"><b>ram free</b> %s</span>' % (formatNumber(self.plugin.memfree_mb) + ' MB')
            html += '<span class="block_data_attr"><b>disk free</b> %s</span>' % (formatNumber(self.plugin.diskfree_mb) + ' MB')
            html += '</div>'
        for p in self.plugin.server.plugins:
            if p.name != None:
                html += '<div class="block_data">'
                st = p.getStatus()
                if 'status' in st[0] and st[0]['status'] == 'error':
                    html += '<img src="static/icons/puzzle-red.png">%s' % p.name
                else:
                    html += '<img src="static/icons/puzzle.png">%s' % p.name
                for i in st:
                    if len(i) == 1 and 'id' in i:
                        html += '<span class="block_data_attr">%s</span>' % i['id']
                    elif len(i) > 1 and 'time' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], prettydate(i['time']))
                    elif len(i) > 1 and 'str' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], i['str'])
                    elif len(i) > 1 and 'int' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], formatNumber(i['int']))
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
        html += '<br>Icons by <a href="http://p.yusukekamiyamane.com/">Yusuke Kamiyamane</a>.</p>'
        html += '</div>'
        return html

    def render_GET(self, request):
        return self.render_POST(request)

    def render_POST(self, request):
        html = '<div id="title">Gyrid Server status panel</div><div id="updated">%s</div>' % time.strftime('%H:%M:%S')
        html += '<div style="clear: both;"></div>'

        html += self.render_server()
        html += self.render_warnings()

        for scanner in sorted(self.plugin.scanners.keys()):
            html += self.plugin.scanners[scanner].render()

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

def formatNumber(number):
    if type(number) is int:
        return '{:,.0f}'.format(number).replace(',', '<span class="thousandSep"></span>')
    elif type(number) is float:
        return '{:,.2f}'.format(number).replace(',', '<span class="thousandSep"></span>')

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
            try:
                f = open("olof/plugins/status/data/obj.pickle", "rb")
                self.scanners = pickle.load(f)
                f.close()
                for s in self.scanners.values():
                    s.init()
                    for sens in s.sensors.values():
                        sens.init()
            except:
                self.scanners = {}
        else:
            self.scanners = {}

        self.resources_log = open("olof/plugins/status/data/resources.log", "a")

        self.plugin_uptime = int(time.time())

        try:
            import multiprocessing
            self.cpuCount = multiprocessing.cpu_count()
        except:
            self.cpuCount = 1

        t = task.LoopingCall(self.check_resources)
        t.start(10)

        t = task.LoopingCall(self.load_locations)
        t.start(60)

        reactor.listenTCP(8080, tserver.Site(self.root))

    def _distance(self, lat1, lon1, lat2, lon2):
        R = 6370
        dLon = lon1-lon2 if lon1 < lon2 else lon2-lon1
        dLon = math.radians(abs(dLon))

        p1 = math.radians(90-lat1)
        p2 = math.radians(90-lat2)

        distCos = math.cos(p2)*math.cos(p1)+math.sin(p2)*math.sin(p1)*math.cos(dLon)
        dist = math.acos(distCos) * R
        return dist

    def load_locations(self):
        f = open("olof/plugins/status/data/locations.txt", "r")
        for line in f:
            line = line.strip().split(',')
            if not line[0].startswith('#'):
                s = self.getScanner(line[0])
                if s.location == None or s.lat == None or s.lon == None:
                    s.sensors = {}
                s.location = line[1]
                if len(line) >= 4:
                    if (s.lat != None and s.lon != None) and \
                        self._distance(s.lat, s.lon, float(line[2]), float(line[3])) > 0.2:
                        s.sensors = {}
                    s.lat = float(line[2])
                    s.lon = float(line[3])
                else:
                    s.lat = None
                    s.lon = None
            else:
                s = self.getScanner(line[0].lstrip('#'), create=False)
                if s != None:
                    s.location = None
                    s.lat = None
                    s.lon = None
        f.close()

    def check_resources(self):
        f = open('/proc/loadavg', 'r')
        self.load = f.read().strip().split()[0:3]
        f.close()

        f = open('/proc/meminfo', 'r')
        for line in f:
            ls = line.strip().split()
            if ls[0].startswith('MemTotal:'):
                memtotal = int(ls[1])
            elif ls[0].startswith('MemFree:'):
                memfree = int(ls[1])
            elif ls[0].startswith('Buffers:'):
                buffers = int(ls[1])
            elif ls[0].startswith('Cached:'):
                cached = int(ls[1])
        self.memfree_mb = int((memfree + buffers + cached)/1024.0)

        s = os.statvfs('.')
        self.diskfree_mb = (s.f_bavail * s.f_bsize)/1024/1024

        self.resources_log.write(",".join([str(int(time.time())),
            ",".join(self.load), str(self.memfree_mb),
            str(self.diskfree_mb)]) + '\n')
        self.resources_log.flush()

    def unload(self):
        self.resources_log.close()
        for s in self.scanners.values():
            s.checkLagCall('stop')
            if 'checkLag_call' in s.__dict__:
                del(s.checkLag_call)

        f = open("olof/plugins/status/data/obj.pickle", "wb")
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
        s.connected = True
        if ip != s.conn_ip:
            s.conn_ip = ip
            s.getProvider()
        s.conn_port = port
        s.conn_time = int(time.time())

        s.checkLagCall('start')

    def connectionLost(self, hostname, ip, port):
        s = self.getScanner(hostname)
        s.connected = False
        s.conn_time = int(time.time())
        s.checkLagCall('stop')
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

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        scann = self.getScanner(hostname)
        t = time.time()
        scann.lagData.append((t, float(timestamp)))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        sens = self.getSensor(hostname, sensor_mac)
        sens.detections += 1
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp

        scann = self.getScanner(hostname)
        t = time.time()
        scann.lagData.append((t, float(timestamp)))
