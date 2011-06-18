#!/usr/bin/python

import time

import olof.core

class Plugin(olof.core.Plugin):
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server)
        self.connection_log = open('logs/connections.log', 'a')
        self.mess_log = open('logs/messages.log', 'a')
        self.scan_log = open('logs/scan.log', 'a')
        self.rssi_log = open('logs/rssi.log', 'a')
        self.lag_avg_log = open('logs/lag_avg.log', 'a')
        self.lag_log = open('logs/lag.log', 'a')

        self.lag_sum = 0
        self.lag_cnt = 0

    def connectionMade(self, hostname, ip, port):
        self.log(self.connection_log, time.time(),
            "Connection made with %s (%s:%s)" % (hostname, ip, port))

    def connectionLost(self, hostname, ip, port):
        self.log(self.connection_log, time.time(),
            "Connection lost with %s (%s:%s)" % (hostname, ip, port))

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        lag = time.time() - float(timestamp)
        self.lag_sum += lag
        self.lag_cnt += 1

        self.log(self.lag_log, timestamp, str(lag))
        self.log(self.lag_avg_log, timestamp, str(self.lag_sum/(self.lag_cnt*1.0)))

        self.log(self.scan_log, timestamp, ','.join([hostname, mac, deviceclass,
            move]))

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        lag = time.time() - float(timestamp)
        self.lag_sum += lag
        self.lag_cnt += 1

        self.log(self.lag_log, timestamp, str(lag))
        self.log(self.lag_avg_log, timestamp, str(self.lag_sum/(self.lag_cnt*1.0)))

        self.log(self.rssi_log, timestamp, ','.join([hostname, mac, rssi]))

    def sysStateFeed(self, hostname, module, info):
        if module == 'gyrid':
            if info == 'connected':
                self.log(self.connection_log, int(time.time()),
                    "%s: Connection with Gyrid made.")
            elif info == 'disconnected':
                self.log(self.connection_log, int(time.time()),
                    "%s: Connection with Gyrid lost.")

    def log(self, log, timestamp, str):
        t = time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(float(timestamp)))
        log.write("%s,%s\n" % (t, str))
        log.flush()
