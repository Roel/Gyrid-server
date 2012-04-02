#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Plugin that provides a status dashboard webpage.
"""

from twisted.cred.checkers import FilePasswordDB
from twisted.cred.portal import IRealm, Portal
from twisted.internet import reactor, task, threads
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from twisted.web import resource
from twisted.web import server as tserver
from twisted.web.resource import IResource
from twisted.web.static import File

from zope.interface import implements

import cPickle as pickle
import datetime
import math
import os
import re
import subprocess
import time
import urllib2
import urlparse

import olof.configuration
import olof.core
import olof.plugins.dashboard.macvendor as macvendor
import olof.tools.validation
from olof.tools.inotifier import INotifier
from olof.tools.webprotocols import RESTConnection

def prettyDate(d, prefix="", suffix=" ago"):
    """
    Turn a UNIX timestamp in a prettier, more readable string.

    @param    d (int)        The UNIX timestamp to convert.
    @param    prefix (str)   The prefix to add. No prefix by default.
    @param    suffix (str)   The suffix to add, " ago" by default.
    @return   (str)          The string corresponding to the timestamp.
    """
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

class ScannerStatus:
    """
    Class providing an enumeration for scanner status.

    ScannerStatus is either Good, Bad or Ugly.
    """
    Good, Bad, Ugly = range(3)

class Scanner(object):
    """
    Class representing a scanner.
    """
    def __init__(self, hostname, mv_url=None, mv_user=None, mv_pwd=None):
        """
        Initialisation.

        @param   hostname (str)   Hostname of the scanner.
        @param   mv_url (str)     Base URL of the Mobile Vikings basic API. Optional.
        @param   mv_user (str)    Username to log in to the Mobile Vikings API. Optional.
        @param   mv_pwd (str)     Password to log in to the Mobile Vikings API. Optional.
        """
        self.hostname = hostname
        self.mv_url = mv_url
        self.mv_user = mv_user
        self.mv_pwd = mv_pwd
        self.project = None
        self.host_uptime = None
        self.sensors = {}
        self.lagData = []
        self.ip_provider = {}
        self.msisdn = None
        self.mv_balance = {}
        self.mv_updated = None
        self.lastConnected = None
        self.conn_time = {}
        self.connections = set()

        self.location = None
        self.location_description = None
        self.lat = None
        self.lon = None
        self.gyrid_connected = True
        self.gyrid_disconnect_time = None
        self.gyrid_uptime = None

        self.init()

    def init(self):
        """
        Reinitialise variables that need updating when the plugin starts.

        __init__() is called when a new Scanner is created, this init() is called at __init__() and after the
        saved Scanner data is read at plugin start.
        """
        self.lag = {1: [0, 0], 5: [0, 0], 15: [0, 0]}

        self.initMVConnection(self.mv_url, self.mv_user, self.mv_pwd)

        self.checkLag_call = task.LoopingCall(reactor.callInThread,
            self.checkLag)
        self.checkLagCall('start')

        self.checkMVBalance_call = task.LoopingCall(reactor.callInThread,
            self.getMVBalance)
        self.checkMVBalanceCall('start')

    def initMVConnection(self, url, username, password):
        """
        Initialise a Mobile Vikings REST connection with the given details. If any of the arguments is None, delete
        any existing connection.

        @param   url (str)        Base URL of the Mobile Vikings basic API. Optional.
        @param   username (str)   Username to log in to the Mobile Vikings API. Optional.
        @param   password (str)   Password to log in to the Mobile Vikings API. Optional.
        """
        if None not in [url, username, password]:
            self.mv_conn = RESTConnection(
                base_url = url,
                username = username,
                password = password,
                authHandler = urllib2.HTTPBasicAuthHandler)
        else:
            self.mv_conn = None

    def isOld(self):
        """
        Get the age of the scanner. Old scanners are removed automatically.

        A scanner is defined old if it has been connected to the server at least once, has no location information
        attached and its last connection to the server was more than 7 days ago.

        @return   (bool)   True if this scanner is old, else False.
        """
        if self.lastConnected == None:
            return False
        elif False in [i == None for i in [self.location, self.location_description, self.lat, self.lon]]:
            return False
        else:
            return (int(time.time()) - self.lastConnected) > 7*24*60*60

    def getStatus(self):
        """
        Get the status of the scanner.

        Status is Bad when:
          - Not connected,
          - Gyrid daemon not connected,
          - No Bluetooth sensors connected,
          - No recent (< 80 seconds) Bluetooth inquiry.

        Status is Ugly when:
          - Connection lag over the last 10 or 15 minutes is over 5 seconds.

        Else status is Good.

        @return   (ScannerStatus)   The status of the scanner.
        """
        lag = [(self.lag[i][0]/self.lag[i][1]) for i in sorted(
                self.lag.keys()) if (i <= 15 and self.lag[i][1] > 0)]
        t = int(time.time())

        if len(self.connections) == 0 or not self.gyrid_connected:
            # Not connected
            return ScannerStatus.Bad
        elif len([s for s in self.sensors.values() if s.connected == True]) == 0:
            # No sensors connected
            return ScannerStatus.Bad
        elif len([s for s in self.sensors.values() if (s.last_inquiry == None or t-s.last_inquiry >= 80)]) == len(
            self.sensors):
            # No recent inquiry
            return ScannerStatus.Bad
        elif len([i for i in lag[1:] if i >= 5]) > 0:
            # Laggy connection
            return ScannerStatus.Ugly
        else:
            return ScannerStatus.Good

    def checkLagCall(self, action):
        """
        Start or stop the looping call that checks the connection lag.

        @param   action (str)   Either 'start' or 'stop'.
        """
        if action == 'start':
            if not 'checkLag_call' in self.__dict__:
                self.checkLag_call = task.LoopingCall(reactor.callInThread,
                    self.checkLag)
            try:
                self.checkLag_call.start(10)
            except AssertionError:
                pass

        elif action == 'stop':
            if 'checkLag_call' in self.__dict__:
                try:
                    self.checkLag_call.stop()
                except AssertionError:
                    pass

    def checkLag(self):
        """
        Check the connection lag data. Removes old data and updates the process lag data.
        """
        t = time.time()
        lag = {1: [0, 0, set()], 5: [0, 0, set()], 15: [0, 0, set()]}
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
                    lag[j][2].add(i[2])

        for j in lag.keys():
            lag[j][2] = len(lag[j][2])

        self.lag = lag

    def checkMVBalanceCall(self, action):
        """
        Start or stop the looping call that checks the SIM card balance.

        @param   action (str)   Either 'start' or 'stop'.
        """
        if action == 'start':
            if not 'checkMVBalance_call' in self.__dict__:
                self.checkMVBalance_call = task.LoopingCall(reactor.callInThread,
                    self.getMVBalance)
            try:
                self.checkMVBalance_call.start(1800, now=False)
            except AssertionError:
                pass

        elif action == 'stop':
            if 'checkMVBalance_call' in self.__dict__:
                try:
                    self.checkMVBalance_call.stop()
                except AssertionError:
                    pass

    def getMVBalance(self):
        """
        Get the SIM card balance via the Mobile Vikings REST API.
        """
        def process(r):
            if r != None:
                try:
                    self.mv_balance = pickle.loads("".join(r))
                    self.mv_updated = int(time.time())
                except:
                    pass

        if self.mv_conn != None and self.msisdn:
            self.mv_conn.requestGet('sim_balance.pickle?msisdn=%s' % self.msisdn, process)
        else:
            self.mv_updated = None
            self.mv_balance = {}

    def getProvider(self, ip):
        """
        Get the Internet Service Provider for the given IP-address using the /usr/bin/whois application.
        Saved in a variable for later user

        @param   ip (str)   IP-address to check.
        """
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
        """
        Render this scanner to HTML.

        @return   (str)   HTML representation of this scanner.
        """
        def renderLocation():
            html = '<div class="block_topright">'
            if self.location != None and (self.lat == None or self.lon == None):
                html += '%s<img src="/dashboard/static/icons/marker.png">' % self.location
            elif self.location != None:
                loc = '<span title="%s">%s</span>' % (self.location_description, self.location) if \
                    self.location_description != None else self.location
                html += '<a href="%s">%s</a><img src="/dashboard/static/icons/marker.png">' % (
                    ("http://maps.google.be/maps?z=17&q=loc:%s,%s(%s)" % (self.lat, self.lon, self.hostname)), loc)
            if self.project == None:
                goto = 'No-project'
            else:
                goto = self.project.name.replace(' ','-')
            html += '</div><div style="clear: both;"></div><div class="block_content" onclick="goTo(\'#%s\')">' % goto

            if self.location_description:
                html += '<div class="block_data_location">%s</div>' % self.location_description

            return html

        def renderUptime():
            html = '<div class="block_data"><img src="/dashboard/static/icons/clock-arrow.png">Uptime'
            if 'made' in self.conn_time:
                html += '<span class="block_data_attr"><b>connection</b> %s</span>' % prettyDate(int(float(
                    self.conn_time['made'])), suffix="")
            if self.gyrid_uptime != None and self.gyrid_connected == True:
                html += '<span class="block_data_attr"><b>gyrid</b> %s</span>' % prettyDate(self.gyrid_uptime,
                    suffix="")
            if self.host_uptime != None:
                html += '<span class="block_data_attr"><b>system</b> %s</span>' % prettyDate(self.host_uptime,
                    suffix="")
            html += '</div>'
            return html

        def renderLag():
            lag = [(self.lag[i][0]/self.lag[i][1]) for i in sorted(
                self.lag.keys()) if (i <= 15 and self.lag[i][1] > 0)]
            if len([i for i in lag[1:] if i >= 5]) > 0:
                provider = self.ip_provider.get(list(self.connections)[0][0], (None, None))[0]
                html = '<div class="block_data"><img src="/dashboard/static/icons/network-cloud.png">Network'
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

        def renderBalance():
            if 'data' in self.mv_balance:
                try:
                    mb = self.mv_balance['data']/1024.0/1024.0
                except:
                    return ''
                if mb <= 200:
                    html = '<div class="block_data"><img src="/dashboard/static/icons/shield-red.png">SIM balance'
                elif mb <= 500:
                    html = '<div class="block_data"><img src="/dashboard/static/icons/shield-yellow.png">SIM balance'
                elif 'is_expired' in self.mv_balance and self.mv_balance['is_expired']:
                    html = '<div class="block_data"><img src="/dashboard/static/icons/shield-red.png">SIM balance'
                elif 'valid_until' in self.mv_balance and not self.mv_balance['is_expired']:
                    if int(time.strftime('%s', time.strptime(self.mv_balance['valid_until'], '%Y-%m-%d %H:%M:%S'))) - \
                        int(time.time()) <= 60*60*24*7:
                        html = '<div class="block_data"><img src="/dashboard/static/icons/shield-yellow.png">SIM balance'
                    else:
                        return ''
                else:
                    return ''
                html += '<span class="block_data_attr"><b>data</b> %s MB</span>' % formatNumber(mb)
                if 'is_expired' in self.mv_balance and self.mv_balance['is_expired']:
                    html += '<span class="block_data_attr"><b>expired</b> %s</span>' % ('yes' if self.mv_balance[
                        'is_expired'] else 'no')
                if 'valid_until' in self.mv_balance and not self.mv_balance['is_expired']:
                    html += '<span class="block_data_attr"><b>expires</b> %s</span>' % \
                        prettyDate(float(time.strftime('%s', time.strptime(self.mv_balance['valid_until'],
                        '%Y-%m-%d %H:%M:%S'))))
                if self.mv_updated:
                    html += '<span class="block_data_attr"><b>updated</b> %s</span>' % prettyDate(self.mv_updated)
                html += '</div>'
                return html
            else:
                return ''

        def renderDetections():
            detc = [self.lag[i][1] for i in sorted(self.lag.keys()) if i <= 15]
            udetc = [self.lag[i][2] for i in sorted(self.lag.keys()) if i <= 15]
            if len([i for i in detc if i > 0]) > 0:
                html = '<div class="block_data"><img src="/dashboard/static/icons/users.png">Detections'
                html += '<span class="block_data_attr"><b>recently received</b> %s</span>' % \
                    ', '.join([formatNumber(i) for i in detc])
                sensors_connected = len([s for s in self.sensors.values() if s.connected == True])
                if sensors_connected > 1:
                    html += '<span class="block_data_attr"><b>averaged</b> %s</span>' % \
                        ', '.join([formatNumber(int(i/sensors_connected)) for i in detc])
                html += '<span class="block_data_attr"><b>unique</b> %s</span>' % \
                    ', '.join([formatNumber(i) for i in udetc])
                html += '</div>'
                return html
            else:
                return ""

        def renderNotconnected(disconnect_time, suffix=""):
            html = '<div class="block_data"><img src="/dashboard/static/icons/traffic-cone.png">No connection%s' % suffix
            if disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettyDate(int(float(
                    disconnect_time)))
            elif suffix == "" and self.lastConnected != None:
                html += '<span class="block_data_attr"><b>last connected</b> %s</span>' % prettyDate(int(float(
                    self.lastConnected)))

            html += '</div>'
            return html

        sd = {ScannerStatus.Good: 'block_status_good', ScannerStatus.Bad: 'block_status_bad', ScannerStatus.Ugly:
            'block_status_ugly'}
        d = {'h': self.hostname, 'status': sd[self.getStatus()]}
        bl = False
        html = '<div id="%(h)s" class="block">' % d

        if bl:
            html += '<div class="blacklist_overlay">'

        html += '<div class="%(status)s"><div class="block_title"><h3>%(h)s</h3></div>' % d
        html += renderLocation()

        if len(self.connections) >= 1:
            html += renderUptime()
            if self.gyrid_connected == True:
                html += renderDetections()
                html += renderLag()
                html += renderBalance()
                for sensor in self.sensors.values():
                    html += sensor.render()
            else:
                html += renderNotconnected(self.gyrid_disconnect_time, " to Gyrid")
                html += renderBalance()
        else:
            html += renderNotconnected(self.conn_time.get('lost', None))
            html += renderBalance()

        html += '</div></div></div>'
        if bl:
            html += '</div>'
        return html

    def renderNavigation(self):
        """
        Render the navition block for this scanner to HTML.

        @return   (str)   HTML representation of the navigation block for this scanner.
        """
        bl = False
        html = '<div class="navigation_item" onclick="goTo(\'#%s\')">' % self.hostname

        if bl:
            html += '<div class="blacklist_overlay">'

        html += '<div class="navigation_link">%s</div>' % self.hostname

        if self.getStatus() == ScannerStatus.Bad:
            html += '<div class="navigation_status_bad"></div>'
        elif self.getStatus() == ScannerStatus.Ugly:
            html += '<div class="navigation_status_ugly"></div>'
        elif self.getStatus() == ScannerStatus.Good:
            html += '<div class="navigation_status_good"></div>'
        html += '</div>'
        if bl:
            html += '</div>'
        return html

class Sensor(object):
    """
    Class representing a Bluetooth sensor.
    """
    def __init__(self, mac):
        """
        Initialisation.

        @param   mac (str)   MAC-adress of this Bluetooth sensor.
        """
        self.mac = mac
        self.last_inquiry = None
        self.last_data = None
        self.detections = 0

        self.init()

    def init(self):
        """
        Reinitialise variables that need updating when the server starts.

        __init__() is called when a new Sensor is created, this init() is called at __init__() and after the
        saved Sensor data is read at server start.
        """
        self.connected = False
        self.disconnect_time = None

    def render(self):
        """
        Render this sensor to HTML.

        @return   (str)   HTML representation of this sensor.
        """
        html = '<div class="block_data">'
        vendor = macvendor.get_vendor(self.mac)
        mac = self.mac if vendor == None else '<span title="%s">%s</span>' % (vendor, self.mac)
        if self.connected == False:
            html += '<img src="/dashboard/static/icons/plug-disconnect.png">%s' % mac
            if self.disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % prettyDate(int(float(
                    self.disconnect_time)))
        else:
            html += '<img src="/dashboard/static/icons/bluetooth.png">%s' % mac
            if self.last_inquiry != None:
                html += '<span class="block_data_attr"><b>last inquiry</b> %s</span>' % prettyDate(int(float(
                    self.last_inquiry)))
        if self.last_data != None:
            html += '<span class="block_data_attr"><b>last data</b> %s</span>' % prettyDate(int(float(self.last_data)))
        if self.detections > 0:
            html += '<span class="block_data_attr"><b>detections</b> %s</span>' % formatNumber(self.detections)
        html += '</div>'
        return html

class RootResource(resource.Resource):
    """
    Class representing the root resource for the webpage.

    This resource basically serves the olof/plugins/dashboard/static/index.html page.
    """
    def __init__(self):
        """
        Initialisation.

        Read the index.html page from disk.
        """
        resource.Resource.__init__(self)

        f = open('olof/plugins/dashboard/static/index.html', 'r')
        self.rendered_page = f.read()
        f.close()

    def render_GET(self, request):
        """
        GET and POST should be identical, so call render_POST instead.
        """
        return self.render_POST(request)

    def render_POST(self, request):
        """
        Return the index.html contents.
        """
        return self.rendered_page

class ContentResource(resource.Resource):
    """
    Class representing the content resource for the webpage. This page contains all useful information and is read
    every 10 seconds by an Ajax call defined in the root index page.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        @param   plugin (Plugin)   Reference to main Status plugin instance.
        """
        resource.Resource.__init__(self)
        self.plugin = plugin

    def renderServer(self):
        """
        Render the server HTML block.

        @return   (str)   HTML representation of the server.
        """
        html = '<div id="server_block"><div class="block_title"><h3>Server</h3></div>'
        html += '<div class="block_topright_server">%s<img src="/dashboard/static/icons/clock-arrow.png"></div>' % \
            prettyDate(self.plugin.server.server_uptime, suffix="")
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'

        # Resources
        if (len(self.plugin.load) > 0 and len([i for i in self.plugin.load[1:] if float(i) >= (
            self.plugin.cpuCount*0.8)]) > 0) or int(self.plugin.memfree_mb) <= 256 or self.plugin.diskfree_mb <= 1000:
            html += '<div class="block_data">'
            html += '<img src="/dashboard/static/icons/system-monitor.png">Resources'
            html += '<span class="block_data_attr"><b>load</b> %s</span>' % ', '.join(self.plugin.load)
            html += '<span class="block_data_attr"><b>ram free</b> %s</span>' % (formatNumber(
                self.plugin.memfree_mb) + ' MB')
            html += '<span class="block_data_attr"><b>disk free</b> %s</span>' % (formatNumber(
                self.plugin.diskfree_mb) + ' MB')
            html += '</div>'

        # Plugins
        for p in self.plugin.server.pluginmgr.getPlugins():
            if p.name != None:
                html += '<div class="block_data">'
                st = p.getStatus()
                if 'status' in st[0] and st[0]['status'] == 'error':
                    html += '<img src="/dashboard/static/icons/puzzle-red.png">%s' % p.name
                elif 'status' in st[0] and st[0]['status'] == 'disabled':
                    html += '<img src="/dashboard/static/icons/puzzle-grey.png">%s' % p.name
                else:
                    html += '<img src="/dashboard/static/icons/puzzle.png">%s' % p.name
                for i in st:
                    if len(i) == 1 and 'id' in i:
                        html += '<span class="block_data_attr">%s</span>' % i['id']
                    elif len(i) > 1 and 'time' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], prettyDate(i['time']))
                    elif len(i) > 1 and 'str' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], i['str'])
                    elif len(i) > 1 and 'int' in i:
                        html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], formatNumber(i['int']))
                html += '</div>'

        html += '</div></div>'
        return html

    def renderProjectList(self):
        """
        Render the project list to HTML

        @return   (str)   HTML representation of the project list.
        """
        def renderProject(p):
            html = '<div class="block_data">'
            if p.isActive():
                html += '<img src="/dashboard/static/icons/radar.png">'
                html += '<a href="#" onclick="goTo(\'#%s\')">%s</a>' % (p.name.replace(' ','-'), p.name)
                html += '<span class="block_data_attr">active</span>'
            else:
                html += '<img src="/dashboard/static/icons/radar-grey.png">'
                html += '<a href="#" onclick="goTo(\'#%s\')">%s</a>' % (p.name.replace(' ','-'), p.name)
                html += '<span class="block_data_attr">inactive</span>'
            if p.start:
                html += '<span class="block_data_attr"><b>start</b> %s</span>' % prettyDate(p.start)
            if p.end:
                html += '<span class="block_data_attr"><b>end</b> %s</span>' % prettyDate(p.end)
            if len(p.disabled_plugins) > 0:
                html += '<span class="block_data_attr"><b>disabled</b> %s</span>' % ', '.join(sorted(p.disabled_plugins))
            html += '</div>'
            return html

        projects = self.plugin.server.dataprovider.projects
        if len(projects) <= 1:
            return ""

        html = '<div id="server_block"><div class="block_title"><h3>Projects</h3></div>'
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'

        # Active projects
        for p_name in sorted([p.name for p in projects.values() if p.isActive()]):
            html += renderProject(projects[p_name])

        # Inactive projects
        for p_name in sorted([p.name for p in projects.values() if not p.isActive()]):
            html += renderProject(projects[p_name])

        html += '</div></div>'
        return html

    def renderProject(self, project):
        """
        Render a specific project to HTML.

        @param    project (olof.datatypes.Project)   Project to render.
        @return   (str)                              HTML representation of the project.
        """
        html = '<div class="h2-outline" id="%s"><h2 onclick="goTo(\'#server_block\')">%s</h2>' % \
            (project.name.replace(' ','-'), project.name)
        html += '<div class="block_content"><div class="block_data">'

        if project.isActive():
            html += '<img src="/dashboard/static/icons/radar.png">Active'
        else:
            html += '<img src="/dashboard/static/icons/radar-grey.png">Inactive'
        if project.start:
            html += '<span class="block_data_attr"><b>start</b> %s</span>' % prettyDate(project.start)
        if project.end:
            html += '<span class="block_data_attr"><b>end</b> %s</span>' % prettyDate(project.end)
        html += '</div>'

        if len(project.disabled_plugins) > 0:
            html += '<div class="block_data"><img src="/dashboard/static/icons/puzzle-grey.png">Disabled plugins'
            html += '<span class="block_data_attr">%s</span>' % ', '.join(sorted(project.disabled_plugins))
            html += '</div>'

        if len(project.locations) == 0:
            html += '</div></div>'
            return html

        scanner_status = {ScannerStatus.Good: 0, ScannerStatus.Bad: 0, ScannerStatus.Ugly: 0}
        for location in project.locations.values():
            s = self.plugin.match(location)
            scanner_status[s.getStatus()] += 1

        if len(project.locations) >= 8 and (scanner_status[ScannerStatus.Bad] > 0 or \
            scanner_status[ScannerStatus.Ugly] > 0):
            html += '<div class="block_data"><img src="/dashboard/static/icons/traffic-light-single.png">Scanner status'
            html += '<span class="block_data_attr"><b>total</b> %s</span>' % formatNumber(len(project.locations))
            html += '<span class="block_data_attr"><b>online</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                ScannerStatus.Good]), scanner_status[ScannerStatus.Good]*100/len(project.locations))
            html += '<span class="block_data_attr"><b>offline</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                ScannerStatus.Bad]), scanner_status[ScannerStatus.Bad]*100/len(project.locations))
            html += '<span class="block_data_attr"><b>attention</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                ScannerStatus.Ugly]), scanner_status[ScannerStatus.Ugly]*100/len(project.locations))
            html += '</div>'

        html += '</div></div>'

        html += '<div id="navigation_block">'
        for location in sorted(project.locations.keys()):
            html += self.plugin.match(project.locations[location]).renderNavigation()
        html += '</div>'

        for location in sorted(project.locations.keys()):
            html += self.plugin.match(project.locations[location]).render()

        return html

    def renderFooter(self):
        """
        Render the footer of the webpage to HTML.

        @return   (str)   HTML representation of the footer of the webpage.
        """
        html = '<div id="footer"><p>Gyrid Server version <span title="%s">%s</span>.</p>' % (
            self.plugin.server.git_commit, time.strftime('%Y-%m-%d', time.localtime(self.plugin.server.git_date)))
        html += '<p>© 2011-2012 Universiteit Gent, Roel Huybrechts. '
        html += '<br>Icons by <a href="http://p.yusukekamiyamane.com/">Yusuke Kamiyamane</a>.</p>'
        html += '</div>'
        return html

    def render_GET(self, request):
        """
        GET and POST should be identical, so call render_POST instead.
        """
        return self.render_POST(request)

    def render_POST(self, request):
        """
        Render the content resource to HTML.

        @return   (str)   HTML representation of the content resource.
        """
        html = '<div id="title"><h1>Gyrid dashboard</h1></div><div id="updated">%s</div>' % time.strftime('%H:%M:%S')
        html += '<div style="clear: both;"></div>'

        html += self.renderServer()
        html += self.renderProjectList()

        projects = self.plugin.server.dataprovider.projects
        self.plugin.matchAll()

        # Active projects
        for p_name in sorted([p.name for p in projects.values() if p.isActive()]):
            html += self.renderProject(projects[p_name])

        # Inactive projects
        for p_name in sorted([p.name for p in projects.values() if not p.isActive()]):
            html += self.renderProject(projects[p_name])

        # Clean old scanners
        to_delete = [s for s in self.plugin.scanners if self.plugin.scanners[s].isOld()]
        for i in to_delete:
            del(self.plugin.scanners[i])

        # Projectless scanners
        projectless_scanners = sorted([s for s in self.plugin.scanners if self.plugin.scanners[s].project == None])

        if len(projectless_scanners) > 0:
            html += '<div class="h2-outline" id="No-project"><h2 onclick="goTo(\'#server_block\')">No project</h2>'
            html += '<div class="block_content"><div class="block_data">'
            html += '<img src="/dashboard/static/icons/radar-grey.png">Inactive</div></div></div>'
            html += '<div id="navigation_block">'
            for scanner in projectless_scanners:
                s = self.plugin.scanners[scanner]
                html += s.renderNavigation()
            html += '</div>'
            for scanner in projectless_scanners:
                s = self.plugin.scanners[scanner]
                html += s.render()

        html += self.renderFooter()

        return html

class StaticResource(File):
    """
    Class representing a resource for serving static files without directory listing.

    Used to serve header images and icons.
    """
    def __init__(self, path, defaultType='text/html', ignoredExts=(),
        registry=None, allowExt=0):
        """
        Initialisation.
        """
        File.__init__(self, path, defaultType, ignoredExts, registry, allowExt)

    def directoryListing(self):
        """
        Reimplement to disable directory listing.
        """
        class NoneRenderer:
            def render(self, arg):
                return ""
        return NoneRenderer()

class AuthenticationRealm(object):
    """
    Implement basic authentication for the dashboard webpage.
    """
    implements(IRealm)

    def __init__(self, plugin):
        """
        Initialisation.

        @param   plugin (Plugin)   Reference to main Status plugin instance.
        """
        self.plugin = plugin

    def requestAvatar(self, avatarId, mind, *interfaces):
        if IResource in interfaces:
            return (IResource, ContentResource(self.plugin), lambda: None)
        else:
            raise NotImplementedError()

def formatNumber(number):
    """
    Format the given number with a HTML span-class as thousand separator and two decimals in the case of a float.

    @param    number (int, long, float)   The number to format.
    @return   (str)                       HTML representation of the given number.
    """
    if (type(number) is int) or (type(number) is long):
        return '{:,.0f}'.format(number).replace(',', '<span class="thousandSep"></span>')
    elif type(number) is float:
        return '{:,.2f}'.format(number).replace(',', '<span class="thousandSep"></span>')

class Plugin(olof.core.Plugin):
    """
    Main Status plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation. Read saved data from disk, start looping calls that check system resources and read SIM card
        data and serve the dashboard webpage.

        @param   server (Olof)   Reference to the main Olof server instance.
        """
        olof.core.Plugin.__init__(self, server, filename)
        self.root = RootResource()

        status_resource = self.root
        self.root.putChild("dashboard", status_resource)

        portal = Portal(AuthenticationRealm(self), [FilePasswordDB(
            'olof/plugins/dashboard/data/auth.password')])
        credfac = BasicCredentialFactory("Gyrid Server")
        rsrc = HTTPAuthSessionWrapper(portal, [credfac])
        status_resource.putChild("content", rsrc)

        status_resource.putChild("static",
            StaticResource("olof/plugins/dashboard/static/"))

        if os.path.isfile("olof/plugins/dashboard/data/obj.pickle"):
            try:
                f = open("olof/plugins/dashboard/data/obj.pickle", "rb")
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

        try:
            import multiprocessing
            self.cpuCount = multiprocessing.cpu_count()
        except:
            self.cpuCount = 1

        self.parseMVNumbers()

        t = task.LoopingCall(self.checkResources)
        t.start(10)

        reactor.callLater(2, self.startListening)

    def defineConfiguration(self):
        """
        Define the configuration options for this plugin.
        """
        def validateMVNumbers(value):
            """
            Validate Mobile Vikings MSISDN mapping.
            """
            d = {}
            tel_re = re.compile(r'\+32[0-9]{9}')

            for i in value:
                if tel_re.match(value[i]) != None:
                    d[i] = value[i]
            return d

        options = []

        o = olof.configuration.Option('tcp_port')
        o.setDescription('TCP port to serve the dashboard on.')
        o.setValidation(olof.tools.validation.parseInt)
        o.addValue(olof.configuration.OptionValue(8080, default=True))
        options.append(o)

        o = olof.configuration.Option('mobilevikings_api_url')
        o.setDescription('Base URL of the Mobile Vikings basic API.')
        o.addValue(olof.configuration.OptionValue('https://mobilevikings.com/api/2.0/basic', default=True))
        o.addCallback(self.updateMVConnectionConfig)
        options.append(o)

        o = olof.configuration.Option('mobilevikings_api_username')
        o.setDescription('Username to use to log in to the Mobile Vikings API.')
        o.addCallback(self.updateMVConnectionConfig)
        options.append(o)

        o = olof.configuration.Option('mobilevikings_api_password')
        o.setDescription('Password to use to log in to the Mobile Vikings API.')
        o.addCallback(self.updateMVConnectionConfig)
        options.append(o)

        o = olof.configuration.Option('mobilevikings_msisdn_mapping')
        o.setDescription('Dictionary mapping hostnames to Mobile Vikings MSISDN ID\'s (telephone numbers).')
        o.setValidation(validateMVNumbers)
        o.addCallback(self.parseMVNumbers)
        o.addValue(olof.configuration.OptionValue({}, default=True))
        options.append(o)

        return options

    def updateMVConnectionConfig(self, value=None):
        """
        Update the Mobile Vikings API details for all current scanners.
        """
        mv_url = self.config.getValue('mobilevikings_api_url')
        mv_user = self.config.getValue('mobilevikings_api_username')
        mv_pwd = self.config.getValue('mobilevikings_api_password')

        for s in self.scanners.values():
            s.initMVConnection(mv_url, mv_user, mv_pwd)

    def startListening(self):
        """
        Start listening for incoming requests. Called automatically after initialisation.
        """
        self.listeningPort = reactor.listenTCP(self.config.getValue('tcp_port'), tserver.Site(self.root))

    def match(self, location):
        """
        Match the given Location to a Scanner, based on the location's ID which should be the scanner's hostname.

        When a match is found, the scanners details are updated based on the information saved in the location instance.
        When no match is found, a new scanner with the correct details is created.

        @param    location (olof.datatypes.Location)   Location to match.
        @return   (Scanner)                            Matching scanner.
        """
        def compare(a, b):
            """
            Compare two variables. If both are olof.datatypes.Project instances, compare their name.
            """
            if type(a) == type(b) == olof.datatypes.Project:
                return a.name == b.name
            else:
                return a == b

        s = self.getScanner(location.id)
        if s != None:
            if False in [compare(s.__dict__[i], location.__dict__[i]) for i in ['project', 'lat', 'lon']]:
                s.sensors = {}
            s.project = location.project
            s.lon = location.lon
            s.lat = location.lat
            s.location = location.name
            s.location_description = location.description
        return s

    def matchAll(self):
        """
        Match all Locations from the dataprovider to the Scanners and vice versa.
        """
        for l in self.server.dataprovider.locations.values():
            self.match(l)

        for s in self.scanners.values():
            found_location = False
            for l in self.server.dataprovider.locations.values():
                if l.id == s.hostname:
                    found_location = True
                    break
            if not found_location:
                s.project = None
                s.sensors = {}

    def checkResources(self):
        """
        Check system resources. Reads information from the proc filesystem and updates variables for later use.
        """
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

    def parseMVNumbers(self, msisdn_map=None):
        """
        Parse the Mobile Vikings MSISDN mapping, matching the numbers to the corresponding scanners.

        @param   msisdn_map (dict)   MSISDN mapping. Optional: when omitted the current configuration value is used.
        """
        if msisdn_map == None:
            msisdn_map = self.config.getValue('mobilevikings_msisdn_mapping')
        for s in self.scanners.values():
            if s.hostname in msisdn_map:
                s.msisdn = msisdn_map[s.hostname]
            else:
                s.msisdn = None
                s.mv_balance = {}
                s.mv_updated = None

    def unload(self, shutdown=False):
        """
        Unload this plugin. Stop listening, stop looping calls and save scanner data to disk.
        """
        olof.core.Plugin.unload(self)
        self.listeningPort.stopListening()

        for s in self.scanners.values():
            if shutdown:
                if len(s.connections) > 0:
                    s.lastConnected = int(time.time())
                s.conn_time = {}
                s.connections = set()
            s.checkLagCall('stop')
            s.checkMVBalanceCall('stop')
            if 'checkLag_call' in s.__dict__:
                del(s.checkLag_call)
            if 'checkMVBalance_call' in s.__dict__:
                del(s.checkMVBalance_call)

        f = open("olof/plugins/dashboard/data/obj.pickle", "wb")
        pickle.dump(self.scanners, f)
        f.close()

    def getScanner(self, hostname, create=True):
        """
        Get a Scanner instance for the given hostname.

        @param    hostname (str)   The hostname of the scanner.
        @param    create (bool)    Create the instance if none exists yet for the given hostname. Defaults to True.
        @return   (Scanner)        Scanner instance for the given hostname.
        """
        if not hostname in self.scanners and create:
            s = Scanner(hostname,
                mv_url = self.config.getValue('mobilevikings_api_url'),
                mv_user = self.config.getValue('mobilevikings_api_username'),
                mv_pwd = self.config.getValue('mobilevikings_api_password'))
            self.scanners[hostname] = s
            self.parseMVNumbers()
        elif hostname in self.scanners:
            s = self.scanners[hostname]
        else:
            s = None
        return s

    def getSensor(self, hostname, mac):
        """
        Get a Sensor instance for the given hostname and MAC-address combination.
        If none exists yet, create a new one.

        @param    hostname (str)   Hostname of the scanner.
        @param    mac (str)        MAC-address of the Bluetooth sensor.
        @return   (Sensor)         Corresponding Sensor.
        """
        s = self.getScanner(hostname)
        if not mac in s.sensors:
            sens = Sensor(mac)
            s.sensors[mac] = sens
        else:
            sens = s.sensors[mac]
        return sens

    def uptime(self, hostname, host_uptime, gyrid_uptime):
        """
        Save the received uptime information in the corresponding Scanner instance.
        """
        s = self.getScanner(hostname)
        s.host_uptime = int(float(host_uptime))
        s.gyrid_uptime = int(float(gyrid_uptime))
        s.gyrid_connected = True

    def connectionMade(self, hostname, ip, port):
        """
        Save the connection information in the corresponding Scanner instance.
        """
        s = self.getScanner(hostname)
        s.connections.add((ip, port))
        s.getProvider(ip)
        s.conn_time['made'] = int(time.time())
        s.gyrid_uptime = None
        s.host_uptime = None
        s.gyrid_connected = True
        s.lastConnected = int(time.time())

    def connectionLost(self, hostname, ip, port):
        """
        Save the connection information in the corresponding Scanner instance.
        """
        s = self.getScanner(hostname)
        if (ip, port) in s.connections:
            s.connections.remove((ip, port))
        s.conn_time['lost'] = int(time.time())
        s.lastConnected = int(time.time())
        for sens in s.sensors.values():
            sens.connected = False

    def sysStateFeed(self, hostname, module, info):
        """
        Save the Gyrid connection information in the corresponding Scanner instance.
        """
        s = self.getScanner(hostname)
        if module == 'gyrid':
            if info == 'connected':
                s.gyrid_connected = True
            elif info == 'disconnected':
                s.gyrid_connected = False
                s.gyrid_disconnect_time = int(time.time())

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        """
        Save the Bluetooth sensor informatio in the corresponding Sensor instance.
        """
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
        """
        Save detection information in the corresponding Sensor instance.
        """
        sens = self.getSensor(hostname, sensor_mac)
        sens.detections += 1
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp

        scann = self.getScanner(hostname)
        t = time.time()
        scann.lagData.append([t, float(timestamp), mac])
