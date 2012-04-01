#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that handles configuration files of the server and its plugins.
"""

import imp
import os
import textwrap
import time

from olof.tools import validation
from olof.tools.inotifier import INotifier

class Configuration(object):
    """
    Main Configuration object representing a specific configuration file.
    """
    def __init__(self, server, name):
        """
        Initialisation.

        @param   server (Olof)   Reference to main Olof server instance.
        @param   name (str)      Name of this configuration file.
        """
        self.server = server
        self.name = name
        self.options = {}
        self.base_path = 'config/'
        self.location = self.base_path + self.name + '.conf.py'

        if not os.path.isdir(self.base_path):
            os.makedirs(self.base_path)

        self.inotifier = INotifier(self.location)
        self.inotifier.addCallback(INotifier.Write, self.__readConfig)

    def unload(self):
        """
        Unload this configuration instance.
        """
        self.inotifier.unload()

    def addOption(self, option):
        """
        Add an Option to this configuration file.

        @param   option (Option)   The Option to add.
        """
        self.options[option.name] = option

    def addOptions(self, iterable):
        """
        Add all the given Options.

        @param   iterable (list, set, ..)   The Options to add.
        """
        for o in iterable:
            self.addOption(o)

    def getValue(self, optionName):
        """
        Get the value of the option with the given name. Returns None when such option does not exist, else the
        validated value or a default value if the validation fails. If the option is not defined in the configuration
        file, return the default value too. The type this method return depends on the validation of the Option.

        @param    optionName (str)   The name of the option to get the value from.
        @return                      The value of this option, or None in case of an error.
        """
        if not optionName in self.options:
            return None
        elif 'config' not in self.__dict__:
            return self.options[optionName].getDefaultValue()
        elif optionName in self.config.__dict__:
            return self.options[optionName].validate(self.config.__dict__[optionName])
        else:
            return self.options[optionName].getDefaultValue()

    def generateDefault(self):
        """
        Generate the default configuration file.

        @return   (str)   The string representing the default configuration file.
        """
        if len(self.options) == 0:
            return ""
        else:
            s = "#-*- coding: utf-8 -*-\n"
            s += "# Gyrid Server: configuration file for %s\n\n" % self.name
            for o in sorted(self.options):
                s += self.options[o].render()
                s += "\n\n"
            return s[:-2]

    def updateConfigFile(self):
        """
        Update the configuration file, adding new options when appropriate.
        """
        to_append = []
        if len(self.options) > 0 and os.path.exists(self.location):
            self.__readConfig()
            for o in self.options:
                if not self.options[o].name in self.config.__dict__:
                    to_append.append(o)

        if len(to_append) > 0:
            f = open(self.location, 'a')
            s = ""
            for o in sorted(to_append):
                s += self.options[o].render()
                s += '\n\n'
            f.write('\n')
            f.write(s[:-2])
            f.close()

    def writeDefaultConfigFile(self):
        """
        Write the default configuration file to disk, when no such file exists yet.
        """
        if len(self.options) > 0 and not os.path.exists(self.location):
            f = open(self.location, 'w')
            f.write(self.generateDefault())
            f.close()

    def __readConfig(self, event=None):
        """
        Read the configuration file from disk.
        """
        try:
            c = imp.load_source(str(time.time()), self.location)
        except Exception, e:
            self.server.logger.logError("Failed to load config file: %s.conf.py: %s" % (
                self.name, e))
        else:
            self.config = c

    def readConfig(self):
        """
        Read the configuration file from disk. Create a default one when none exists, update if one exists.
        This should be called after all options are added.
        """
        if not os.path.exists(self.location):
            self.writeDefaultConfigFile()
        else:
            self.updateConfigFile()
        self.__readConfig()

class OptionValue(object):
    """
    Class representing a value for an Option.
    """
    def __init__(self, value, description=None, default=False):
        """
        Initialisation.

        @param   value               The value.
        @param   description (str)   A description for this value.
        @param   default (bool)      If this value is the default value.
        """
        self.value = value
        self.description = description
        self.default = default

    def render(self):
        """
        Render this OptionValue to text. For use in the configuration file.
        """
        d = {'value': self.value}
        d['default'] = ' (Default)' if self.default else ''
        d['description'] = ' %s' % self.description if self.description != None else ''
        d['link'] = ' -' if d['default'] or d['description'] else ''
        s = "%(value)s%(link)s%(default)s%(description)s" % d
        return "\n" + "\n#     ".join(textwrap.wrap("#   %s" % s, 116))

class Option(object):
    """
    Class representing an option in a configuration file.
    """
    def __init__(self, name, description=None):
        """
        Initialisation.

        @param   name (str)          The name of this option.
        @param   description (str)   A description for this option. Optional.
        """
        self.name = name
        self.description = description
        self.values = {}
        self.validation = None

    def setDescription(self, description):
        """
        Set the description for this option.

        @param   description (str)   The description to use.
        """
        self.description = description

    def setValidation(self, validation, *args):
        """
        Set the validation method for this Option. This method is called to validate values for this option.
        It is called with a value as the first argument followed by the other arguments. It should return the value
        if the validation passes, else None.

        By default, no validation is done.

        @param   validation (method)   Validation method.
        @param   *args                 Extra arguments. Optional.
        """
        self.validation = (validation, args)

    def validate(self, value):
        """
        Validate the given value for this option.

        @param    value   The value to validate.
        @return           The validated value, depending on the validation result this is the given value or the
                            default value.
        """
        if self.validation != None:
            v = self.validation[0](value, *self.validation[1])
            v = v if v != None else self.getDefaultValue()
        else:
            v = value

        if len(self.values) > 1:
            return v if v in self.values else self.getDefaultValue()
        else:
            return v

    def addValue(self, value):
        """
        Add an OptionValue to this option.

        @param   value (OptionValue)   The value to add.
        """
        self.values[value.value] = value

    def getDefaultValue(self):
        """
        Return the default value for this Option, None when none exists. Note there should be only one OptionValue
        that is 'default' for each Option.
        """
        for v in self.values.values():
            if v.default == True:
                return v.value
        return None

    def render(self):
        """
        Render this Option to text. For use in the configuration file.
        """
        s = ""
        if self.description != None:
            s += "\n# ".join(textwrap.wrap("# %s" % self.description, 118))
            s += "\n"

        if len(self.values) > 0:
            s += '#  Values:'
            for v in sorted(self.values):
                s += self.values[v].render()
            s += "\n"
        s += "%s = %s" % (self.name, self.getDefaultValue())
        return s
