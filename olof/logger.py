#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

import logging, logging.handlers
import os
import sys
import time

class Logger(object):
    def __init__(self, server, location):
        self.server = server
        self.base_path = 'olof/logs'
        self.location = os.path.join(self.base_path, location)

        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        self.logger = self.__getLogger()

    def __getLogger(self):
        logger = logging.getLogger(self.location)
        handler = logging.handlers.RotatingFileHandler(self.location, maxBytes=524288, backupCount=4)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

    def logInfo(self, message):
        t = time.strftime('%Y%m%d-%H%M%S-%Z')
        m = message.strip()

        if self.server.debug_mode:
            sys.stdout.write("%s Gyrid Server: %s.\n" % (t, m))
        self.logger.info("I %s: %s." % (t, m))

    def logError(self, message):
        t = time.strftime('%Y%m%d-%H%M%S-%Z')
        m = message.strip()

        if self.server.debug_mode:
            sys.stderr.write("%s Gyrid Server: %s.\n" % (t, m))
        self.logger.info("E %s: %s." % (t, m))
