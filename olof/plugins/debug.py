#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin to print debug and information to the terminal.
"""

import olof.core

class Plugin(olof.core.Plugin):
    """
    Main Debug plugin class.
    """
    def __init__(self, server, filename):
        """
        Initialisation.
        """
        olof.core.Plugin.__init__(self, server, filename)

    def connectionMade(self, hostname, projects, ip, port):
        """
        Print connection details to terminal.
        """
        self.logger.logInfo("Connection made with %s (%s:%s)" % (hostname, ip, port))

    def connectionLost(self, hostname, projects, ip, port):
        """
        Print connection details to terminal.
        """
        self.logger.logInfo("Connection lost with %s (%s:%s)" % (hostname, ip, port))

    def locationUpdate(self, hostname, projects, module, obj):
        for pr in projects:
            print "locationUpdate for %s (project %s), %s" % (hostname, str(pr), module)
