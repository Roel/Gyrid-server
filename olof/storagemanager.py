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
    Class that manages saving and loading objects to and from disk.
    """
    def __init__(self, server, directoryName):
        """
        Initialisation.

        @param   server (Olof)         Reference to main Olof server instance.
        @param   directoryName (str)   Name of the storage subdirectory to save and load files.
        """
        self.server = server
        self.base_path = self.server.paths['storage'] + '/%s/' % directoryName

    def __createDir(self):
        """
        Create the base directory if is does not exists already.
        """
        if not os.path.exists(self.base_path):
            os.makedirs(self.base_path)

    def storeObject(self, object, name):
        """
        Save the object to disk.

        @param   object       Object to save. Dynamically typed objects (i.e. objects of classes defined in plugin
                                modules) cannot be saved. If you do need to save them, move those classes to a different
                                module; however losing the dynamic reloading of those objects.
        @param   name (str)   Unique name to identify this object, later used to load the same object from disk.
        """
        self.__createDir()
        try:
            if 'dynamic-plugin-module' in type(object).__module__:
                raise ValueError('Object type is defined in dynamic-plugin-module')
            f = open(self.base_path + name, 'wb')
            pickle.dump(object, f)
            f.close()
        except Exception as e:
            self.server.logger.logException(e, "Could not save storage object '%s'" % name)
            if 'dynamic-plugin-module' in str(e):
                self.server.logger.logInfo("Objects of types/classes defined in plugin modules cannot be stored")

    def loadObject(self, name, default=None):
        """
        Load the object from disk.

        @param   name (str)   Unique name of the object to load.
        @param   default      A default value to return in case of an error or a non-existing object.
        @return               The requested object or the default value in case things went wrong.
        """
        self.__createDir()
        object = default
        try:
            if os.path.isfile(self.base_path + name):
                f = open(self.base_path + name, 'rb')
                object = pickle.load(f)
                f.close()
        except Exception as e:
            self.server.logger.logException(e, "Could not load storage object '%s'" % name)
            if 'dynamic-plugin-module' in str(e):
                self.server.logger.logInfo("Objects of types/classes defined in plugin modules cannot be stored")
        return object
