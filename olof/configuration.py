#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2007-2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides all options of the program and the handling of the configuration file.

Classes:
    Configuration: The main class, stores all Options and can get the value.
    _ConfigurationParser: The configuration file parser.
    _Option: Class for all Options.
"""

import ConfigParser
import os
import sys
import textwrap

class Configuration(object):
    """
    Store all the configuration options and retrieve the value of a certain option with the ConfigurationParser.
    """
    def __init__(self, server, configfile):
        """
        Initialisation. Construct an empty list of options, and fill it with all the Options.

        @param  configfile   URL of the configfile to write to.
        """
        self.server = server
        self.options = []
        self.configfile = configfile
        self._defineOptions()
        self.configparser = _ConfigurationParser(self)

    def _defineOptions(self):
        """
        Create all options and add them to the list.
        """
        ssl_server_crt = _Option(name = 'ssl_server_crt',
            description = 'Path to the SSL server certificate.',
            values = {},
            default = 'keys/server.crt')

        ssl_server_key = _Option(name = 'ssl_server_key',
            description = 'Path to the SSL server key.',
            values = {},
            default = 'keys/server.key')

        ssl_server_ca = _Option(name = 'ssl_server_ca',
            description = 'Path to the SSL server CA.',
            values = {},
            default = 'keys/ca.pem')

        tcp_listening_port = _Option(name = 'tcp_listening_port',
            description = 'The TCP port to listen on for incoming connection from the scanners.',
            type = 'int("%s")',
            values = {2583: 'Listen on port 2583 by default.'},
            default = 2583)

        self.options.extend([ssl_server_ca, ssl_server_crt, ssl_server_key, tcp_listening_port])

    def _getOptionByName(self, name):
        """
        Get the Option object of the option with the given name.

        @param  name   (str)       The name of the object.
        @return        (Option)    The Option object with the given name, None if such object does not exist.
        """
        for option in self.options:
            if option.name == name:
                return option
        return None

    def getValue(self, option):
        """
        Retrieve the value of the option.

        @param  option   (str)       The option to retrieve the value from.
        @return          (unicode)   The value of the option.
        """
        optionObj = self._getOptionByName(option)

        try:
            value = self.configparser.getValue(option)
            if value != None:
                config = eval(optionObj.type % value)
            else:
                if not optionObj.hidden:
                    raise ValueError("No valid value.")
                else:
                    config = None
        except:
            self.server.logger.logError("Issue concerning option '%s' : " % option + str(sys.exc_info()[1]) + \
                " [Using default value: %s]" % optionObj.default)
            config = None

        if config != None and optionObj.valuesHasKey(config):
            return config
        elif config != None:
            self.server.logger.logError("Wrong value for option %(option)s: '%(value)s'." % \
                {'option': optionObj.name, 'value': config} + "[Using default value: %s]" % optionObj.default)

        if optionObj.default == None and optionObj.type == 'str("%s")':
            return None
        else:
            return eval(optionObj.type % optionObj.default)

    def _parseInt(self, integer):
        """
        Parse the argument as an integer. Return the integer value on success, None on ValueError.
        """
        try:
            return int(integer)
        except (ValueError, TypeError):
            return None

class _ConfigurationParser(ConfigParser.ConfigParser, object):
    """
    Handles interaction with the configuration file.
    """
    def __init__(self, configuration):
        """
        Initialisation.

        @param  configuration  (Configuration)    Configuration instance.
        """
        ConfigParser.ConfigParser.__init__(self)
        self.configuration = configuration
        self.config_file_location = self.configuration.configfile
        self.updateConfigFile()
        ConfigParser.ConfigParser.read(self, self.config_file_location)

    def updateConfigFile(self):
        """
        If no configuration file exists, copy a new default one.
        """

        if not os.path.isfile(self.config_file_location):
            file = open(self.config_file_location, "w")
            file.write(self._generateDefault())
            file.close()
        else:
            #FIXME: update when necessary
            pass

    def _generateDefault(self):
        """
        Generates a default configuration file.

        @return  (str)    A default configuration file, based on the configuration options.
        """
        default = '# Gyrid Server configuration file\n[Gyrid Server]\n\n'
        for option in self.configuration.options:
            if not option.hidden:
                default += "\n# ".join(textwrap.wrap("# %s" % option.description, 78))
                if option.values:
                    default += '\n#  Values:'
                    for key in option.values.items():
                        if key[0] == option.default:
                            defaultValue = '(default) '
                        else:
                            defaultValue = ''
                        default += '\n#  %s - %s%s' % (key[0], defaultValue, key[1])
                default += '\n%s = %s\n\n' % (option.name, option.default)
        return default.rstrip('\n')

    def getValue(self, option):
        """
        Get the value of the given option in the configuration file.

        @return   (str)    The value of the option in the configuration file.
                           None in case of an error, e.g. there is no such
                           option.
        """
        try:
            return ConfigParser.ConfigParser.get(self, 'Gyrid Server', option)
        except:
            return None

class _Option(object):
    """
    Class for an option.
    """
    def __init__(self, name, description, default, values, type='str("%s")',
            hidden=False):
        """
        Initialisation.

        Mandatory:
        @param  name          (str)   The name of the option.
        @param  description   (str)   A descriptive documentation string.
        @param  values        (dict)  Which values are accepted. The value as
                  key, a description as value. If there's only one key,
                  this value is treated as a default and all other values are
                  accepted too. If there are multiple keys, these values are
                  restrictive.

        Optional
        @param  type          (str)   The type of the value of the option.
                  F.ex. 'str("%s")' (default), 'int(str(%s))'.
        @param  hidden        (bool)  If this is a hidden option, one that is
                  not written out to the config file. Defaults to False.
        """
        #Mandatory
        self.name = name
        self.description = description
        self.default = default
        self.values = values

        #Optional
        self.type = type
        self.hidden = hidden

    def valuesHasKey(self, key):
        """
        Checks if the given key is in the values
        dictionary.

        @param key     (str)       The key to check.
        @return        (boolean)   True if the key is in the dict.
        """
        if len(self.values) <= 1:
            return True
        else:
            for item in self.values.keys():
                try:
                    if item.lower() == key.lower():
                        return True
                except:
                    if item == key:
                        return True
                    elif str(item) == str(key):
                        return True
            return False
