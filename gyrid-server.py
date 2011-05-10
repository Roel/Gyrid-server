#!/usr/bin/python
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

import time
import zlib

def verifyCallback(connection, x509, errnum, errdepth, ok):
    if not ok:
        print 'invalid cert from subject:', x509.get_subject()
        return False
    else:
        #Certs are fine
        pass
    return True

class GyridServer(LineReceiver):
    def connectionMade(self):
        self.last_keepalive = -1
        self.ip = "%s:%s" % (self.transport.getPeer().host,
            self.transport.getPeer().port)

        print "Connection made with %s" % self.ip
        self.factory.connection_log.write(time.strftime('%H:%M:%S') + \
            ' - Connection made with %s\n' % self.ip)
        self.factory.connection_log.flush()

        self.sendLine('MSG,hostname')
        self.sendLine('MSG,enable_sensor_mac,true')
        self.sendLine('MSG,enable_rssi,true')
        self.sendLine('MSG,enable_cache,true')

        self.sendLine('MSG,enable_keepalive,%i' % self.factory.timeout)
        self.sendLine('MSG,keepalive')

        #l = task.LoopingCall(self.keepalive)
        #l.start(self.factory.timeout, now=False)

    def keepalive(self):
        t = self.factory.timeout
        if self.last_keepalive < (int(time.time())-(t+0.1*t)):
            #self.transport._writeDisconnected = True
            self.transport.loseConnection()
        else:
            self.sendLine('MSG,keepalive')

    def sendLine(self, data):
        if not data.startswith('ACK'):
            print time.strftime('%H:%M:%S') + " -> %s" % data
        LineReceiver.sendLine(self, data)

    def connectionLost(self, reason):
        print "Connection lost with %s" % self.ip
        self.factory.connection_log.write(time.strftime('%H:%M:%S') + \
            ' - Connection lost with %s\n' % self.ip)
        self.factory.connection_log.flush()

        try:        
            del(self.factory.client_dict[self.ip])
        except KeyError:
            pass

    def checksum(self, data):
        return hex(abs(zlib.crc32(data)))[2:]

    def lineReceived(self, line):
        #reactor.callInThread(self.process, line)
        self.process(line)

    def process(self, line):
        ll = line.strip().split(',')

        if ll[0] == 'MSG':
            if self.ip in self.factory.client_dict:
                print time.strftime('%H:%M:%S') + ' %s <- %s' % (
                    self.factory.client_dict[self.ip], line)
            else:
                print time.strftime('%H:%M:%S') + ' %s <- %s' % (self.ip, line)

            ll[1] = ll[1].strip()
            if ll[1] == 'hostname':
                self.factory.client_dict[self.ip] = ll[2]
            elif len(ll) == 2 and ll[1] == 'keepalive':
                self.last_keepalive = int(time.time())
            elif len(ll) == 3 and ll[1] == 'enable_keepalive':
                l = task.LoopingCall(self.keepalive)
                l.start(self.factory.timeout, now=False)
                self.sendLine('MSG,cache,push')
        else:
            self.sendLine('ACK,%s' % self.checksum(line))

            if ll[0] == 'INFO':
                self.factory.log(self.factory.mess_log, ll[1], ','.join(ll[2:]))
            elif len(ll) == 5:
                self.factory.log(self.factory.scan_log, ll[1], ','.join(ll[2:]))
            elif len(ll) == 4:
                self.factory.log(self.factory.rssi_log, ll[1], ','.join(ll[2:]))

class GyridServerFactory(Factory):
    protocol = GyridServer

    def __init__(self):
        self.client_dict = {}
        self.timeout = 60

        self.connection_log = open('logs/connections.log', 'a')
        self.mess_log = open('logs/messages.log', 'a')
        self.scan_log = open('logs/scan.log', 'a')
        self.rssi_log = open('logs/rssi.log', 'a')

    def log(self, log, timestamp, str):
        t = time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(float(timestamp)))
        log.write("%s,%s\n" % (t, str))
        log.flush()

gyridCtxFactory = ssl.DefaultOpenSSLContextFactory(
    'keys/server.key', 'keys/server.crt')

ctx = gyridCtxFactory.getContext()

ctx.set_verify(
    SSL.VERIFY_PEER | SSL.VERIFY_FAIL_IF_NO_PEER_CERT,
    verifyCallback)

# Since we have self-signed certs we have to explicitly
# tell the server to trust them.
ctx.load_verify_locations("keys/ca.pem")

gsf = GyridServerFactory()

reactor.listenSSL(2583, gsf, gyridCtxFactory)
reactor.run()
