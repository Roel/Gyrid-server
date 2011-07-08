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
        self.__alertMap = {}

        a = Alert('Server', Alert.Type.ServerStartup,
            info=0, warning=None, alert=None, fire=None)
        self.addAlert(a)

        t = task.LoopingCall(self.sendAlerts)
        t.start(60)

    def addAlert(self, alert):
        self.alerts.append(alert)
        if not alert.origin in self.__alertMap:
            self.__alertMap[alert.origin] = [[alert.type, alert]]
        else:
            self.__alertMap[alert.origin].append([alert.type, alert])

    def getAlerts(self, origin, atype):
        if not origin in self.__alertMap:
            return []
        else:
            return [a[1] for a in self.__alertMap[origin] if a[0] in atype]

    def removeAlerts(self, alerts):
        for a in alerts:
            self.alerts.remove(a)
            self.__alertMap[a.origin].remove([a.type, a])

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
        ServerStartup, ScannerConnect, ScannerDisconnect, SensorDisconnect = range(4)

        Message = {ServerStartup: "Server has been started.",
                   ScannerConnect: "Scanner connected.",
                   ScannerDisconnect: "Scanner disconnected."}

    class Level:
        Info, Warning, Alert, Fire = range(4)

        String = {Info: 'Info', Warning: 'Warning', Alert: 'Alert', Fire: 'Fire'}

    def __init__(self, origin, type, etime=None, message=None,
                 info=0, warning=5, alert=15, fire=30):
        self.origin = origin
        self.type = type
        self.etime = etime if etime != None else int(time.time())
        self.message = message
        self.action = {Alert.Level.Info: [info, False],
                       Alert.Level.Warning: [warning, False],
                       Alert.Level.Alert: [alert, False],
                       Alert.Level.Fire: [fire, False]}

    def getStatusLevel(self, ctime):
        diff = ctime - self.etime
        for level in sorted(self.action.keys(), reverse=True):
            lTime = self.action[level][0]
            if lTime != None and diff >= lTime*60:
                return level

    def getMessageBody(self, level):
        msg = Alert.Level.String[level]
        msg += ' - %s -\r\n\r\n' % prettydate(self.etime)
        msg += Alert.Type.Message[self.type] + '\r\n\r\n'
        if self.message:
            msg += self.message
        msg += '--\r\nThis event occurred at %s.' % \
            time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(self.etime))
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

    def unload(self):
        pass

    def connectionMade(self, hostname, ip, port):
        # Remove any ScannerDisconnect/ScannerConnect alerts
        alerts = self.mailer.getAlerts(hostname, Alert.Type.ScannerDisconnect)
        self.mailer.removeAlerts(alerts)

        # Add ScannerConnect alert
        self.mailer.addAlert(Alert(hostname, Alert.Type.ScannerConnect,
                info=0, warning=None, alert=None, fire=None))

    def connectionLost(self, hostname, ip, port):
        a = self.mailer.getAlerts(hostname, Alert.Type.ScannerDisconnect)
        if len(a) == 0:
            self.mailer.addAlert(Alert(hostname, Alert.Type.ScannerDisconnect))
        else:
            a[0].etime = int(time.time())

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
