#!/usr/bin/python

import os
import time

import olof.core

class Logger(object):
    def __init__(self, hostname):
        self.hostname = hostname
        self.logBase = 'olof/plugins/logger'
        self.logDir = '/'.join([self.logBase, self.hostname])
        self.logs = {}

        if not os.path.exists(self.logDir):
            os.makedirs(self.logDir, mode=0755)

    def unload(self):
        for f in self.logs.values():
            f.close()

    def formatTimestamp(self, timestamp):
        return time.strftime('%Y%m%d-%H%M%S-%Z', time.localtime(timestamp))

class Scanner(Logger):
    def __init__(self, hostname):
        Logger.__init__(self, hostname)

        self.logFiles = ['messages', 'connections']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s.log' % (self.hostname, i)]),
            'a') for i in self.logFiles]))

        self.host = None
        self.port = None

    def unload(self):
        self.logConnection(time.time(), self.host, self.port, 'server shutdown')
        Logger.unload(self)

    def logInfo(self, timestamp, info):
        self.logs['messages'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), info]]) + '\n')
        self.logs['messages'].flush()

    def logConnection(self, timestamp, host, port, action):
        if action == 'made':
            self.host = host
            self.port = port

        self.logs['connections'].write(','.join([str(i) for i in [
            self.formatTimestamp(timestamp), host, port, action]]) + '\n')
        self.logs['connections'].flush()

class ScanSetup(Logger):
    def __init__(self, hostname, sensor_mac):
        Logger.__init__(self, hostname)
        self.sensor = sensor_mac

        self.logFiles = ['scan', 'rssi']
        self.logs = dict(zip(self.logFiles, [open('/'.join([
            self.logDir, '%s-%s-%s.log' % (self.hostname, self.sensor, i)]),
            'a') for i in self.logFiles]))

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
        if olof.data.whitelist.match(hostname):
            if not (hostname, sensor_mac) in self.scanSetups:
                ss = ScanSetup(hostname, sensor_mac)
                self.scanSetups[(hostname, sensor_mac)] = ss
            else:
                ss = self.scanSetups[(hostname, sensor_mac)]
            return ss

    def getScanner(self, hostname):
        if olof.data.whitelist.match(hostname):
            if not (hostname, None) in self.scanSetups:
                sc = Scanner(hostname)
                self.scanSetups[(hostname, None)] = sc
            else:
                sc = self.scanSetups[(hostname, None)]
            return sc

    def connectionMade(self, hostname, ip, port):
        if olof.data.whitelist.match(hostname):
            sc = self.getScanner(hostname)
            sc.logConnection(time.time(), ip, port, 'made')

    def connectionLost(self, hostname, ip, port):
        if olof.data.whitelist.match(hostname):
            sc = self.getScanner(hostname)
            try:
                sc.logConnection(time.time(), ip, port, 'lost')
            except ValueError:
                pass

    def infoFeed(self, hostname, timestamp, info):
        if olof.data.whitelist.match(hostname):
            sc = self.getScanner(hostname)
            sc.logInfo(timestamp, info)

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        if olof.data.whitelist.match(hostname):
            ss = self.getScanSetup(hostname, sensor_mac)
            ss.logCell(timestamp, mac, deviceclass, move)

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        if olof.data.whitelist.match(hostname):
            ss = self.getScanSetup(hostname, sensor_mac)
            ss.logRssi(timestamp, mac, rssi)
