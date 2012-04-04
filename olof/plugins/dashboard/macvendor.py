#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2009-2012  Roel Huybrechts
# All rights reserved.

"""
Module to get the vendor company from a mac address of a Bluetooth device.

Source of information (oui.txt):
    http://standards.ieee.org/regauth/oui/oui.txt
"""

import gzip
import os

VENDOR_MAC = {}

def _parseOui(url):
    """
    Parse the file populating the VENDOR_MAC dictionary.

    @param  url   URL of the file to parse.
    """
    if url.endswith('.gz'):
        file = gzip.GzipFile(url, 'r')
    else:
        file = open(url, 'r')
    for line in file:
        if not line.startswith('#'):
            ls = line.split('\t')
            VENDOR_MAC [ls[0]] = ls[1].strip('\n')
    file.close()

def getVendor(macAddress):
    """
    Retrieve the vendor company of the device with specified mac address.

    @param  macAddress  The mac address of the device.
    """
    return VENDOR_MAC.get(macAddress[:6].upper(), None)

#Parse the oui file on importing
try:
    __dir__ = os.path.dirname(os.path.abspath(__file__))
    filepath = os.path.join(__dir__, 'oui_data.txt')
    _parseOui(filepath)
except IOError:
    _parseOui('/usr/share/gyrid/oui_data.txt.gz')
