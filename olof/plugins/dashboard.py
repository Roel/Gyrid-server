#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin that provides a status dashboard webpage.
"""

DYNAMIC_LOADING = False

from twisted.cred.checkers import FilePasswordDB
from twisted.cred.portal import IRealm, Portal
from twisted.internet import reactor, task, threads
from twisted.web.guard import HTTPAuthSessionWrapper, BasicCredentialFactory
from twisted.web import resource
from twisted.web import server as tserver
from twisted.web.resource import IResource
from twisted.web.static import File

from zope.interface import implements

import datetime
import math
import os
import re
import time

import olof.configuration
import olof.core
import olof.storagemanager
import olof.tools.validation

from olof.plugins.dashboard.scanner import formatNumber, htmlSpanWrapper, Scanner, ScannerStatus, BluetoothSensor, WiFiSensor
from olof.tools.datetimetools import getRelativeTime

class RootResource(resource.Resource):
    """
    Class representing the root resource for the webpage.

    This resource basically serves the olof/plugins/dashboard/static/index.html page.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        Read the index.html page from disk.

        @param   plugin (Plugin)   Reference to main Olof plugin instance.
        """
        resource.Resource.__init__(self)
        self.plugin = plugin

        f = open(self.plugin.base_path + '/static/index.html', 'r')
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
        return str(self.rendered_page)

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
        html += '<div class="block_topright_server">%s<img alt="" src="/dashboard/static/icons/clock-arrow.png"></div>' % \
            getRelativeTime(self.plugin.server.server_uptime, pastSuffix="", wrapper=htmlSpanWrapper)
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'

        if self.plugin.connectionLagProcessing == False or \
            self.plugin.config.getValue('connection_lag_processing') == False:
            html += '<div class="block_data">'
            html += '<img alt="" src="/dashboard/static/icons/warning.png">Warning'
            html += '<span class="block_data_attr">connection lag calculation disabled</span>'
            html += '</div>'

        plugins = [p for p in self.plugin.server.pluginmgr.getPlugins() if p.name != None]

        # Resources
        if len(plugins) < 1 or ((len(self.plugin.load) > 0 and len([i for i in self.plugin.load[1:] if float(i) >= (
            self.plugin.cpuCount*0.8)]) > 0) or int(self.plugin.memfree_mb) <= 256 or self.plugin.diskfree_mb <= 2048):
            html += '<div class="block_data">'
            html += '<img alt="" src="/dashboard/static/icons/system-monitor.png">Resources'
            html += '<span class="block_data_attr"><b>load</b> ' + \
                '<span title="1, 5 and 15 minutes moving averages">%s</span></span>' % ', '.join(self.plugin.load)
            html += '<span class="block_data_attr"><b>ram free</b> %s</span>' % (formatNumber(
                self.plugin.memfree_mb) + ' MB')
            html += '<span class="block_data_attr"><b>disk free</b> %s</span>' % (formatNumber(
                self.plugin.diskfree_mb) + ' MB')
            html += '</div>'

        # Plugins
        for p in plugins:
            html += '<div class="block_data">'
            st = p.getStatus()
            if 'status' in st[0] and st[0]['status'] == 'error':
                html += '<img alt="" src="/dashboard/static/icons/puzzle-red.png">%s' % p.name
            elif 'status' in st[0] and st[0]['status'] == 'disabled':
                html += '<img alt="" src="/dashboard/static/icons/puzzle-grey.png">%s' % p.name
            else:
                html += '<img alt="" src="/dashboard/static/icons/puzzle.png">%s' % p.name
            for i in st:
                if len(i) == 1 and 'id' in i:
                    html += '<span class="block_data_attr">%s</span>' % i['id']
                elif len(i) > 1 and 'time' in i:
                    html += '<span class="block_data_attr"><b>%s</b> %s</span>' % (i['id'], getRelativeTime(
                        i['time'], wrapper=htmlSpanWrapper))
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
                html += '<img alt="" src="/dashboard/static/icons/radar.png">'
                html += '<a href="#" onclick="goTo(\'#%s\')">%s</a>' % (p.id, p.name)
                html += '<span class="block_data_attr">active</span>'
            else:
                html += '<img alt="" src="/dashboard/static/icons/radar-grey.png">'
                html += '<a href="#" onclick="goTo(\'#%s\')">%s</a>' % (p.id, p.name)
                html += '<span class="block_data_attr">inactive</span>'
            html +='<span class="block_data_attr"><b>scanners</b> %s</span>' % formatNumber(len(p.locations))
            if p.start:
                html += '<span class="block_data_attr"><b>start</b> %s</span>' % getRelativeTime(p.start,
                    wrapper=htmlSpanWrapper, levels=2)
            if p.end:
                html += '<span class="block_data_attr"><b>end</b> %s</span>' % getRelativeTime(p.end,
                    wrapper=htmlSpanWrapper, levels=2)
            if len(p.disabled_plugins) > 0:
                html += '<span class="block_data_attr"><b>disabled</b> %s</span>' % ', '.join(sorted(
                    p.disabled_plugins))
            html += '</div>'
            return html

        projects = self.plugin.server.dataprovider.projects
        if len(projects) <= 1:
            return ""

        html = '<div id="project_block"><div class="block_title"><h3>Projects</h3></div>'
        html += '<div style="clear: both;"></div>'
        html += '<div class="block_content">'

        # Active projects
        for pid in sorted([p.id for p in projects.values() if p.isActive()]):
            html += renderProject(projects[pid])

        # Inactive projects
        for pid in sorted([p.id for p in projects.values() if not p.isActive()]):
            html += renderProject(projects[pid])

        html += '</div></div>'
        return html

    def renderProject(self, project):
        """
        Render a specific project to HTML.

        @param    project (olof.datatypes.Project)   Project to render.
        @return   (str)                              HTML representation of the project.
        """
        html = '<div class="h2-outline" id="%s"><h2 onclick="goTo(\'#server_block\')">%s</h2>' % \
            (project.id, project.name)
        html += '<div class="block_content"><div class="block_data">'

        if project.isActive():
            html += '<img alt="" src="/dashboard/static/icons/radar.png">Active'
        else:
            html += '<img alt="" src="/dashboard/static/icons/radar-grey.png">Inactive'
        if project.start:
            html += '<span class="block_data_attr"><b>start</b> %s</span>' % getRelativeTime(project.start,
                wrapper=htmlSpanWrapper, levels=2)
        if project.end:
            html += '<span class="block_data_attr"><b>end</b> %s</span>' % getRelativeTime(project.end,
                wrapper=htmlSpanWrapper, levels=2)
        html += '</div>'

        if len(project.disabled_plugins) > 0:
            html += '<div class="block_data"><img alt="" src="/dashboard/static/icons/puzzle-grey.png">Disabled plugins'
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
            html += '<div class="block_data"><img alt="" src="/dashboard/static/icons/traffic-light-single.png">Scanner status'
            html += '<span class="block_data_attr"><b>total</b> %s</span>' % formatNumber(len(project.locations))
            if scanner_status[ScannerStatus.Good] > 0:
                html += '<span class="block_data_attr"><b>online</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                    ScannerStatus.Good]), scanner_status[ScannerStatus.Good]*100/len(project.locations))
            if scanner_status[ScannerStatus.Bad] > 0:
                html += '<span class="block_data_attr"><b>offline</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                    ScannerStatus.Bad]), scanner_status[ScannerStatus.Bad]*100/len(project.locations))
            if scanner_status[ScannerStatus.Ugly] > 0:
                html += '<span class="block_data_attr"><b>attention</b> %s – %i%%</span>' % (formatNumber(scanner_status[
                    ScannerStatus.Ugly]), scanner_status[ScannerStatus.Ugly]*100/len(project.locations))
            html += '</div>'

        html += '</div></div>'

        html += '<div class="navigation_block">'
        for location in sorted(project.locations.keys()):
            html += self.plugin.match(project.locations[location]).renderNavigation(project.id)
        html += '</div>'

        for location in sorted(project.locations.keys()):
            html += self.plugin.match(project.locations[location]).render(project.id)

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

        # Clean old scanners
        to_delete = [s for s in self.plugin.scanners if self.plugin.scanners[s].isOld()]
        for i in to_delete:
            self.plugin.scanners[i].unload()
            del(self.plugin.scanners[i])

        # Active projects
        for pid in sorted([p.id for p in projects.values() if p.isActive()]):
            html += self.renderProject(projects[pid])

        # Inactive projects
        for pid in sorted([p.id for p in projects.values() if not p.isActive()]):
            html += self.renderProject(projects[pid])

        # Projectless scanners
        projectless_scanners = sorted([s for s in self.plugin.scanners if len(self.plugin.scanners[s].projects) < 1])

        if len(projectless_scanners) > 0:
            html += '<div class="h2-outline" id="No-project"><h2 onclick="goTo(\'#server_block\')">No project</h2>'
            html += '<div class="block_content"><div class="block_data">'
            html += '<img alt="" src="/dashboard/static/icons/radar-grey.png">Inactive</div></div></div>'
            html += '<div class="navigation_block">'
            for scanner in projectless_scanners:
                s = self.plugin.scanners[scanner]
                html += s.renderNavigation()
            html += '</div>'
            for scanner in projectless_scanners:
                s = self.plugin.scanners[scanner]
                html += s.render()

        return str(html)

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
        self.base_path = self.server.paths['plugins'] + '/dashboard'

        self.root = RootResource(self)
        status_resource = self.root
        self.root.putChild("dashboard", status_resource)

        authFile = self.base_path + '/data/auth.password'
        if os.path.isfile(authFile):
            portal = Portal(AuthenticationRealm(self), [FilePasswordDB(authFile)])
            credfac = BasicCredentialFactory("Gyrid Server")
            rsrc = HTTPAuthSessionWrapper(portal, [credfac])
            status_resource.putChild("content", rsrc)
        else:
            status_resource.putChild("content", ContentResource(self))

        status_resource.putChild("static", StaticResource(self.base_path + "/static/"))

        self.scanners = self.storage.loadObject('scanners', {})
        for s in self.scanners.values():
            s.init(self)
            for sens in s.sensors.values():
                sens.init()

        try:
            import multiprocessing
            self.cpuCount = multiprocessing.cpu_count()
        except:
            self.cpuCount = 1

        self.connectionLagProcessing = True

        self.parseMVNumbers()
        self.updateConnectionLagConfig()

        self.checkResourcesCall = task.LoopingCall(self.checkResources)
        self.checkResourcesCall.start(10)

        reactor.callLater(2, self.startListening)

    def defineConfiguration(self):
        """
        Define the configuration options for this plugin.
        """
        def validateMVNumbers(value):
            """
            Validate Mobile Vikings MSISDN mapping.
            """
            if type(value) is not dict:
                raise olof.tools.validation.ValidationError()

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

        o = olof.configuration.Option('connection_lag_processing')
        o.setDescription('Calculate connection lag based on recently received detections. ' + \
            'This can be CPU and memory intensive.')
        o.addValue(olof.configuration.OptionValue(True, default=True))
        o.addValue(olof.configuration.OptionValue(False))
        o.addCallback(self.updateConnectionLagConfig)
        options.append(o)

        return options

    def updateMVConnectionConfig(self, value=None):
        """
        Update the Mobile Vikings API details for all current scanners.
        """
        for s in self.scanners.values():
            s.initMVConnection()

    def updateConnectionLagConfig(self, value=None):
        """
        Update the connection lag calculation based on the configuration value.
        """
        value = self.connectionLagProcessing and self.config.getValue('connection_lag_processing')

        if value == False:
            for s in self.scanners.values():
                for se in s.sensors.values():
                    se.lagData = []

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
            if False in [compare(s.__dict__[i], location.__dict__[i]) for i in ['lat', 'lon']]:
                s.sensors = {}
            s.projects = location.projects
            s.lon = location.lon
            s.lat = location.lat
            s.location = location.name
            s.sensor_count = len(location.sensors)
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
                if len(s.projects) > 0:
                    s.sensors = {}
                    s.projects = set()
                    s.sensor_count = None

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

        if self.connectionLagProcessing == True:
            clp = not (float(self.load[2]) > (self.cpuCount*1.75)) or (self.memfree_mb < 60)
        else:
            clp = not (float(self.load[2]) > (self.cpuCount*1)) or (self.memfree_mb < 100)
        if clp != self.connectionLagProcessing:
            self.connectionLagProcessing = clp
            self.updateConnectionLagConfig(clp)

    def parseMVNumbers(self, msisdnMap=None):
        """
        Parse the Mobile Vikings MSISDN mapping, matching the numbers to the corresponding scanners.

        @param   msisdnMap (dict)   MSISDN mapping. Optional: when omitted the current configuration value is used.
        """
        if msisdnMap == None:
            msisdnMap = self.config.getValue('mobilevikings_msisdn_mapping')
        for s in self.scanners.values():
            if s.hostname in msisdnMap:
                s.msisdn = msisdnMap[s.hostname]
            else:
                s.msisdn = None
                s.mv_balance = {}
                s.mv_updated = None

    def unload(self, shutdown=False):
        """
        Unload this plugin. Stop listening, stop looping calls and save scanner data to disk.
        """
        olof.core.Plugin.unload(self, shutdown)
        try:
            self.checkResourcesCall.stop()
        except AssertionError:
            pass

        if 'listeningPort' in self.__dict__:
            self.listeningPort.stopListening()

        for s in self.scanners.values():
            s.unload(shutdown)

        self.storage.storeObject(self.scanners, 'scanners')

    def getScanner(self, hostname, create=True):
        """
        Get a Scanner instance for the given hostname.

        @param    hostname (str)   The hostname of the scanner.
        @param    create (bool)    Create the instance if none exists yet for the given hostname. Defaults to True.
        @return   (Scanner)        Scanner instance for the given hostname.
        """
        if not hostname in self.scanners and create:
            s = Scanner(self, hostname)
            self.scanners[hostname] = s
            self.parseMVNumbers()
        elif hostname in self.scanners:
            s = self.scanners[hostname]
        else:
            s = None
        return s

    def getSensor(self, hostname, hwType, mac):
        """
        Get a Sensor instance for the given hostname and MAC-address combination.
        If none exists yet, create a new one.

        @param    hostname (str)   Hostname of the scanner.
        @param    mac (str)        MAC-address of the Bluetooth sensor.
        @return   (Sensor)         Corresponding Sensor.
        """
        s = self.getScanner(hostname)
        if not mac in s.sensors:
            if hwType == 'bluetooth':
                sens = BluetoothSensor(mac)
            elif hwType == 'wifi':
                sens = WiFiSensor(mac)
            s.sensors[mac] = sens
        else:
            sens = s.sensors[mac]
        return sens

    def uptime(self, hostname, projects, hostUptime, gyridUptime):
        """
        Save the received uptime information in the corresponding Scanner instance.
        """
        s = self.getScanner(hostname)
        s.host_uptime = int(float(hostUptime))
        s.gyrid_uptime = int(float(gyridUptime))
        s.gyrid_connected = True

    def connectionMade(self, hostname, projects, ip, port):
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

    def connectionLost(self, hostname, projects, ip, port):
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

    def sysStateFeed(self, hostname, projects, module, info):
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

    def stateFeed(self, hostname, projects, timestamp, hwType, sensorMac, type, info, cache):
        """
        Save the Bluetooth sensor information in the corresponding Sensor instance.
        """
        sens = self.getSensor(hostname, hwType, sensorMac)
        if type in ('new_inquiry', 'frequency', 'frequency_loop'):
            sens.connected = True
            if sens.last_activity == None or timestamp > sens.last_activity:
                sens.last_activity = timestamp
        elif type == 'started_scanning':
            sens.connected = True
        elif type == 'stopped_scanning':
            sens.connected = False
            sens.disconnect_time = int(float(timestamp))
        elif type == 'antenna':
            sens.last_rotation = int(float(timestamp))

    def dataFeedBluetoothRaw(self, hostname, projects, timestamp, sensorMac, mac, deviceclass, rssi, angle, cache):
        """
        Save detection information in the corresponding Sensor instance.
        """
        sens = self.getSensor(hostname, 'bluetooth', sensorMac)
        sens.detections += 1
        if sens.last_activity == None or timestamp > sens.last_activity:
            sens.last_activity = timestamp
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp

        if self.connectionLagProcessing and self.config.getValue('connection_lag_processing'):
            t = time.time()
            sens.lagData.append([t, float(timestamp), mac])

    def dataFeedWifiDevRaw(self, hostname, projects, timestamp, sensorMac, hwid, ssi, freq, cache):
        sens = self.getSensor(hostname, 'wifi', sensorMac)
        sens.detections += 1
        if sens.last_activity == None or timestamp > sens.last_activity:
            sens.last_activity = timestamp
        if sens.last_data == None or timestamp > sens.last_data:
            sens.last_data = timestamp

        if self.connectionLagProcessing and self.config.getValue('connection_lag_processing'):
            t = time.time()
            sens.lagData.append([t, float(timestamp), hwid])

    def dataFeedWifiIO(self, hostname, projects, timestamp, sensorMac, hwid, type, move, cache):
        sens = self.getSensor(hostname, 'wifi', sensorMac)

        if type == 'acp':
            if move == 'in':
                sens.accesspoints += 1
            elif move == 'out' and sens.accesspoints > 0:
                sens.accesspoints -= 1
        elif type == 'dev':
            if move == 'in':
                sens.devices += 1
            elif move == 'out' and sens.devices > 0:
                sens.devices -= 1
