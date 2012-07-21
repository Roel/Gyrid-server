#!/usr/bin/python
#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

from olof import server

if __name__ == '__main__':
    """
    Make the Olof object and start running.
    """
    s = server.Olof()
    s.run()
