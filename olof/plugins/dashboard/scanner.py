#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module providing storage-safe classes for use in dashboard plugin.
"""

from twisted.internet import reactor, task, threads

import pickle
import subprocess
import time
import urllib2

import olof.plugins.dashboard.macvendor as macvendor

from olof.tools.datetimetools import getRelativeTime
from olof.tools.webprotocols import RESTConnection

def htmlSpanWrapper(timestamp):
    """
    Wrapper method to use when formatting relative timestamps using olof.tools.datetimetools.getRelativeTime
    """
    return '<span title="%s">' % timestamp.strftime('%a %Y-%m-%d %H:%M:%S'), '</span>'

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
    def __init__(self, plugin, hostname):
        """
        Initialisation.

        @param   plugin (olof.core.Plugin)   Reference to main Dashboard plugin instance.
        @param   hostname (str)              Hostname of the scanner.
        """
        self.hostname = hostname
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

        self.init(plugin)

    def init(self, plugin):
        """
        Reinitialise variables that need updating when the plugin starts.

        __init__() is called when a new Scanner is created, this init() is called at __init__() and after the
        saved Scanner data is read at plugin start.

        @param   plugin (olof.core.Plugin)   Reference to main Dashboard plugin instance.
        """
        self.plugin = plugin
        self.lag = {1: [0, 0], 5: [0, 0], 15: [0, 0]}

        self.initMVConnection()

        self.checkLag_call = task.LoopingCall(reactor.callInThread,
            self.checkLag)
        self.checkLagCall('start')

        self.checkMVBalance_call = task.LoopingCall(reactor.callInThread,
            self.getMVBalance)
        self.checkMVBalanceCall('start')

    def initMVConnection(self):
        """
        Initialise a Mobile Vikings REST connection with the given details. If any of the arguments is None, delete
        any existing connection.
        """
        url = self.plugin.config.getValue('mobilevikings_api_url')
        username = self.plugin.config.getValue('mobilevikings_api_username')
        password = self.plugin.config.getValue('mobilevikings_api_password')

        if None not in [url, username, password]:
            self.mv_conn = RESTConnection(
                baseUrl = url,
                username = username,
                password = password,
                authHandler = urllib2.HTTPBasicAuthHandler)
        else:
            self.mv_conn = None

    def unload(self, shutdown=False):
        """
        Unload this scanner.
        """
        if shutdown:
            if len(self.connections) > 0:
                self.lastConnected = int(time.time())
            self.conn_time = {}
            self.connections = set()
        del(self.plugin)
        self.checkLagCall('stop')
        self.checkMVBalanceCall('stop')
        if 'checkLag_call' in self.__dict__:
            del(self.checkLag_call)
        if 'checkMVBalance_call' in self.__dict__:
            del(self.checkMVBalance_call)

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
                except Exception, e:
                    self.plugin.logger.logError('Error requesting Mobile Vikings balance for %s (%s): %s' % \
                        (self.hostname, self.msisdn, e))
            else:
                self.plugin.logger.logError('Error requesting Mobile Vikings balance for %s (%s)' % \
                    (self.hostname, self.msisdn))

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
                html += '%s<img alt="" src="/dashboard/static/icons/marker.png">' % self.location
            elif self.location != None:
                loc = '<span title="%s">%s</span>' % (self.location_description, self.location) if \
                    self.location_description != None else self.location
                html += '<a href="%s">%s</a><img alt="" src="/dashboard/static/icons/marker.png">' % (
                    ("http://maps.google.be/maps?z=17&amp;q=loc:%s,%s(%s)" % (self.lat, self.lon, self.hostname)), loc)
            if self.project == None:
                goto = 'No-project'
            else:
                goto = self.project.name.replace(' ','-')
            html += '</div><div style="clear: both;"></div><div class="block_content" onclick="goTo(\'#%s\')">' % goto

            if self.location_description:
                html += '<div class="block_data_location">%s</div>' % self.location_description

            return html

        def renderUptime():
            html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/clock-arrow.png">Uptime'
            if 'made' in self.conn_time:
                html += '<span class="block_data_attr"><b>connection</b> %s</span>' % getRelativeTime(int(float(
                    self.conn_time['made'])), pastSuffix="", wrapper=htmlSpanWrapper)
            if self.gyrid_uptime != None and self.gyrid_connected == True:
                html += '<span class="block_data_attr"><b>gyrid</b> %s</span>' % getRelativeTime(self.gyrid_uptime,
                    pastSuffix="", wrapper=htmlSpanWrapper)
            if self.host_uptime != None:
                html += '<span class="block_data_attr"><b>system</b> %s</span>' % getRelativeTime(self.host_uptime,
                    pastSuffix="", wrapper=htmlSpanWrapper)
            html += '</div>'
            return html

        def renderLag():
            lag = [(self.lag[i][0]/self.lag[i][1]) for i in sorted(
                self.lag.keys()) if (i <= 15 and self.lag[i][1] > 0)]
            if len([i for i in lag[1:] if i >= 5]) > 0:
                provider = self.ip_provider.get(list(self.connections)[0][0], (None, None))[0]
                html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/network-cloud.png">Network'
                l = []
                for i in sorted(self.lag.keys()):
                    if i <= 15:
                        if self.lag[i][1] == 0:
                            l.append('nd')
                        else:
                            avg = self.lag[i][0]/self.lag[i][1]
                            if avg < 60:
                                l.append(formatNumber(float("%0.2f" % (avg))) + 's')
                            else:
                                l.append(getRelativeTime(time.time()-avg, pastSuffix=""))
                if len([i for i in l if i != 'nd']) > 0:
                    html += '<span class="block_data_attr"><b>lag</b> ' + \
                        '<span title="1, 5 and 15 minutes moving averages">%s</span></span>' %  ', '.join(l)
                html += '<span class="block_data_attr"><b>ip</b> %s</span>' % list(self.connections)[0][0]
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
                    html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/shield-red.png">SIM balance'
                elif mb <= 500:
                    html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/shield-yellow.png">SIM balance'
                elif 'is_expired' in self.mv_balance and self.mv_balance['is_expired']:
                    html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/shield-red.png">SIM balance'
                elif 'valid_until' in self.mv_balance and not self.mv_balance['is_expired']:
                    if int(time.strftime('%s', time.strptime(self.mv_balance['valid_until'], '%Y-%m-%d %H:%M:%S'))) - \
                        int(time.time()) <= 60*60*24*7:
                        html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/shield-yellow.png">SIM balance'
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
                        getRelativeTime(float(time.strftime('%s', time.strptime(self.mv_balance['valid_until'],
                        '%Y-%m-%d %H:%M:%S'))), wrapper=htmlSpanWrapper)
                if self.mv_updated:
                    html += '<span class="block_data_attr"><b>updated</b> %s</span>' % getRelativeTime(self.mv_updated,
                        wrapper=htmlSpanWrapper)
                html += '</div>'
                return html
            else:
                return ''

        def renderDetections():
            detc = [self.lag[i][1] for i in sorted(self.lag.keys()) if i <= 15]
            udetc = [self.lag[i][2] for i in sorted(self.lag.keys()) if i <= 15]
            if len([i for i in detc if i > 0]) > 0:
                html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/users.png">Detections'
                html += '<span class="block_data_attr"><b>recently received</b> ' + \
                    '<span title="1, 5 and 15 minutes moving averages">%s</span></span>' % \
                    ', '.join([formatNumber(i) for i in detc])
                sensors_connected = len([s for s in self.sensors.values() if s.connected == True])
                html += '<span class="block_data_attr"><b>unique</b> ' + \
                    '<span title="1, 5 and 15 minutes moving averages">%s</span></span>' % \
                    ', '.join([formatNumber(i) for i in udetc])
                html += '</div>'
                return html
            else:
                return ""

        def renderNotconnected(disconnectTime, pastSuffix=""):
            html = '<div class="block_data"><img alt="" src="/dashboard/static/icons/traffic-cone.png">' + \
                'No connection%s' % pastSuffix
            if disconnectTime != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % getRelativeTime(int(float(
                    disconnectTime)), wrapper=htmlSpanWrapper)
            elif pastSuffix == "" and self.lastConnected != None:
                html += '<span class="block_data_attr"><b>last connected</b> %s</span>' % getRelativeTime(int(float(
                    self.lastConnected)), wrapper=htmlSpanWrapper)

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
            html += '<img alt="" src="/dashboard/static/icons/plug-disconnect.png">%s' % mac
            if self.disconnect_time != None:
                html += '<span class="block_data_attr"><b>disconnected</b> %s</span>' % getRelativeTime(int(float(
                    self.disconnect_time)), wrapper=htmlSpanWrapper)
        else:
            html += '<img alt="" src="/dashboard/static/icons/bluetooth.png">%s' % mac
            if self.last_inquiry != None:
                html += '<span class="block_data_attr"><b>last inquiry</b> %s</span>' % getRelativeTime(int(float(
                    self.last_inquiry)), wrapper=htmlSpanWrapper)
        if self.last_data != None:
            html += '<span class="block_data_attr"><b>last data</b> %s</span>' % getRelativeTime(int(float(
                self.last_data)), wrapper=htmlSpanWrapper)
        if self.detections > 0:
            html += '<span class="block_data_attr"><b>detections</b> %s</span>' % formatNumber(self.detections)
        html += '</div>'
        return html
