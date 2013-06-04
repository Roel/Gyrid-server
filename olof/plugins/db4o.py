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

from twisted.internet import reactor, ssl
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import Int16StringReceiver

import os
import struct
import time

import olof.configuration
import olof.core
import olof.protocol.network as proto
import olof.storagemanager

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

    def connectionMade(self):
        """
        Push through the cache.
        """
        self.plugin.connected = True
        self.plugin.conn_time = int(time.time())
        self.pushCache()

    def connectionLost(self, reason):
        """
        Open the cache.
        """
        self.plugin.connected = False
        self.plugin.conn_time = int(time.time())
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()
        self.plugin.cache = open(self.plugin.cache_file, 'a')

    def sendMsg(self, msg):
        """
        Try to send the line to the Db4O server. When not connected, cache the line.
        """
        if self.transport != None and self.plugin.connected:
            Int16StringReceiver.sendString(self, msg.SerializeToString())
        elif not self.plugin.connected and not self.plugin.cache.closed:
            self.plugin.cache.write(struct.pack('!H', msg.ByteSize()) + \
                msg.SerializeToString())
            self.plugin.cache.flush()
            self.plugin.cached_lines += 1

    def stringReceived(self, line):
        """
        Called when a line of data is received.
        """
        pass

    def pushCache(self):
        """
        Push trough the cached data. Clears the cache afterwards.
        """
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        self.plugin.cache = open(self.plugin.cache_file, 'r')

        read = self.plugin.cache.read(2)
        while read:
            bts = struct.unpack('!H', read)[0]
            try:
                msg = proto.Msg.FromString(self.plugin.cache.read(bts))
            except:
                pass
            else:
                self.sendMsg(msg)
            try:
                read = self.plugin.cache.read(2)
            except IOError:
                read = False

            self.plugin.cached_lines -= 1
        self.plugin.cache.close()

        self.clearCache()

    def clearCache(self):
        """
        Clears the cache file.
        """
        if not self.plugin.cache.closed:
            self.plugin.cache.flush()
            self.plugin.cache.close()

        self.plugin.cache = open(self.plugin.cache_file, 'w')
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
        olof.core.Plugin.__init__(self, server, filename, "Db4o")
        self.host = self.config.getValue('host')
        self.port = self.config.getValue('port')
        self.cache_file = self.config.getValue('cache_file')
        self.cached_lines = 0
        if os.path.isfile(self.cache_file):
            self.cache = open(self.cache_file, 'r')
            for line in self.cache:
                self.cached_lines += 1
            self.cache.close()

        self.server.checkDiskAccess([self.cache_file])
        self.cache = open(self.cache_file, 'a')

        self.connected = False
        self.conn_time = None

        self.locations = self.storage.loadObject('locations', [])
        self.scanSetups = self.storage.loadObject('scanSetups', [])

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
        self.storage.storeObject(self.locations, 'locations')
        self.storage.storeObject(self.scanSetups, 'scanSetups')

    def getStatus(self):
        """
        Return the current status of the Db4O connection and cache. For use in the status plugin.
        """
        cl = {}
        if self.cached_lines > 0:
            cl = {'id': 'cached', 'int': self.cached_lines}

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
