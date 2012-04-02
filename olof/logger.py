#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module providing logging infrastructure for info and error messages from the server.
"""

import logging, logging.handlers
import os
import sys
import time

class Logger(object):
    """
    Main Logger class that handles logging of information.
    """
    def __init__(self, server, filename):
        """
        Initialisation.

        @param   server (Olof)    Reference to main Olof server instance.
        @param   filename (str)   Filename of the logfile. Log resides in logs/filename.
        """
        self.server = server
        self.filename = filename
        self.base_path = 'logs'
        self.location = os.path.join(self.base_path, self.filename)

        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

        self.logger = None

    def __getLogger(self):
        """
        Get the logging.Logger object for this logger. Uses a RotatingFileHandler to automatically rotate the log when
        filesize exceeds 512 kB. Four backups are stored.
        """
        logger = logging.getLogger(self.location)
        handler = logging.handlers.RotatingFileHandler(self.location, maxBytes=524288, backupCount=4)
        handler.setFormatter(logging.Formatter("%(message)s"))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        return logger

    def __procMsg(self, message):
        """
        Process the given message, creating a logger when none available.

        @param    message (str)   The message to process
        @return   (str, str)      The timestamp this message was processed. The message itself.
        """
        if self.logger == None:
            self.logger = self.__getLogger()
        return time.strftime('%Y%m%d-%H%M%S-%Z'), message.strip()

    def logInfo(self, message):
        """
        Log the given message as information. When running in debug mode, print to stdout too.

        @param   message (str)   The message to log.
        """
        t, m = self.__procMsg(message)
        if self.server.debug_mode:
            f = ' (%s)' % self.filename if self.filename != 'server' else ''
            sys.stdout.write("%s Gyrid Server%s: %s.\n" % (t, f, m))
        self.logger.info("I %s: %s." % (t, m))

    def logError(self, message):
        """
        Log the given message as error. When running in debug mode, print to stderr too.

        @param   message (str)   The message to log.
        """
        t, m = self.__procMsg(message)
        if self.server.debug_mode:
            f = ' (%s)' % self.filename if self.filename != 'server' else ''
            sys.stderr.write("%s Gyrid Server%s: Error: %s.\n" % (t, f, m))
        self.logger.info("E %s: %s." % (t, m))
