#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin to print debug and information to the terminal.
"""

from threading import Lock
from twisted.internet import task

import olof.core

ENABLED = False

class Plugin(olof.core.Plugin):
    def __init__(self, server, filename):
        """
        Initialisation.
        """
        olof.core.Plugin.__init__(self, server, filename)
        self.logfile = '/srv/files/tmp/ip-addresses.txt'
        self.lock = Lock()
        self.mapping = {}
        self.shouldWrite = False
        self.loop = task.LoopingCall(self.writeLog)
        self.loop.start(5)

        self.enabledHosts = ['gyrid-303']

    def unload(self, shutdown=False):
        try:
            self.loop.stop()
        except AssertionError:
            pass

    def connectionMade(self, hostname, projects, ip, port):
        if hostname in self.enabledHosts:
            self.lock.acquire()
            self.mapping[hostname] = ip
            self.shouldWrite = True
            self.lock.release()

    def connectionLost(self, hostname, projects, ip, port):
        if hostname in self.enabledHosts:
            self.lock.acquire()
            if hostname in self.mapping:
                del(self.mapping[hostname])
                self.shouldWrite = True
            self.lock.release()

    def writeLog(self):
        if self.shouldWrite:
            self.lock.acquire(False)
            f = open(self.logfile, 'w')
            f.write('\n'.join(['%s,%s' % (i, self.mapping[i]) for i in self.mapping]))
            f.write('\n')
            f.close()
            self.shouldWrite = False
            self.lock.release()
