#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.internet import task

import time
import urllib2
import urlparse

import olof.core

class Plugin(olof.core.Plugin):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server, "Debug")

    def connectionMade(self, hostname, ip, port):
        self.output("Connection made with %s (%s:%s)" % (hostname, ip, port))

    def connectionLost(self, hostname, ip, port):
        self.output("Connection lost with %s (%s:%s)" % (hostname, ip, port))

    def infoFeed(self, hostname, timestamp, info):
        self.output("%s info: %s" % (hostname, info))

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        if info == 'new_inquiry':
            self.output("%s - %s: %s" % (hostname, sensor_mac, info))

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        #self.output("%s - %s: %s moved %s" % (hostname, sensor_mac, mac, move))
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        #print "%s detected with %s" % (mac, rssi)
        #self.output("%s - %s: %s detected with %s" % (hostname, sensor_mac, mac,
            #rssi))
        pass
