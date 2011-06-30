#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011  Roel Huybrechts
# All rights reserved.

"""
Module that handles the communication with the Move REST API.
"""

from twisted.internet import reactor, task

import datetime
import smtplib
import time

import olof.core

def prettydate(d, prefix="", suffix=" ago"):
    t = d
    d = datetime.datetime.fromtimestamp(d)
    diff = datetime.datetime.now() - d
    s = diff.seconds
    if diff.days < 0:
        r =  d.strftime('%d %b %y')
    elif diff.days == 1:
        r =  '%s1 day%s' % (prefix, suffix)
    elif diff.days > 1:
        r =  '%s%i days%s' % (prefix, diff.days, suffix)
    elif s <= 1:
        r =  'just now'
    elif s < 60:
        r =  '%s%i seconds%s' % (prefix, s, suffix)
    elif s < 120:
        r =  '%s1 minute%s' % (prefix, suffix)
    elif s < 3600:
        r =  '%s%i minutes%s' % (prefix, s/60, suffix)
    elif s < 7200:
        r =  '%s1 hour%s' % (prefix, suffix)
    else:
        r =  '%s%i hours%s' % (prefix, s/3600, suffix)
    return r

class Mailer(object):
    def __init__(self):
        self.server = 'smtp.ugent.be'
        self.port = 587
        self.from_address = 'noreply@gyrid-server.ugent.be'

        f = open('olof/plugins/alert/mailserver.conf')
        for line in f:
            ls = line.strip().split(',')
            self.__dict__[ls[0]] = ls[1]
        f.close()

        self.recipients = {'mail+gyrid@rulus.be': Alert.Level.Info}
        self.alerts = []

        a = Alert('Server', Alert.Type.ServerStartup, int(time.time()))
        self.addAlert(a)

        t = task.LoopingCall(self.sendAlerts)
        t.start(60)

    def addAlert(self, alert):
        self.alerts.append(alert)

    def sendAlerts(self):
        reactor.callInThread(self.__sendAlerts)

    def __connect(self):
        self.s = smtplib.SMTP(self.server, self.port)
        self.s.ehlo()
        self.s.starttls()
        self.s.ehlo()
        self.s.login(self.user, self.password)

    def __sendMail(self, to, subject, message):
        msg = "From: Gyrid Server <%s>\r\n" % self.from_address
        msg += "To: %s\r\n" % to
        msg += "Subject: %s\r\n\r\n" % subject
        msg += message
        self.s.sendmail(self.from_address, to, msg)

    def __disconnect(self):
        self.s.quit()

    def __sendAlerts(self):
        if len(self.alerts) == 0:
            return

        t = int(time.time())
        mails = []

        for alert in self.alerts:
            level = alert.getStatusLevel(t)
            print Alert.Level.String[level]
            if level is not None and not alert.isSent(level):
                for r in self.recipients:
                    print "Checking recipient %s" % r
                    if level >= self.recipients[r]:
                        mails.append([r,
                            alert.origin,
                            alert.getMessageBody(level)])
                alert.markSent(level)

        if len(mails) > 0:
            print "Connecting ..."
            self.__connect()
            for m in mails:
                self.__sendMail(m[0], m[1], m[2])
                print "Sending e-mail to %s" % r
            print "Disconnecting ..."
            self.__disconnect()

class Alert(object):
    class Type:
        ServerStartup, ScannerDisconnect, SensorDisconnect = range(3)

        Message = {ServerStartup: "Server has been started.",
                   ScannerDisconnect: "Scanner disconnected."}

    class Level:
        Info, Warning, Alert, Fire = range(4)

        String = {Info: 'Info', Warning: 'Warning', Alert: 'Alert', Fire: 'Fire'}

    def __init__(self, origin, type, time, message=None,
                 info=0, warning=5, alert=15, fire=30):
        self.origin = origin
        self.type = type
        self.time = time
        self.message = message
        self.action = {Alert.Level.Info: [info, False],
                       Alert.Level.Warning: [warning, False],
                       Alert.Level.Alert: [alert, False],
                       Alert.Level.Fire: [fire, False]}

    def getStatusLevel(self, time):
        diff = time - self.time
        for level in sorted(self.action.keys(), reverse=True):
            if diff >= ((self.action[level][0])*60):
                return level

    def getMessageBody(self, level):
        msg = Alert.Level.String[level]
        msg += ' - %s -\r\n\r\n' % prettydate(self.time)
        msg += Alert.Type.Message[self.type] + '\r\n\r\n'
        if self.message:
            msg += self.message
        msg += '--\r\nThis event occurred at %s.' % \
            time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(self.time))
        return msg

    def markSent(self, level):
        self.action[level][1] = True

    def isSent(self, level):
        return self.action[level][1]

class Plugin(olof.core.Plugin):
    """
    Class that can interact with the Gyrid network component.
    """
    def __init__(self, server):
        olof.core.Plugin.__init__(self, server)

        self.alerts = {}
        self.mailer = Mailer()

    def getAlert(self, hostname, type):
        r = []
        if hostname in self.alerts:
            for alert in self.alerts[hostname]:
                if alert.type == type:
                    r.append(alert)
        else:
            self.alerts[hostname] = []
        return r

    def unload(self):
        pass

    def connectionMade(self, hostname, ip, port):
        a = self.getAlert(hostname, Alert.Type.ScannerDisconnect)
        if len(a) > 0:
            self.alerts[hostname].remove(a[0])

    def connectionLost(self, hostname, ip, port):
        a = self.getAlert(hostname, Alert.Type.ScannerDisconnect)
        if len(a) == 0:
            self.alerts[hostname].append(Alert(Alert.Type.ScannerDisconnect,
                int(time.time()), 'Scanner disconnected', 2, 5, 10, 20))
        else:
            a[0].time = int(time.time())

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        pass

    def sysStateFeed(self, hostname, module, info):
        pass

    def infoFeed(self, hostname, timestamp, info):
        pass

    def dataFeedCell(self, hostname, timestamp, sensor_mac, mac, deviceclass,
            move):
        pass

    def dataFeedRssi(self, hostname, timestamp, sensor_mac, mac, rssi):
        pass
