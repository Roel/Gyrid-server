#!/usr/bin/python

import os
import time

import olof.core

class ScanSetup(object):
    def __init__(self, hostname, sensor_mac):
        self.hostname = hostname
        self.sensor = sensor_mac
        self.logBase = 'olof/plugins/logger'

        self.logDir = '/'.join([self.logBase, self.hostname])

        if not os.path.exists(self.logDir):
            os.makedirs(self.logDir)

        self.logFiles = ['connections', 'messages', 'scan', 'rssi']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s-%s.log' % (self.hostname, self.sensor, i)]),
            'a') for i in self.logFiles]))

    def formatTimestamp(self, timestamp):
        return time.strftime('%Y%m%d-%H%M%S-%Z', time.localtime(timestamp))

    def unload(self):
        for f in self.logs.values():
            f.close()

    def logRssi(self, timestamp, mac, rssi):
        self.logs['rssi'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), mac, rssi]]) + '\n')
        self.logs['rssi'].flush()

    def logCell(self, timestamp, mac, deviceclass, move):
        self.logs['scan'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), mac, deviceclass, move]]) + '\n')
        self.logs['scan'].flush()

class Plugin(olof.core.Plugin):
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server)

        self.scanSetups = {}

    def unload(self):
        for ss in self.scanSetups.values():
            ss.unload()

    def getScanSetup(self, hostname, sensor_mac):
        if not (hostname, sensor_mac) in self.scanSetups:
            ss = ScanSetup(hostname, sensor_mac)
            self.scanSetups[(hostname, sensor_mac)] = ss
        else:
            ss = self.scanSetups[(hostname, sensor_mac)]
        return ss

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        ss = self.getScanSetup(hostname, sensor_mac)
        ss.logCell(timestamp, mac, deviceclass, move)

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        ss = self.getScanSetup(hostname, sensor_mac)
        ss.logRssi(timestamp, mac, rssi)
