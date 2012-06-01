#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides a few simple tests and conversions. Can for instance be used to validate configuration file values.

All tests take at least the value to validate as an argument. When the test passes, the value (or converted value)
should be returned. When the test fails it should raise a ValidationError.
"""

import random
import re

class ValidationError(Exception):
    """
    Exception to raise when the test fails.
    """
    def __init__(self, value=""):
        self.value = value

    def __str__(self):
        return repr(self.value)

def parseInt(value):
    """
    Parse the given value as an integer.
    """
    try:
        return int(value)
    except:
        raise ValidationError()

def parseFloat(value):
    """
    Parse the given value as a float.
    """
    try:
        return float(value)
    except:
        raise ValidationError()

def parseString(value):
    """
    Parse the given value as a string.
    """
    try:
        return str(value)
    except:
        raise ValidationError()

def isString(value):
    """
    Test if the given value is of type str.
    """
    if type(value) is str:
        return value
    else:
        raise ValidationError()

def isEmail(value):
    """
    Test if the given value is a valid e-mailaddress.
    """
    # E-mail validation regex from Django (django.core.validators)
    #   More information in LICENSE.
    email_re = re.compile(
        r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
        # quoted-string, see also http://tools.ietf.org/html/rfc2822#section-3.2.5
        r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-\011\013\014\016-\177])*"'
        r')@((?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$)'  # domain
        r'|\[(25[0-5]|2[0-4]\d|[0-1]?\d?\d)(\.(25[0-5]|2[0-4]\d|[0-1]?\d?\d)){3}\]$', re.IGNORECASE)
        # literal form, ipv4 address (SMTP 4.1.3)
    if email_re.match(value) == None:
        raise ValidationError()
    else:
        return value
