#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

from OpenSSL import SSL

from twisted.internet import reactor, ssl, task, threads
from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver

import git
import imp
import os
import sys
import time
import traceback
import zlib

import cPickle as pickle

import olof.dataprovider
import olof.datatypes

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

class GyridServerProtocol(LineReceiver):
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

        self.sendLine('MSG,hostname')
        self.sendLine('MSG,enable_sensor_mac,true')
        self.sendLine('MSG,enable_rssi,true')
        self.sendLine('MSG,enable_cache,true')
        self.sendLine('MSG,enable_uptime,true')
        self.sendLine('MSG,enable_state_scanning,true')
        self.sendLine('MSG,enable_state_inquiry,true')

        self.sendLine('MSG,enable_keepalive,%i' % self.factory.timeout)
        self.sendLine('MSG,keepalive')

    def keepalive(self):
        """
        Keepalive method. Close the connection when the last keepalive was longer ago than the timeout value, reply with
        a keepalive otherwise.
        """
        t = self.factory.timeout
        if self.last_keepalive < (int(time.time())-(t+0.1*t)):
            self.transport.loseConnection()
        else:
            self.sendLine('MSG,keepalive')

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
                for p in self.factory.server.plugins:
                    if dp.isActive(self.hostname, p.filename):
                        p.connectionLost(**args)

    def checksum(self, data):
        """
        Calculate the CRC32 checksum of the given data.

        @param   data (str)   The data to check.
        @return  (hex)        The absolute (positive) hexadecimal CRC32 checksum of the data.
        """
        return hex(abs(zlib.crc32(data)))[2:]

    def lineReceived(self, line):
        """
        Called when a line was received. Process the line.
        """
        self.process(line)

    def process(self, line):
        """
        Process the line. The magic happens here!

        Depending on the type of information received, the corresponding method is called for all plugins with the
        correct arguments based on the received data.

        @param   line (str)   The line to process.
        """
        ll = line.strip().split(',')
        dp = self.factory.server.dataprovider

        if ll[0] == 'MSG':
            ll[1] = ll[1].strip()
            if ll[1] == 'hostname':
                self.hostname = ll[2]
                try:
                    args = {'hostname': str(self.hostname),
                            'ip': str(self.transport.getPeer().host),
                            'port': int(self.transport.getPeer().port)}
                except:
                    return
                else:
                    for p in self.factory.server.plugins:
                        if dp.isActive(self.hostname, p.filename):
                            p.connectionMade(**args)

                for l in self.buffer:
                    if not 'hostname' in l:
                        self.process(l)
                self.buffer[:] = []
            elif ll[1] == 'uptime':
                if self.hostname != None:
                    try:
                        args = {'hostname': str(self.hostname),
                                'host_uptime': int(ll[3]),
                                'gyrid_uptime': int(ll[2])}
                    except:
                        return
                    else:
                        for p in self.factory.server.plugins:
                            if dp.isActive(self.hostname, p.filename):
                                p.uptime(**args)
                else:
                    self.buffer.append(line)
            elif ll[1] == 'gyrid':
                if self.hostname != None:
                    try:
                        args = {'hostname': str(self.hostname),
                                'module': str(ll[1]),
                                'info': str(ll[2])}
                    except:
                        return
                    else:
                        for p in self.factory.server.plugins:
                            if dp.isActive(self.hostname, p.filename):
                                p.sysStateFeed(**args)
                else:
                    self.buffer.append(line)
            elif len(ll) == 2 and ll[1] == 'keepalive':
                self.last_keepalive = int(time.time())
            elif len(ll) == 3 and ll[1] == 'enable_keepalive':
                l = task.LoopingCall(self.keepalive)
                l.start(self.factory.timeout, now=False)
                self.sendLine('MSG,cache,push')
        else:
            self.sendLine('ACK,%s' % self.checksum(line))

            if self.hostname != None:
                if len(ll) == 4 and ll[0] == 'STATE':
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': float(ll[2]),
                                'sensor_mac': str(ll[1]),
                                'info': str(ll[3])}
                    except:
                        return
                    else:
                        for p in self.factory.server.plugins:
                            if dp.isActive(self.hostname, p.filename, args['timestamp']):
                                p.stateFeed(**args)
                elif len(ll) == 5:
                    try:
                        mac = str(ll[2])
                        dc = int(ll[3])
                    except:
                        return
                    else:
                        self.factory.server.mac_dc[mac] = dc
                        try:
                            args = {'hostname': str(self.hostname),
                                    'timestamp': float(ll[1]),
                                    'sensor_mac': str(ll[0]),
                                    'mac': mac,
                                    'deviceclass': dc,
                                    'move': str(ll[4])}
                        except:
                            return
                        else:
                            for p in self.factory.server.plugins:
                                if dp.isActive(self.hostname, p.filename, args['timestamp']):
                                    p.dataFeedCell(**args)
                elif len(ll) == 4:
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': float(ll[1]),
                                'sensor_mac': str(ll[0]),
                                'mac': str(ll[2]),
                                'rssi': int(ll[3])}
                    except:
                        return
                    else:
                        for p in self.factory.server.plugins:
                            if dp.isActive(self.hostname, p.filename, args['timestamp']):
                                p.dataFeedRssi(**args)
                elif len(ll) == 3 and ll[0] == 'INFO':
                    try:
                        args = {'hostname': str(self.hostname),
                                'timestamp': float(ll[1]),
                                'info': str(ll[2])}
                    except:
                        return
                    else:
                        for p in self.factory.server.plugins:
                            if dp.isActive(self.hostname, p.filename, args['timestamp']):
                                p.infoFeed(**args)


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
    def __init__(self):
        """
        Initialisation.

        Read the MAC-adress:deviceclass dictionary from disk, load the plugins and the dataprovider.
        """
        self.port = 2583

        self.plugins = []
        self.plugins_inactive = []
        self.plugins_with_errors = {}

        self.output("Starting Gyrid Server")
        repo = git.Repo('.')
        commit = repo.commits(repo.active_branch)[0]
        self.git_commit = commit.id
        self.git_date = int(time.strftime('%s', commit.committed_date))

        self.mac_dc = {}
        if os.path.isfile('olof/data/mac_dc.pickle'):
            f = open('olof/data/mac_dc.pickle', 'rb')
            try:
                self.mac_dc = pickle.load(f)
            except:
                self.mac_dc = {}
            f.close()

        olof.datatypes.server = self

        self.loadPlugins()

        self.dataprovider = olof.dataprovider.DataProvider(self)

    def loadPlugins(self):
        """
        Load the plugins. Called automatically on initialisation.
        """
        def load(filename, list):
            name = os.path.basename(filename)[:-3]
            try:
                plugin = imp.load_source(name, filename).Plugin(self)
                plugin.filename = name
            except Exception, e:
                self.plugins_with_errors[name] = (e, traceback.format_exc())
                sys.stderr.write("Error while loading plugin %s: %s\n" % (name, e))
                traceback.print_exc()
            else:
                self.output("Loaded plugin: %s" % name)
                list.append(plugin)

        home = os.getcwd()

        filenames = []
        for filename in os.listdir(os.path.join(home, 'olof', 'plugins')):
            if filename.endswith('.py') and not filename.startswith('_'):
                load(os.path.join(home, 'olof', 'plugins', filename), self.plugins)
            elif filename.endswith('.py') and not filename.startswith('__'):
                load(os.path.join(home, 'olof', 'plugins', filename), self.plugins_inactive)

    def unloadPlugins(self):
        """
        Unload the dataprovider and all the plugins. Save the MAC-address:deviceclass dictionary to disk.
        """
        self.dataprovider.unload()

        f = open('olof/data/mac_dc.pickle', 'wb')
        pickle.dump(self.mac_dc, f)
        f.close()

        for p in self.plugins:
            p.unload()

    def getDeviceclass(self, mac):
        """
        Get the deviceclass that corresponds with the given MAC-address.

        @param   mac (str)   The MAC-address to check.
        @return  (int)       The deviceclass of the device with given MAC-address.
        """
        return self.mac_dc.get(mac, -1)

    def checkDiskAccess(self, paths):
        """
        Check read/write access to all given paths. Prints errors when read/write access is forbidden, and exits
        with an exit code of 1 when not all paths have read/write access.

        @param    paths (list)   A list of paths to check.
        """
        access = True

        for path in paths:
            if not os.path.exists(os.path.dirname(path)):
                os.makedirs(os.path.dirname(path))
            elif (os.path.exists(path)) and (os.access(path, os.W_OK) == False):
                self.output("Error: Needs write access to %s" \
                    % path, sys.stderr)
                access = False
            elif (not os.path.exists(path)) and (os.access(os.path.dirname(
                path), os.W_OK) == False):
                self.output("Error: Needs write access to %s" \
                    % path, sys.stderr)
                access = False

        if not access:
            sys.exit(1)

    def output(self, message, channel=sys.stdout):
        """
        Write a message to the terminal output.

        @param   message (str)   The message to write, without trailing punctuation or line-endings.
        @param   channel         The channel to write the message to, by default sys.stdout
        """
        d = {'time': time.strftime('%Y%m%d-%H%M%S-%Z'),
             'message': message}
        channel.write("%(time)s Gyrid Server: %(message)s.\n" % d)

    def run(self):
        """
        Start up the server reactor.
        """
        self.output("Listening on TCP port %s" % self.port)

        gyridCtxFactory = ssl.DefaultOpenSSLContextFactory(
            'keys/server.key', 'keys/server.crt')

        ctx = gyridCtxFactory.getContext()

        ctx.set_verify(
            SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT,
            verifyCallback)

        # Since we have self-signed certs we have to explicitly
        # tell the server to trust them.
        ctx.load_verify_locations("keys/ca.pem")

        gsf = GyridServerFactory(self)

        reactor.addSystemEventTrigger("before", "shutdown", self.unloadPlugins)
        reactor.listenSSL(self.port, gsf, gyridCtxFactory)
        reactor.run()
