#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

class Plugin(object):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server, name):
        self.server = server
        self.name = name
        self.output = self.server.output

    def unload(self):
        pass

    def uptime(self, hostname, host_uptime, gyrid_uptime):
        pass

    def connectionMade(self, hostname, ip, port):
        pass

    def connectionLost(self, hostname, ip, port):
        pass

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        pass

    def sysStateFeed(self, hostname, module, info):
        pass

    def infoFeed(self, hostname, timestamp, info):
        pass

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        pass
