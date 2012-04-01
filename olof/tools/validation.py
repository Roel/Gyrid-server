#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2012  Roel Huybrechts
# All rights reserved.

"""
Module that provides a few simple tests and conversions. Can for instance be used to validate configuration file values.

All tests take at least the value to validate as an argument. When the test passes, the value (or converted value)
should be returned. When the test fails it should return None.
"""

def parseInt(value):
    """
    Parse the given value as an integer.
    """
    try:
        return int(value)
    except:
        return None

def parseFloat(value):
    """
    Parse the given value as a float.
    """
    try:
        return float(value)
    except:
        return None
