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
    if not ok:
        print 'invalid cert from subject:', x509.get_subject()
        return False
    else:
        #Certs are fine
        pass
    return True

class GyridServerProtocol(LineReceiver):
    def connectionMade(self):
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
        t = self.factory.timeout
        if self.last_keepalive < (int(time.time())-(t+0.1*t)):
            #self.transport._writeDisconnected = True
            self.transport.loseConnection()
        else:
            self.sendLine('MSG,keepalive')

    def sendLine(self, data):
        LineReceiver.sendLine(self, data)

    def connectionLost(self, reason):
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
        return hex(abs(zlib.crc32(data)))[2:]

    def lineReceived(self, line):
        #reactor.callInThread(self.process, line)
        #print line
        self.process(line)

    def process(self, line):
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
    protocol = GyridServerProtocol

    def __init__(self, server):
        self.server = server
        self.client_dict = {}
        self.timeout = 60

class Olof(object):
    def __init__(self):
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

        self.load_plugins()

        self.dataprovider = olof.dataprovider.DataProvider(self)

    def load_plugins(self):
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

    def unload_plugins(self):
        self.dataprovider.unload()

        f = open('olof/data/mac_dc.pickle', 'wb')
        pickle.dump(self.mac_dc, f)
        f.close()

        for p in self.plugins:
            p.unload()

    def getDeviceclass(self, mac):
        return self.mac_dc.get(mac, -1)

    def check_disk_access(self, locations):
        access = True

        for file in locations:
            if not os.path.exists(os.path.dirname(file)):
                os.makedirs(os.path.dirname(file))
            elif (os.path.exists(file)) and (os.access(file, os.W_OK) == False):
                self.output("Error: Needs write access to %s" \
                    % file, sys.stderr)
                access = False
            elif (not os.path.exists(file)) and (os.access(os.path.dirname(
                file), os.W_OK) == False):
                self.output("Error: Needs write access to %s" \
                    % file, sys.stderr)
                access = False

        if not access:
            sys.exit(1)

    def output(self, message, channel=sys.stdout):
        d = {'time': time.strftime('%Y%m%d-%H%M%S-%Z'),
             'message': message}
        channel.write("%(time)s Gyrid Server: %(message)s.\n" % d)

    def run(self):
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

        reactor.addSystemEventTrigger("before", "shutdown", self.unload_plugins)
        reactor.listenSSL(self.port, gsf, gyridCtxFactory)
        reactor.run()
