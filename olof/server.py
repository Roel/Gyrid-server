#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

from OpenSSL import SSL

from twisted.internet import reactor, ssl, task, threads
from twisted.internet.protocol import Factory
from twisted.protocols.basic import LineReceiver

import imp
import os
import sys
import time
import traceback
import zlib

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
            for p in self.factory.server.plugins:
                p.connectionLost(self.hostname, self.transport.getPeer().host,
                    self.transport.getPeer().port)

    def checksum(self, data):
        return hex(abs(zlib.crc32(data)))[2:]

    def lineReceived(self, line):
        #reactor.callInThread(self.process, line)
        #print line
        self.process(line)

    def process(self, line):
        ll = line.strip().split(',')

        if ll[0] == 'MSG':
            ll[1] = ll[1].strip()
            if ll[1] == 'hostname':
                self.hostname = ll[2]
                for p in self.factory.server.plugins:
                    p.connectionMade(self.hostname,
                        self.transport.getPeer().host,
                        self.transport.getPeer().port)
            elif ll[1] == 'uptime':
                for p in self.factory.server.plugins:
                    p.uptime(self.hostname, ll[3], ll[2])
            elif ll[1] == 'gyrid':
                for p in self.factory.server.plugins:
                    p.sysStateFeed(self.hostname, ll[1], ll[2])
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
                    for p in self.factory.server.plugins:
                        p.stateFeed(self.hostname, ll[2], ll[1], ll[3])
                elif len(ll) == 5:
                    for p in self.factory.server.plugins:
                        p.dataFeedCell(self.hostname, ll[1], ll[0], ll[2], ll[3],
                            ll[4])
                elif len(ll) == 4:
                    for p in self.factory.server.plugins:
                        p.dataFeedRssi(self.hostname, ll[1], ll[0], ll[2], ll[3])
                elif len(ll) == 3 and ll[0] == 'INFO':
                    for p in self.factory.server.plugins:
                        p.infoFeed(self.hostname, ll[1], ll[2])


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

        self.load_plugins()

    def load_plugins(self):
        def load(filename, list):
            name = os.path.basename(filename)[:-3]
            try:
                plugin = imp.load_source(name, filename).Plugin(self)
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

    def output(self, message):
        d = {'time': time.strftime('%Y%m%d-%H%M%S-%Z'),
             'message': message}
        sys.stdout.write("%(time)s Gyrid Server: %(message)s.\n" % d)

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

        reactor.listenSSL(self.port, gsf, gyridCtxFactory)
        reactor.run()
