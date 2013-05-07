#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

from twisted.internet import reactor, task, threads
from twisted.internet.protocol import Factory
from twisted.protocols.basic import Int16StringReceiver

import binascii
import os
import struct
import sys
import time
import traceback
import warnings
import zlib

import olof.configuration
import olof.dataprovider
import olof.datatypes
import olof.logger
import olof.pluginmanager
import olof.protocol.network as proto
import olof.storagemanager
import olof.tools.validation

def verifyCallback(connection, x509, errnum, errdepth, ok):
    """
    Check SSL certificates.

    @return   (bool)   True when the certificates are valid, else False.
    """
    if not ok:
        print 'invalid cert from subject:', x509.get_subject()
        return False
    else:
        #Certs are fine
        pass
    return True

class GyridServerProtocol(Int16StringReceiver):
    """
    The main Gyrid server protocol. This provides the interaction with the scanners.
    """
    def connectionMade(self):
        """
        Called when a new connection is made with a scanner. Initialise the connection.
        """
        self.last_keepalive = -1
        self.hostname = None

        self.buffer = []

        m = proto.Msg()
        m.type = m.Type_REQUEST_HOSTNAME
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_REQUEST_UPTIME
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_REQUEST_STATE
        m.requestState.bluetooth_enableInquiry = True
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_REQUEST_CACHING
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_REQUEST_KEEPALIVE
        m.requestKeepalive.interval = self.factory.timeout
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_KEEPALIVE
        self.sendMsg(m)

        m = proto.Msg()
        m.type = m.Type_REQUEST_STARTDATA
        m.requestStartdata.enableRaw = True
        self.sendMsg(m)

    def sendMsg(self, msg):
        self.sendString(struct.pack('!H', msg.ByteSize()) + msg.SerializeToString())

    def keepalive(self):
        """
        Keepalive method. Close the connection when the last keepalive was longer ago than the timeout value, reply with
        a keepalive otherwise.
        """
        t = self.factory.timeout
        if self.last_keepalive < (int(time.time())-(t+0.1*t)):
            self.transport.loseConnection()
        else:
            m = proto.Msg()
            m.type = m.Type_KEEPALIVE
            self.sendMsg(m)

    def connectionLost(self, reason):
        """
        Called when a connection has been lost.

        @param   reason (str)   The reason why the connection has been lost.
        """
        if self.hostname != None:
            dp = self.factory.server.dataprovider
            try:
                args = {'hostname': str(self.hostname),
                        'ip': str(self.transport.getPeer().host),
                        'port': int(self.transport.getPeer().port)}
            except:
                return
            else:
                ap = dp.getActivePlugins(self.hostname)
                for plugin in ap:
                    args['projects'] = ap[plugin]
                    plugin.connectionLost(**args)

    def checksum(self, data):
        """
        Calculate the CRC32 checksum of the given data.

        @param   data (str)   The data to check.
        @return  (hex)        The absolute (positive) hexadecimal CRC32 checksum of the data.
        """
        r = '%x' % abs(zlib.crc32(data))
        if len(r) % 2 != 0:
            r = '0' + r
        return r

    def stringReceived(self, data):
        """
        Process received data. The magic happens here!

        Depending on the type of information received, the corresponding method is called for all plugins with the
        correct arguments based on the received data.

        @param   data (str)   The data to process.
        """
        m = proto.Msg.FromString(data)
        dp = self.factory.server.dataprovider

        if m.type == m.Type_HOSTNAME:
            self.hostname = m.hostname.hostname
            try:
                args = {'hostname': str(self.hostname),
                        'ip': str(self.transport.getPeer().host),
                        'port': int(self.transport.getPeer().port)}
            except:
                return
            else:
                ap = dp.getActivePlugins(self.hostname)
                for plugin in ap:
                    args['projects'] = ap[plugin]
                    plugin.connectionMade(**args)

            for l in self.buffer:
                if l.type != l.Type_HOSTNAME:
                    self.stringReceived(l)
            self.buffer[:] = []

        elif m.type == m.Type_UPTIME:
            if self.hostname != None:
                try:
                    args = {'hostname': str(self.hostname),
                            'hostUptime': m.uptime.systemStartup,
                            'gyridUptime': m.uptime.gyridStartup}
                except:
                    return
                else:
                    ap = dp.getActivePlugins(self.hostname)
                    for plugin in ap:
                        args['projects'] = ap[plugin]
                        plugin.uptime(**args)
            else:
                self.buffer.append(m)

        elif m.type == m.Type_STATE_GYRID:
            if self.hostname != None:
                mp = {m.stateGyrid.Type_CONNECTED: 'connected',
                      m.stateGyrid.Type_DISCONNECTED: 'disconnected'}
                try:
                    args = {'hostname': str(self.hostname),
                            'module': 'gyrid',
                            'info': mp[m.stateGyrid.type]}
                except:
                    return
                else:
                    ap = dp.getActivePlugins(self.hostname)
                    for plugin in ap:
                        args['projects'] = ap[plugin]
                        plugin.sysStateFeed(**args)
            else:
                self.buffer.append(m)

        elif m.type == m.Type_KEEPALIVE:
            self.last_keepalive = int(time.time())

        elif m.type == m.Type_REQUEST_KEEPALIVE and m.success:
            l = task.LoopingCall(self.keepalive)
            l.start(self.factory.timeout, now=False)

        elif m.type == m.Type_REQUEST_STARTDATA and m.success:
            msg = proto.Msg()
            msg.type = msg.Type_REQUEST_CACHING
            msg.requestCaching.pushCache = True
            self.sendMsg(msg)

        elif not m.success:
            mr = proto.Msg()
            mr.type = mr.Type_ACK
            mr.ack.crc32 = binascii.a2b_hex(self.checksum(m.SerializeToString()))
            self.sendMsg(mr)

            if m.type == m.Type_BLUETOOTH_STATE_INQUIRY:
                if self.hostname != None:
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': m.bluetooth_stateInquiry.timestamp,
                                'sensorMac': binascii.b2a_hex(m.bluetooth_stateInquiry.sensorMac),
                                'info': 'new_inquiry',
                                'cache': m.cached}
                    except:
                        return
                    else:
                        ap = dp.getActivePlugins(self.hostname, timestamp=args['timestamp'])
                        for plugin in ap:
                            args['projects'] = ap[plugin]
                            plugin.stateFeed(**args)
                else:
                    self.buffer.append(m)

            elif m.type == m.Type_STATE_SCANNING:
                if self.hostname != None:
                    mp = {m.stateScanning.Type_STARTED: 'started_scanning',
                          m.stateScanning.Type_STOPPED: 'stopped_scanning'}
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': m.stateScanning.timestamp,
                                'sensorMac': binascii.b2a_hex(m.stateScanning.sensorMac),
                                'info': mp[m.stateScanning.type],
                                'cache': m.cached}
                    except:
                        return
                    else:
                        ap = dp.getActivePlugins(self.hostname, timestamp=args['timestamp'])
                        for plugin in ap:
                            args['projects'] = ap[plugin]
                            plugin.stateFeed(**args)
                else:
                    self.buffer.append(m)

            elif m.type == m.Type_BLUETOOTH_DATAIO:
                d = m.bluetooth_dataIO
                mp = {d.Move_IN: 'in',
                      d.Move_OUT: 'out'}
                if self.hostname != None:
                    try:
                        mac = binascii.b2a_hex(d.hwid)
                        dc = d.deviceclass
                    except:
                        return
                    else:
                        self.factory.server.mac_dc[mac] = dc
                        try:
                            args = {'hostname': str(self.hostname),
                                    'timestamp': d.timestamp,
                                    'sensorMac': binascii.b2a_hex(d.sensorMac),
                                    'mac': mac,
                                    'deviceclass': dc,
                                    'move': mp[d.move],
                                    'cache': m.cached}
                        except:
                            return
                        else:
                            ap = dp.getActivePlugins(self.hostname, timestamp=args['timestamp'])
                            for plugin in ap:
                                args['projects'] = ap[plugin]
                                plugin.dataFeedCell(**args)
                else:
                    self.buffer.append(m)

            elif m.type == m.Type_BLUETOOTH_DATARAW:
                d = m.bluetooth_dataRaw
                if self.hostname != None:
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': d.timestamp,
                                'sensorMac': binascii.b2a_hex(d.sensorMac),
                                'mac': binascii.b2a_hex(d.hwid),
                                'rssi': d.rssi,
                                'cache': m.cached}
                    except:
                        return
                    else:
                        ap = dp.getActivePlugins(self.hostname, timestamp=args['timestamp'])
                        for plugin in ap:
                            args['projects'] = ap[plugin]
                            plugin.dataFeedRssi(**args)
                else:
                    self.buffer.append(m)

            elif m.type == m.Type_INFO:
                if self.hostname != None:
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': d.info.timestamp,
                                'info': d.info.info,
                                'cache': m.cached}
                    except:
                        return
                    else:
                        ap = dp.getActivePlugins(self.hostname, timestamp=args['timestamp'])
                        for plugin in ap:
                            args['projects'] = ap[plugin]
                            plugin.infoFeed(**args)
                else:
                    self.buffer.append(m)


