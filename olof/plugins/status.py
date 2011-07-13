#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.cred.portal import IRealm, Portal
from twisted.cred.checkers import FilePasswordDB
from twisted.internet import reactor, task, threads
from twisted.web import resource
from twisted.web import server as tserver
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from twisted.web.resource import IResource
from twisted.web.static import File

from zope.interface import implements

import cPickle as pickle
import datetime
import math
import os
import subprocess
import time
import urllib2
import urlparse

import olof.core
import olof.plugins.status.macvendor as macvendor
from olof.plugins.move import RawConnection

def prettydate(d, prefix="", suffix=" ago"):
    t = d
    d = datetime.datetime.fromtimestamp(d)
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days < 0:
        r =  d.strftime('%d %b %Y')
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
        self.lagData = []
        self.connections = set()
        self.ip_provider = {}
        self.msisdn = None
        self.mv_balance = {}
        self.mv_updated = None

        f = open('olof/plugins/status/data/mobilevikings.conf', 'r')
        for l in f:
            ls = l.strip().split(',')
            self.__dict__[ls[0]] = ls[1]
        f.close()
        self.mv_conn = RawConnection(self.url, self.user, self.password,
            urllib2.HTTPBasicAuthHandler)

        self.location = None
        self.location_description = None
        self.lat = None
        self.lon = None
        self.gyrid_connected = True
        self.gyrid_disconnect_time = None
        self.gyrid_uptime = None

        self.init()

    def init(self):
        self.conn_port = None
        self.conn_time = None
        self.connections = set()
        self.lag = {1: [0, 0], 5: [0, 0], 15: [0, 0]}

        self.checkLag_call = task.LoopingCall(reactor.callInThread,
            self.checkLag)

        self.checkMVBalance_call = task.LoopingCall(reactor.callInThread,
            self.getMVBalance)
        self.checkMVBalanceCall('start')

    def checkLagCall(self, action):
        if action == 'start':
            if not 'checkLag_call' in self.__dict__:
                self.checkLag_call = task.LoopingCall(reactor.callInThread,
                    self.checkLag)
            try:
                self.checkLag_call.start(10)
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

    def checkMVBalanceCall(self, action):
        if action == 'start':
            if not 'checkMVBalance_call' in self.__dict__:
                self.checkMVBalance_call = task.LoopingCall(reactor.callInThread,
                    self.getMVBalance)
            try:
                self.checkMVBalance_call.start(1800)
            except AssertionError:
                print self.hostname + ": AssertionError starting call"

        elif action == 'stop':
            if 'checkMVBalance_call' in self.__dict__:
                try:
                    self.checkMVBalance_call.stop()
                except AssertionError:
                    print self.hostname + ": AssertionError stopping call"

    def getMVBalance(self):
        def process(r):
            self.mv_balance = pickle.loads("".join(r))
            self.mv_updated = int(time.time())

        if self.msisdn:
            self.mv_conn.request_get('sim_balance.pickle?msisdn=%s' % self.msisdn, process)

    def getProvider(self, ip):
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
            self.ip_provider[ip] = (v[1], v[0])

        if ip != None and ip not in self.ip_provider:
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
                loc = '<span title="%s">%s</span>' % (self.location_description, self.location) if self.location_description != None else self.location
                html += '<a href="%s">%s</a><img src="static/icons/marker.png">' % (
                    ("http://maps.google.be/maps?f=q&source=s_q&hl=nl&geocode=&q=loc:%s,%s(%s)" % (self.lat, self.lon, self.hostname)), loc)
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
                provider = self.ip_provider.get(list(self.connections)[0][0], (None, None))[0]
                html = '<div class="block_data"><img src="static/icons/network-cloud.png">Network'
                html += '<span class="block_data_attr"><b>ip</b> %s</span>' % list(self.connections)[0][0]
                l = []
                for i in sorted(self.lag.keys()):
                    if i <= 15:
                        if self.lag[i][1] == 0:
                            l.append('nd')
                        else:
                            l.append(formatNumber(float("%0.2f" % (self.lag[i][0]/self.lag[i][1]))))
                if len([i for i in l if i != 'nd']) > 0:
                    html += '<span class="block_data_attr"><b>lag</b> %s</span>' %  ', '.join(l)
                if provider:
                    html += '<span class="block_data_attr"><b>provider</b> %s</span>' % provider
                html += '</div>'
                return html
            else:
                return ''

        def render_balance():
            if 'data' in self.mv_balance:
                mb = self.mv_balance['data']/1024.0/1024.0
                if mb <= 200:
                    html = '<div class="block_data"><img src="static/icons/shield-red.png">SIM balance'
                elif mb <= 500:
                    html = '<div class="block_data"><img src="static/icons/shield-yellow.png">SIM balance'
                else:
                    return ''
                html += '<span class="block_data_attr"><b>data</b> %s MB</span>' % formatNumber(mb)
                if 'is_expired' in self.mv_balance and self.mv_balance['is_expired']:
                    html += '<span class="block_data_attr"><b>expired</b> %s</span>' % ('yes' if self.mv_balance['is_expired'] else 'no')
                if 'valid_until' in self.mv_balance and not self.mv_balance['is_expired']:
                    html += '<span class="block_data_attr"><b>expires</b> %s</span>' % \
                        prettydate(float(time.strftime('%s', time.strptime(self.mv_balance['valid_until'], '%Y-%m-%d %H:%M:%S'))))
                if self.mv_updated:
                    html += '<span class="block_data_attr"><b>updated</b> %s</span>' % prettydate(self.mv_updated)
                html += '</div>'
                return html
            else:
                return ''

        def render_detections():
            detc = [self.lag[i][1] for i in sorted(self.lag.keys()) if i <= 15]
            if len([i for i in detc if i > 0]) > 0:
                html = '<div class="block_data"><img src="static/icons/users.png">Detections'
                html += '<span class="block_data_attr"><b>recently received</b> %s</span>' % \
                    ', '.join([formatNumber(i) for i in detc])
                sensors_connected = len([s for s in self.sensors.values() if s.connected == True])
                if sensors_connected > 1:
                    html += '<span class="block_data_attr"><b>averaged</b> %s</span>' % \
                        ', '.join([formatNumber(int(i/sensors_connected)) for i in detc])
                html += '</div>'
                return html
            else:
                return ""

        def render_notconnected(disconnect_time, suffix=""):
            html = '<div class="block_data"><img src="static/icons/traffic-cone.png">No connection%s' % suffix
            if disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(disconnect_time)))
            html += '</div>'
            return html

        html = '<div id="%(h)s" class="block" onclick="goTo(\'#navigation_block\')"><div class="block_title"><h3>%(h)s</h3></div>' % {'h': self.hostname}
        html += render_location()
        html += '<div style="clear: both;"></div>'

        html += '<div class="block_content">'

        if len(self.connections) >= 1:
            html += render_uptime()
            if self.gyrid_connected == True:
                html += render_detections()
                html += render_lag()
                html += render_balance()
                for sensor in self.sensors.values():
                    html += sensor.render()
            else:
                html += render_notconnected(self.gyrid_disconnect_time, " to Gyrid")
        else:
            html += render_notconnected(self.conn_time)

        html += '</div></div>'
        return html

    def render_navigation(self):
        lag = [(self.lag[i][0]/self.lag[i][1]) for i in sorted(
                self.lag.keys()) if (i <= 15 and self.lag[i][1] > 0)]
        html = '<div class="navigation_item" onclick="goTo(\'#%s\')">' % self.hostname
        html += '<div class="navigation_link">%s</div>' % self.hostname
        if len(self.connections) == 0 or not self.gyrid_connected:
            html += '<div class="navigation_status_bad"></div>'
        elif len([s for s in self.sensors.values() if s.connected == True]) == 0:
            html += '<div class="navigation_status_bad"></div>'
        elif len([i for i in lag[1:] if i >= 5]) > 0:
            html += '<div class="navigation_status_ugly"></div>'
        else:
            html += '<div class="navigation_status_good"></div>'
        html += '</div>'
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
        vendor = macvendor.get_vendor(self.mac)
        mac = self.mac if vendor == None else '<span title="%s">%s</span>' % (vendor, self.mac)
        if self.connected == False:
            html += '<img src="static/icons/plug-disconnect.png">%s' % mac
            if self.disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettydate(int(float(self.disconnect_time)))
        else:
            html += '<img src="static/icons/bluetooth.png">%s' % mac
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

    def render_server(self):
        html = '<div id="server_block" onclick="goTo(\'top\')"><div class="block_title"><h3>Server</h3></div>'
        html += '<div class="block_topright">%s<img src="static/icons/clock-arrow.png"></div>' % prettydate(self.plugin.plugin_uptime, suffix="")
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'

        # Resources
        if (len(self.plugin.load) > 0 and len([i for i in self.plugin.load[1:] if float(i) >= (self.plugin.cpuCount*0.8)]) > 0) \
            or int(self.plugin.memfree_mb) <= 256 or self.plugin.diskfree_mb <= 1000:
            html += '<div class="block_data">'
            html += '<img src="static/icons/system-monitor.png">Resources'
            html += '<span class="block_data_attr"><b>load</b> %s</span>' % ', '.join(self.plugin.load)
            html += '<span class="block_data_attr"><b>ram free</b> %s</span>' % (formatNumber(self.plugin.memfree_mb) + ' MB')
            html += '<span class="block_data_attr"><b>disk free</b> %s</span>' % (formatNumber(self.plugin.diskfree_mb) + ' MB')
            html += '</div>'

        # Unique devices
        html += '<div class="block_data">'
        html += '<img src="static/icons/users.png">Unique devices'
        html += '<span class="block_data_attr"><b>total</b> %s' % formatNumber(len(self.plugin.server.mac_dc))
        html += '</div>'

        # Plugins
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

        # Disabled plugins
        for p in self.plugin.server.plugins_inactive:
            if p.name != None:
                html += '<div class="block_data">'
                html += '<img src="static/icons/puzzle-grey.png">%s' % p.name
                html += '<span class="block_data_attr">disabled</span>'
                html += '</div>'

        html += '</div></div>'
        return html

    def render_navigation(self):
        html = '<div id="navigation_block">'
        for s in sorted(self.plugin.scanners.keys()):
            html += self.plugin.scanners[s].render_navigation()
        html += '</div>'
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
        html += self.render_navigation()

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

