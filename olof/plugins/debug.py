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
    def __init__(self, server):
        """
        Initialisation.
        """
        olof.core.Plugin.__init__(self, server)

    def connectionMade(self, hostname, ip, port):
        """
        Print connection details to terminal.
        """
        self.output("Connection made with %s (%s:%s)" % (hostname, ip, port))

    def connectionLost(self, hostname, ip, port):
        """
        Print connection details to terminal.
        """
        self.output("Connection lost with %s (%s:%s)" % (hostname, ip, port))
