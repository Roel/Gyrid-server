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
        olof.core.Plugin.__init__(self, server)

    def connectionMade(self, hostname, ip, port):
        self.output("Connection made with %s (%s:%s)" % (hostname, ip, port))

    def connectionLost(self, hostname, ip, port):
        self.output("Connection lost with %s (%s:%s)" % (hostname, ip, port))