class GyridServerFactory(Factory):
    """
    The Gyrid server factory.
    """
    protocol = GyridServerProtocol

    def __init__(self, server):
        """
        Initialisation.

        @param   server (Olof)   Reference to main Olof server instance.
        """
        self.server = server
        self.client_dict = {}
        self.timeout = 60

class Olof(object):
    """
    Main Olof server class.
    """
    def __init__(self, paths):
        """
        Initialisation.

        Read the MAC-adress:deviceclass dictionary from disk, load the pluginmanager and the dataprovider.

        @param   paths (dict)   Dictionary setting the filepaths to use.
        """
        self.paths = paths
        self.logger = olof.logger.Logger(self, 'server')
        warnings.simplefilter("ignore", RuntimeWarning)

        self.debug_mode = False
        if len(sys.argv) > 1 and sys.argv[1] == 'debug':
            self.debug_mode = True

        self.logger.logInfo("Starting Gyrid Server")
        self.server_uptime = int(time.time())

        olof.datatypes.server = self

        self.configmgr = olof.configuration.Configuration(self, 'server')
        self.__defineConfiguration()

        self.pluginmgr = olof.pluginmanager.PluginManager(self)
        self.storagemgr = olof.storagemanager.StorageManager(self, 'server')
        self.dataprovider = olof.dataprovider.DataProvider(self)

        self.mac_dc = self.storagemgr.loadObject('mac_dc', {})
        self.port = self.configmgr.getValue('tcp_listening_port')

    def __defineConfiguration(self):
        """
        Define the configuration options for the server.
        """
        options = set()

        o = olof.configuration.Option('tcp_listening_port')
        o.setDescription('TCP port to listen on for incoming connections from the scanners.')
        o.setValidation(olof.tools.validation.parseInt)
        o.addValue(olof.configuration.OptionValue(2583, default=True))
        options.add(o)

        o = olof.configuration.Option('ssl_server_key')
        o.setDescription("Path to the server's SSL key. None to disable SSL.")
        o.addValue(olof.configuration.OptionValue('keys/server.key', default=True))
        options.add(o)

        o = olof.configuration.Option('ssl_server_crt')
        o.setDescription("Path to the server's SSL certificate. None to disable SSL.")
        o.addValue(olof.configuration.OptionValue('keys/server.crt', default=True))
        options.add(o)

        o = olof.configuration.Option('ssl_server_ca')
        o.setDescription("Path to the server's SSL CA. None to disable SSL.")
        o.addValue(olof.configuration.OptionValue('keys/ca.pem', default=True))
        options.add(o)

        self.configmgr.addOptions(options)
        self.configmgr.readConfig()

    def unload(self):
        """
        Unload the dataprovider and the pluginmanager. Save the MAC-address:deviceclass dictionary to disk.
        """
        self.dataprovider.unload()
        self.configmgr.unload()
        self.pluginmgr.unload(shutdown=True)
        self.storagemgr.storeObject(self.mac_dc, 'mac_dc')
        self.logger.logInfo("Stopping Gyrid Server")

    def getDeviceclass(self, mac):
        """
        Get the deviceclass that corresponds with the given MAC-address.

        @param   mac (str)   The MAC-address to check.
        @return  (int)       The deviceclass of the device with given MAC-address, -1 if unknown.
        """
        return self.mac_dc.get(mac, -1)

    def checkDiskAccess(self, paths):
        """
        Check read/write access to all given paths. Prints errors when read/write access is
        forbidden, and returns True only when all paths have read/write access.

        @param    paths (list)   A list of paths to check.
        @return   (bool)         Whether all paths are accessible.
        """
        def hardExit(path):
            """
            Write error directly to standarderror and exit immediately without unloading.
            Used when the logfiles or -directory itself is not writeable.
            """
            sys.stderr.write(time.strftime('%Y%m%d-%H%M%S-%Z ') + 'Gyrid Server: ' + \
                "Error: Needs write access to '%s'.\n" % path)
            sys.exit(1)

        access = True

        if type(paths) is str or type(paths) is unicode:
            paths = [paths]

        for path in paths:
            if os.path.dirname(path) and not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            elif (os.path.exists(path)) and (os.access(path, os.W_OK) == False):
                if 'logger' not in self.__dict__:
                    hardExit(path)
                self.logger.logError("Needs write access to '%s'" % path)
                access = False
            elif (not os.path.exists(path)) and (os.access(os.path.dirname(path), os.W_OK) == False):
                if 'logger' not in self.__dict__:
                    hardExit(path)
                self.logger.logError("Needs write access to '%s'" % path)
                access = False

        return access

    def run(self):
        """
        Start up the server reactor.
        """
        reactor.addSystemEventTrigger("before", "shutdown", self.unload)
        gsf = GyridServerFactory(self)

        ssl_server_key = self.configmgr.getValue('ssl_server_key')
        ssl_server_crt = self.configmgr.getValue('ssl_server_crt')
        ssl_server_ca = self.configmgr.getValue('ssl_server_ca')

        listen = False
        if ssl_server_key == ssl_server_crt == ssl_server_ca == None:
            # Disable SSL
            reactor.listenTCP(self.port, gsf)
            self.logger.logInfo("Listening on TCP port %s" % self.port)
            listen = True
        else:
            # Enable SSL
            if False in [os.path.isfile(i) for i in [ssl_server_key, ssl_server_crt, ssl_server_ca]]:
                self.logger.logError("SSL credentials missing")
            else:
                from OpenSSL import SSL
                from twisted.internet import ssl
                gyridCtxFactory = ssl.DefaultOpenSSLContextFactory(ssl_server_key, ssl_server_crt)
                ctx = gyridCtxFactory.getContext()
                ctx.set_verify(SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT, verifyCallback)

                # Since we have self-signed certs we have to explicitly
                # tell the server to trust them.
                ctx.load_verify_locations(self.configmgr.getValue('ssl_server_ca'))

                reactor.listenSSL(self.port, gsf, gyridCtxFactory)
                self.logger.logInfo("Listening on TCP port %s, with SSL enabled" % self.port)
                listen = True

        if listen:
            reactor.run()
        else:
            self.unload()
            sys.exit(1)
