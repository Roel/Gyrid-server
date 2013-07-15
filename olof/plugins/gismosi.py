#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin that handles the connection with the Db4O database.
"""

from OpenSSL import SSL

from twisted.internet import reactor, ssl, task
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import Int16StringReceiver

import os
import binascii
import struct
import threading
import time
import zlib

import olof.configuration
import olof.core
import olof.protocol.network as proto
import olof.storagemanager

class AckItem(object):
    """
    Class that defines an item in the AckMap.
    """

    # The maximum value of the timer after which the item is resent.
    max_misses = 5

    def __init__(self, msg, timer=0):
        """
        Initialisation.

        @param   msg      The msg to store.
        @param   timer    The initial value of the timer. An item is resent
                             when this value is negative or exceeds
                             AckItem.max_misses.
        """
        self.ackmap = None
        self.msg = msg
        self.timer = timer
        self.checksum = AckMap.checksum(msg.SerializeToString())

    def __eq__(self, item):
        return (item.msg == self.msg and
                item.checksum == self.checksum)

    def __hash__(self):
        return int(self.checksum, 16)

    def incrementTimer(self):
        """
        Increment the timer by a value of 1.
        """
        if self.timer >= 0:
            self.timer += 1

    def checkResend(self):
        """
        Check if the data should be resent, and do so when required.
        """
        if self.ackmap != None:
            if self.timer > 10 * AckItem.max_misses:
                # Protection against cache overflow when a line repeatedly fails to be ack'ed.
                self.ackmap.clearItem(self.checksum)

            elif self.timer < 0 or (self.timer % AckItem.max_misses == 0):
                self.msg.cached = True
                self.checksum = AckMap.checksum(self.msg.SerializeToString())
                client = self.ackmap.factory.client
                if client != None:
                    client.sendMsg(self.msg, await_ack=False)

class AckMap(object):
    """
    Class that stores the temporary cache, waiting for ack'ing by the server.
    """
    @staticmethod
    def checksum(data):
        """
        Calculate the CRC32 checksum for the given data string.

        @param   data   The data to process.
        @return         The CRC32 checksum.
        """
        return '%08x' % abs(zlib.crc32(data))

    def __init__(self, factory):
        """
        Initialisation. Start the checker loop which checks old cached lines
        and resends when necessary.

        @param   factory   Refence to InetClientFactory instance.
        """
        self.factory = factory
        self.ackmap = set()
        self.toAdd = set()
        self.toClear = set()
        self.lock = threading.Lock()

        self.check_loop = task.LoopingCall(self.__check)

    def restartChecker(self):
        """
        Start or restart the checker loop based on the current keepalive interval.
        """
        self.stopChecker()
        self.startChecker()

    def startChecker(self):
        """
        Start the checker loop.
        """
        interval = self.factory.config['enable_keepalive']
        self.interval = interval if interval > 0 else 60

        try:
            self.check_loop.start(self.interval, now=False)
        except AssertionError:
            pass

    def stopChecker(self):
        """
        Stop the checker loop.
        """
        try:
            self.check_loop.stop()
        except AssertionError:
            pass

    def addItem(self, ackItem):
        """
        Add an item to the map.
        """
        self.factory.plugin.cached_msgs += 1
        ackItem.ackmap = self
        if not self.lock.acquire(False):
            self.toAdd.add(ackItem)
        else:
            try:
                if len(self.toAdd) > 0:
                    #print "adding extra items to ackmap"
                    self.ackmap.update(self.toAdd)
                    self.toAdd.clear()
                #print "added item %s" % ackItem.checksum
                self.ackmap.add(ackItem)
            finally:
                self.lock.release()

        #print "ackmap size is now %i" % len(self.ackmap)

    def clearItem(self, checksum):
        """
        Clear the item with the given checksum from the cache, i.e. when it
        has been ack'ed by the server.

        @param   checksum   The checksum to check.
        """
        #print "trying to clear item %s" % checksum
        if not self.lock.acquire(False):
            self.toClear.add(checksum)
        else:
            try:
                item = None
                if len(self.toClear) > 0:
                    toClear = set()
                    for i in self.ackmap:
                        if i.checksum == checksum or \
                           i.checksum in self.toClear:
                           toClear.add(i)
                    self.factory.plugin.cached_msgs -= len(toClear)
                    #print "clearing extra items"
                    self.ackmap.difference_update(toClear)
                    self.toClear.clear()
                else:
                    for i in self.ackmap:
                        if i.checksum == checksum:
                            item = i
                            break

                    if item != None:
                        self.factory.plugin.cached_msgs -= 1
                        self.ackmap.difference_update([item])
                        #print "cleared item %s" % item.checksum
            finally:
                self.lock.release()

        #print "ackmap size is now %i" % len(self.ackmap)

    def clear(self):
        """
        Clear the entire map.
        """
        # No locking here, caller should use locking.
        #print "clearing ackmap"
        self.ackmap.clear()
        #print "ackmap size is now %i" % len(self.ackmap)

    def __check(self):
        """
        Called automatically by the checker loop; should not be called
        directly. Checks each item in the map and resends when necessary.
        """
        self.lock.acquire()
        try:
            for v in self.ackmap:
                v.incrementTimer()
                v.checkResend()
        finally:
            self.lock.release()

class Db4OClient(Int16StringReceiver):
    """
    The class handling the connection with the Db4O server.
    """
    def __init__(self, factory, plugin):
        """
        Initialisation.

        @param   factory (t.i.p.ClientFactory)   Reference to a Twisted ClientFactory.
        @param   plugin (olof.core.Plugin)       Reference to the main Db4O Plugin instance.
        """
        self.factory = factory
        self.plugin = plugin
        self.hostport = None
        self.cachedItemsAck = None

    def connectionMade(self):
        """
        Push through the cache.
        """
        self.plugin.connected = True
        self.plugin.conn_time = int(time.time())
        self.hostport = (self.transport.getPeer().host, self.transport.getPeer().port)
        self.plugin.logger.logInfo("Connected to %s:%i." % (self.hostport[0], self.hostport[1]))
        #for i in range(10):
        #    m = proto.Msg()
        #    m.type = m.Type_BLUETOOTH_DATARAW
        #    d = m.bluetooth_dataRaw
        #    d.timestamp = time.time() - 100 + i
        #    d.sensorMac = binascii.a2b_hex('001122334455')
        #    d.hwid = binascii.a2b_hex('aabbccddeeff')
        #    d.deviceclass = 120
        #    d.rssi = -80
        #    m.hostname = "helloworld"
        #    self.sendMsg(m)
        self.pushCache()

    def connectionLost(self, reason):
        """
        Open the cache.
        """
        self.plugin.connected = False
        self.plugin.conn_time = int(time.time())
        self.plugin.logger.logInfo("Disconnected from %s:%i." % (self.hostport[0], self.hostport[1]))
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()
        self.plugin.cache = open(self.plugin.cache_file, 'ab')
        self.factory.ackmap.lock.acquire()
        try:
            for i in self.factory.ackmap.ackmap:
                self.plugin.cache.write(
                    i.msg.SerializeToString() + \
                    struct.pack('!H', i.msg.ByteSize()))
                #print "written item %s to disk cache" % AckMap.checksum(i.msg.SerializeToString())
            self.factory.ackmap.clear()
        finally:
            self.factory.ackmap.lock.release()
        self.plugin.cache.flush()

    def sendMsg(self, msg):
        """
        Try to send the line to the Db4O server. When not connected, cache the line.
        """
        if self.transport != None and self.plugin.connected:
            self.factory.ackmap.addItem(AckItem(msg))
            Int16StringReceiver.sendString(self, msg.SerializeToString())
        elif not self.plugin.connected and not self.plugin.cache.closed:
            #print "written item %s to disk cache" % AckMap.checksum(msg.SerializeToString())
            self.plugin.cache.write(msg.SerializeToString() + struct.pack('!H', msg.ByteSize()))
            self.plugin.cache.flush()
            self.plugin.cached_msgs += 1

    def stringReceived(self, data):
        """
        Called when a line of data is received.
        """
        try:
            msg = proto.Msg.FromString(data)
        except:
            #print "Y U SEND THIS SH*T"
            return

        if msg.type == msg.Type_ACK:
            self.factory.ackmap.clearItem(binascii.b2a_hex(msg.ack))

            if self.cachedItemsAck:
                self.cachedItemsAck.discard(ack)
                if len(self.cachedItemsAck) <= 2:
                    self.readNextCachedItems(5000)

    def readNextCachedItems(self, amount=1):
        if self.plugin.cache.closed:
            self.cachedItemsAck = None
            #print "failed to read disk cache as file is closed"
            return

        for i in range(amount):
            #print "reading cached disk item"
            try:
                self.plugin.cache.seek(-2, 1)
                read = self.plugin.cache.read(2)
                bts = struct.unpack('!H', read)[0]
                self.plugin.cache.seek(-2-bts, 1)
                self.plugin.cached_msgs -= 1
            except:
                self.cachedItemsAck = None
                self.plugin.cache.truncate()
                self.plugin.cache.close()
                break

            rawmsg = self.plugin.cache.read(bts)
            self.plugin.cache.seek(-bts, 1)
            try:
                msg = proto.Msg.FromString(rawmsg)
                #print "read item %s from disk" % (AckMap.checksum(msg.SerializeToString()))
            except:
                pass
            else:
                msg.cached = True
                self.cachedItemsAck.add(AckMap.checksum(msg.SerializeToString()))
                self.sendMsg(msg)

        if not self.plugin.cache.closed:
            self.plugin.cache.truncate()

    def pushCache(self):
        """
        Push trough the cached data. Clears the cache afterwards.
        """
        #print "try pushing cache"
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        if os.path.isfile(self.plugin.cache_file):
            self.plugin.cache = open(self.plugin.cache_file, 'r+b')
            self.plugin.cache.seek(0, 2)

            self.cachedItemsAck = set()
            self.readNextCachedItems(5000)


    def clearCache(self):
        """
        Clears the cache file.
        """
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        self.plugin.cache = open(self.plugin.cache_file, 'wb')
        self.plugin.cache.truncate()
        self.plugin.cache.close()

class Db4OClientFactory(ReconnectingClientFactory):
    """
    The factory class of the Db4O client.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        @param   plugin (olof.core.Plugin)   Reference to the main Db4O Plugin instance.
        """
        self.plugin = plugin
        self.maxDelay = 120
        self.client = None
        self.ackmap = AckMap(self)
        self.buildProtocol(None)

    def sendMsg(self, msg):
        """
        Send a line via the Db4O client.

        @param   line (str)   The line to send.
        """
        if 'client' in self.__dict__ and self.client != None:
            self.client.sendMsg(msg)

    def buildProtocol(self, addr):
        """
        Build the Db4OClient protocol, return an Db4OClient instance.
        """
        self.resetDelay()
        self.client = Db4OClient(self, self.plugin)
        return self.client

class InetCtxFactory(ssl.ClientContextFactory):
    """
    The SSL context class of the inet client.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        @param   plugin (Plugin)   Reference to main Olof plugin instance.
        """
        self.plugin = plugin

    def getContext(self):
        """
        Return the SSL client context.
        """
        self.method = SSL.SSLv23_METHOD
        ctx = ssl.ClientContextFactory.getContext(self)
        ctx.use_certificate_file(self.plugin.config.getValue('ssl_client_crt'))
        ctx.use_privatekey_file(self.plugin.config.getValue('ssl_client_key'))
        return ctx

class Plugin(olof.core.Plugin):
    """
    Main Db4O plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation. Set up connection details and open cache file.
        Read saved location and scansetup data from disk.

        Connect to the Db4O server.
        """
        olof.core.Plugin.__init__(self, server, filename, "Gismosi")
        self.host = self.config.getValue('host')
        self.port = self.config.getValue('port')
        self.cache_file = self.config.getValue('cache_file')
        self.cache_lock = threading.Lock()

        self.server.checkDiskAccess([self.cache_file])
        self.cache = open(self.cache_file, 'ab')
        self.cached_msgs = 0

        self.connected = False
        self.conn_time = None

        self.db4o_factory = Db4OClientFactory(self)
        self.ssl_enabled = None not in [self.config.getValue('ssl_client_%s' % i) for i in ['crt', 'key']]
        if self.ssl_enabled:
            self.logger.logInfo('Connecting to Db4o server at %s:%i, with SSL enabled' % (self.host, self.port))
            reactor.connectSSL(self.host, self.port, self.db4o_factory, InetCtxFactory(self))
        else:
            self.logger.logInfo('Connecting to Db4o server at %s:%i' % (self.host, self.port))
            reactor.connectTCP(self.host, self.port, self.db4o_factory)

    def defineConfiguration(self):
        options = []

        o = olof.configuration.Option('host')
        o.setDescription('Hostname or IP-address of the Db4O database server.')
        o.addValue(olof.configuration.OptionValue('localhost', default=True))
        options.append(o)

        o = olof.configuration.Option('port')
        o.setDescription('TCP port to use on the database server.')
        o.setValidation(olof.tools.validation.parseInt)
        o.addValue(olof.configuration.OptionValue(5001, default=True))
        options.append(o)

        o = olof.configuration.Option('ssl_client_crt')
        o.setDescription('Path to the SSL client certificate. None to disable SSL.')
        o.addValue(olof.configuration.OptionValue(None, default=True))
        options.append(o)

        o = olof.configuration.Option('ssl_client_key')
        o.setDescription('Path to the SSL client key. None to disable SSL.')
        o.addValue(olof.configuration.OptionValue(None, default=True))
        options.append(o)

        o = olof.configuration.Option('cache_file')
        o.setDescription('Location of the file to use for caching data when the connection with the database ' + \
            'fails or is lost.')
        o.addValue(olof.configuration.OptionValue('/var/cache/gyrid-server/db4o.cache', default=True))
        options.append(o)

        return options

    def unload(self, shutdown=False):
        """
        Unload. Save locations and scansetups to disk.
        """
        olof.core.Plugin.unload(self, shutdown)

    def getStatus(self):
        """
        Return the current status of the Db4O connection and cache. For use in the status plugin.
        """
        cl = {}
        if self.cached_msgs > 0:
            cl = {'id': 'cached', 'int': self.cached_msgs}

        r = []
        if self.connected == False and self.conn_time == None:
            r = [{'status': 'error'}, {'id': 'no connection'}]
        elif self.connected == False:
            r = [{'status': 'error'},
                {'id': 'disconnected', 'time': self.conn_time}]
        elif self.connected == True:
            r = [{'status': 'ok'},
                {'id': 'connected', 'time': self.conn_time}]

        r.append({'id': 'host', 'str': self.host})
        r.append({'id': 'ssl', 'str': 'enabled' if self.ssl_enabled else 'disabled'})

        if len(cl) > 0:
            r.append(cl)
        return r

    def rawProtoFeed(self, m):
        self.db4o_factory.sendMsg(m)
