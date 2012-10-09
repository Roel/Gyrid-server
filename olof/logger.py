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
import traceback

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
        self.base_path = self.server.paths['logs']
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
        logger.setLevel(logging.INFO)

        if len(logger.handlers) < 1:
            handler = logging.handlers.RotatingFileHandler(self.location, maxBytes=524288, backupCount=4)
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)

        return logger

    def __procMsg(self, message):
        """
        Process the given message, creating a logger when none available.

        @param    message (str)   The message to process
        @return   (str, str)      The timestamp this message was processed. The message itself.
        """
        if self.logger == None:
            self.logger = self.__getLogger()

        message = message.strip() if message != None else ""
        return time.strftime('%Y%m%d-%H%M%S-%Z'), message

    def debug(self, message):
        """
        Write the given message to standard output as debug message.

        @param   message (str)   The message to log.
        """
        t, m = self.__procMsg(message)
        if self.server.debug_mode:
            f = ' (%s)' % self.filename if self.filename != 'server' else ''
            sys.stdout.write("%s Gyrid Server%s: %s.\n" % (t, f, m))

    def logInfo(self, message):
        """
        Log the given message as information. When running in debug mode, print to stdout too.

        @param   message (str)   The message to log.
        """
        t, m = self.__procMsg(message)
        if self.server.debug_mode:
            f = ' (%s)' % self.filename if self.filename != 'server' else ''
            sys.stdout.write("%s Gyrid Server%s: %s.\n" % (t, f, m))
        m = m.replace('\n', '\nI   ')
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
        m = m.replace('\n', '\nE   ')
        self.logger.info("E %s: %s." % (t, m))

    def logException(self, exception, message=None):
        """
        Log the given exception as error. When running in debug mode, print to stderr too.

        @param   exception (Exception)   The exception to log.
        @param   message (str)           A message to clarify the exception. Optional.
        """
        eType = sys.exc_info()[0].__name__
        eTraceback = traceback.format_exc()
        t, m = self.__procMsg(message)

        if self.server.debug_mode:
            f = ' (%s)' % self.filename if self.filename != 'server' else ''
            dbgStr = "\n%s Gyrid Server%s: Error: " % (t, f)
            if message != None:
                dbgStr += '%s. \n%s Gyrid Server%s:        ' % (message.strip(), t, f)
            dbgStr += '%s exception: %s.\n' % (eType, str(exception))
            sys.stderr.write(dbgStr)
            sys.stderr.write('   ' + '\n   '.join(eTraceback.rstrip().split('\n')) + '\n\n')

        m = m.replace('\n', '\nE   ')
        mLog = '%s. ' % m if m != '' else ''
        self.logger.info("E %s: %s%s exception: %s." % (t, mLog, eType, str(exception)))
        self.logger.info("E   %s" % eTraceback.rstrip().replace('\n', '\nE   '))