class AuthenticationRealm(object):
    implements(IRealm)

    def __init__(self, plugin):
        self.plugin = plugin

    def requestAvatar(self, avatarId, mind, *interfaces):
        if IResource in interfaces:
            return (IResource, ContentResource(self.plugin), lambda: None)
        else:
            raise NotImplementedError()

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

        portal = Portal(AuthenticationRealm(self), [FilePasswordDB(
            'olof/plugins/status/data/auth.password')])
        credfac = BasicCredentialFactory("Gyrid Server")
        resource = HTTPAuthSessionWrapper(portal, [credfac])
        self.root.putChild("content", resource)

        self.root.putChild("static",
            StaticResource("olof/plugins/status/static/"))

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

        t = task.LoopingCall(self.read_MV_numbers)
        t.start(120)

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

    def read_MV_numbers(self):
        f = open('olof/plugins/status/data/mobilevikings_numbers.conf', 'r')
        for line in f:
            l = line.strip().split(',')
            s = self.getScanner(l[0], create=False)
            if s:
                s.msisdn = l[1]
        f.close()

    def unload(self):
        self.resources_log.close()
        for s in self.scanners.values():
            s.checkLagCall('stop')
            s.checkMVBalanceCall('stop')
            if 'checkLag_call' in s.__dict__:
                del(s.checkLag_call)
            if 'checkMVBalance_call' in s.__dict__:
                del(s.checkMVBalance_call)

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
        s.gyrid_connected = True

    def connectionMade(self, hostname, ip, port):
        s = self.getScanner(hostname)
        s.connections.add((ip, port))
        s.getProvider(ip)
        s.conn_time = int(time.time())
        s.gyrid_uptime = None
        s.gyrid_connected = True

        s.checkLagCall('start')

    def connectionLost(self, hostname, ip, port):
        s = self.getScanner(hostname)
        if (ip, port) in s.connections:
            s.connections.remove((ip, port))
        s.conn_time = int(time.time())
        s.checkLagCall('stop')
        for sens in s.sensors.values():
            sens.connected = False

    def locationUpdate(self, hostname, module, timestamp, id, description, coordinates):
        if module != 'scanner':
            return

        s = self.getScanner(hostname)
        if coordinates != None:
            s.lon = coordinates[0]
            s.lat = coordinates[1]
            s.location = id
            s.location_description = description
        else:
            s.lon = s.lat = s.location = s.location_description = None

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

        scann = self.getScanner(hostname)
        t = time.time()
        scann.lagData.append((t, float(timestamp)))
