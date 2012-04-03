#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles disk storage.
"""

import cPickle as pickle
import os

class StorageManager(object):
    """
    Class that manages saving and loading variables to and from disk.
    """
    def __init__(self, server, directoryName):
        """
        Initialisation.

        @param   server (Olof)         Reference to main Olof server instance.
        @param   directoryName (str)   Name of the storage subdirectory to save and load files.
        """
        self.server = server
        self.base_path = 'storage/%s/' % directoryName

    def __createDir(self):
        """
        Create the base directory if is does not exists already.
        """
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

    def saveVariable(self, variable, name):
        """
        Save the variable to disk.

        @param   variable     Variable to save.
        @param   name (str)   Unique name to identify this variable, later used to load the same variable from disk.
        """
        self.__createDir()
        f = open(self.base_path + name, 'wb')
        pickle.dump(variable, f)
        f.close()

    def loadVariable(self, name, default=None):
        """
        Load the variable from disk.

        @param   name (str)   Unique name of the variable to load.
        @param   default      A default value to return in case of an error or a non-existing variable.
        @return               The requested variable or the default value in case things went wrong.
        """
        self.__createDir()
        variable = default
        try:
            if os.path.isfile(self.base_path + name):
                f = open(self.base_path + name, 'rb')
                variable = pickle.load(f)
                f.close()
        except Exception, e:
            self.server.logger.logError("Could not load storage variable '%s': %s" % (name, e))
        return variable
