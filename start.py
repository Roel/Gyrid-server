#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

from olof import server

PATHS_LOCAL = {
    'config' : 'config',
    'logs' : 'logs',
    'plugins' : 'olof/plugins',
    'storage' : 'storage'
}

PATHS_SYSTEM = {
    'config' : '/etc/gyrid-server',
    'logs' : '/var/log/gyrid-server',
    'plugins' : '/usr/share/gyrid-server/plugins',
    'storage' : '/var/tmp/gyrid-server'
}

if __name__ == '__main__':
    """
    Make the Olof object and start running.
    """
    s = server.Olof(PATHS_LOCAL)
    s.run()
