#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Plugin that provides e-mailalerts in case things go wrong.
"""

from twisted.internet import reactor, task, threads

import datetime
import smtplib
import time

import olof.core

def prettyDate(d, prefix="", suffix=" ago"):
    """
    Turn a UNIX timestamp in a prettier, more readable string.

    @param    d (int)        The UNIX timestamp to convert.
    @param    prefix (str)   The prefix to add. No prefix by default.
    @param    suffix (str)   The suffix to add, " ago" by default.
    @return   (str)          The string corresponding to the timestamp.
    """
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
    """
    Class that handles e-mail interaction.
    """
    def __init__(self):
        """
        Initialisation.

        Reads the configuration from alert/mailserver.conf and start the looping call that sends e-mails every minute.
        """
        self.server = 'smtp.ugent.be'
        self.port = 587
        self.from_address = 'noreply@gyrid-server.ugent.be'
        self.recipients = {}

        f = open('olof/plugins/alert/mailserver.conf')
        for line in f:
            ls = line.strip().split(',')
            if len(ls) == 1 and ls[0] == '':
                continue
            self.__dict__[ls[0]] = ls[1]
        f.close()

        self.alerts = []
        self.__alertMap = {}
        self.loadRecipients()

        t = task.LoopingCall(self.sendAlerts)
        t.start(60)

    def loadRecipients(self, *args):
        """
        Read the recipients from alert/recipients.conf.

        @param   *args   Can be ignored.
        """
        r = {}
        f = open('olof/plugins/alert/recipients.conf')
        for line in f:
            ls = line.strip().split(',')
            if len(ls) == 1 and ls[0] == '':
                continue
            r[ls[0]] = eval(ls[1])
        f.close()

        self.recipients = r

    def addAlert(self, alert):
        """
        Add an alert.

        @param   alert (Alert)   The alert to add.
        """
        self.alerts.append(alert)
        if not alert.origin in self.__alertMap:
            self.__alertMap[alert.origin] = [[alert.type, alert]]
        else:
            self.__alertMap[alert.origin].append([alert.type, alert])

    def getAlerts(self, origin, atype, module=None):
        """
        Get the alerts matching the origin, type and module given.

        @param   origin (str)               The origin of the alert (i.e. the hostname of the scanner).
        @param   atype (list(Alert.Type))   A list of Alert.Type's to match.
        @param   module (str)               The module (i.e. sensor MAC), when applicable.
        @return  (list(Alert))              A list of matching Alert's.
        """
        if not origin in self.__alertMap:
            return []
        else:
            return [a[1] for a in self.__alertMap[
                origin] if a[0] in atype and a[1].module == module]

    def removeAlerts(self, alerts):
        """
        Remove the given alerts.

        @param   alerts (list(Alert))   A list of Alerts to remove.
        """
        for a in alerts:
            self.alerts.remove(a)
            self.__alertMap[a.origin].remove([a.type, a])

    def sendAlerts(self):
        """
        Send the Alerts by e-mail and reload recipients when finished.
        """
        d = threads.deferToThread(self.__sendAlerts)
        d.addCallback(self.loadRecipients)

    def __connect(self):
        """
        Connect to the SMTP server.
        """
        self.s = smtplib.SMTP(self.server, self.port)
        self.s.ehlo()
        self.s.starttls()
        self.s.ehlo()
        self.s.login(self.user, self.password)

    def __sendMail(self, to, subject, message):
        """
        Send an e-mail with given details.

        @param   to (str)        The address to send the e-mail to.
        @param   subject (str)   The subject of the e-mail.
        @param   message (str)   The message to send.
        """
        msg = "From: Gyrid Server <%s>\r\n" % self.from_address
        msg += "To: %s\r\n" % to
        msg += "Subject: %s\r\n\r\n" % subject
        msg += message
        self.s.sendmail(self.from_address, to, msg)

    def __disconnect(self):
        """
        Disconnect from the SMTP server.
        """
        self.s.quit()

    def __sendAlerts(self):
        """
        Send the alerts, intelligently.
        """
        if len(self.alerts) == 0:
            return

        t = int(time.time())
        mails = []

        to_delete = []
        for alert in self.alerts:
            level = alert.getStatusLevel(t)
            if level is not None and not alert.isSent(level):
                for r in self.recipients:
                    if level >= self.recipients[r]:
                        mails.append([r,
                            alert.origin,
                            alert.getMessageBody(level)])
                alert.markSent(level)

                al = sorted(alert.action.keys())
                nextLevels = al[al.index(level)+1:]
                if len([a for a in nextLevels if alert.action[a][0] == None]) == \
                    len(nextLevels):
                    to_delete.append(alert)

        self.removeAlerts(to_delete)

        if len(mails) > 0:
            self.__connect()
            for m in mails:
                self.__sendMail(m[0], m[1], m[2])
            self.__disconnect()

class Alert(object):
    """
    Class representing an alert.
    """
    class Type:
        """
        Class representing a type of alert.
        """
        ServerStartup, ScannerConnect, ScannerDisconnect, SensorDisconnect, \
        SensorConnect, GyridDisconnect, GyridConnect = range(7)

        Message = {ServerStartup: "Server has been started.",
                   ScannerConnect: "Scanner connected.",
                   ScannerDisconnect: "Scanner disconnected.",
                   GyridConnect: "Gyrid daemon connected.",
                   GyridDisconnect: "Gyrid daemon disconnected.",
                   SensorConnect: "Sensor %(module)s connected.",
                   SensorDisconnect: "Sensor %(module)s disconnected."}

    class Level:
        """
        Class representing the level of alerts. They are, in increasing impact, Info, Warning, Alert and Fire.
        """
        Info, Warning, Alert, Fire = range(4)

        String = {Info: 'Info', Warning: 'Warning', Alert: 'Alert', Fire: 'Fire'}

    def __init__(self, origin, type, module=None, etime=None, message=None,
                 info=1, warning=5, alert=20, fire=45):
        """
        Initialisation.

        @param   origin (str)        The origin of this alert (i.e. the hostname of the scanner).
        @param   type (Alert.Type)   The type this alert.
        @param   module (str)        The module of this alert (i.e. the MAC-address of the sensor), when applicable.
        @param   etime (int)         The time the event causing the alert occured, in UNIX time. Current time when None.
        @param   message (str)       The message to send with this alert. Optional. A default message is always added
                                       based on the alert's type.
        @param   info (int)          Time in minutes to wait before sending the 'info' level message. Defaults to 1.
        @param   warning (int)       Time in minutes to wait before sending the 'warning' level message. Defaults to 5.
        @param   alert (int)         Time in minutes to wait before sending the 'alert' level message. Defaults to 20.
        @param   fire (int)          Time in minutes to wait before sending the 'fire' level message. Defaults to 45.
        """
        self.origin = origin
        self.type = type
        self.module = module
        self.etime = etime if etime != None else int(time.time())
        self.message = message
        self.action = {Alert.Level.Info: [info, False],
                       Alert.Level.Warning: [warning, False],
                       Alert.Level.Alert: [alert, False],
                       Alert.Level.Fire: [fire, False]}

    def getStatusLevel(self, ctime):
        """
        Get the status level of this alert at the given time.

        @param    ctime (int)     The timestamp to check, in UNIX time.
        @return   (Alert.Level)   The corresponding Alert.Level
        """
        diff = ctime - self.etime
        for level in sorted(self.action.keys(), reverse=True):
            lTime = self.action[level][0]
            if lTime != None and diff >= lTime*60:
                return level

    def getMessageBody(self, level):
        """
        Get the message body for this alert, given the level.

        @param    level (Alert.Level)   The level to check.
        @return   (str)                 The corresponding message body.
        """
        msg = Alert.Level.String[level]
        msg += ' - %s -\r\n\r\n' % prettyDate(self.etime)
        msg += Alert.Type.Message[self.type] % {'origin': self.origin,
                                                'module': self.module}
        msg += '\r\n\r\n'
        if self.message:
            msg += self.message
        msg += '--\r\nThis event occurred at %s.' % \
            time.strftime("%Y%m%d-%H%M%S-%Z", time.localtime(self.etime))
        return msg

    def markSent(self, level):
        """
        Mark the given level as 'sent' for this alert.

        @param   level (Alert.Level)   The level to mark.
        """
        self.action[level][1] = True

    def isSent(self, level):
        """
        Check if the message for the given level has been sent.

        @param    level (Alert.Level)   The level to check.
        @return   (bool)                True if the message has been sent, else False.
        """
        return self.action[level][1]

class Plugin(olof.core.Plugin):
    """
    Main Alert plugin class.
    """
    def __init__(self, server):
        """
        Initialisation. Add ServerStartup info alert.
        """
        olof.core.Plugin.__init__(self, server)

        self.alerts = {}
        self.mailer = Mailer()

        self.mailer.addAlert(Alert('Server', Alert.Type.ServerStartup,
            info=1, warning=None, alert=None, fire=None))

        self.connections = {}

    def connectionMade(self, hostname, ip, port):
        """
        Add ScannerConnect info alert and remove all ScannerDisconnect alerts.
        """
        if not hostname in self.connections:
            self.connections[hostname] = [(ip, port)]
        else:
            self.connections[hostname].append((ip, port))

        alerts = self.mailer.getAlerts(hostname, [Alert.Type.ScannerDisconnect,
            Alert.Type.ScannerConnect])
        self.mailer.removeAlerts(alerts)

        self.mailer.addAlert(Alert(hostname, Alert.Type.ScannerConnect,
                info=1, warning=None, alert=None, fire=None))

    def connectionLost(self, hostname, ip, port):
        """
        Remove GyridDisconnect alerts and add ScannerDisconnect alert.
        """
        if hostname in self.connections and (ip, port) in self.connections[hostname]:
            self.connections[hostname].remove((ip, port))

        if len(self.connections[hostname]) == 0:
            a = self.mailer.getAlerts(hostname, [Alert.Type.GyridDisconnect,
                Alert.Type.SensorDisconnect])
            self.mailer.removeAlerts(a)

            a = self.mailer.getAlerts(hostname, [Alert.Type.ScannerDisconnect])
            if len(a) == 0:
                self.mailer.addAlert(Alert(hostname, Alert.Type.ScannerDisconnect))
            else:
                a[0].etime = int(time.time())

    def stateFeed(self, hostname, timestamp, sensor_mac, info):
        """
        On 'started_scanning': remove SensorDisconnect alerts and add SensorConnect info alert.
        On 'stopped_scanning': add SensorDisconnect alert.
        """
        if info == 'started_scanning':
            a = self.mailer.getAlerts(hostname, [Alert.Type.SensorDisconnect,
                Alert.Type.SensorConnect], sensor_mac)
            self.mailer.removeAlerts(a)
            self.mailer.addAlert(Alert(hostname, Alert.Type.SensorConnect,
                sensor_mac, info=1, warning=None, alert=None, fire=None))
        elif info == 'stopped_scanning':
            self.mailer.addAlert(Alert(hostname, Alert.Type.SensorDisconnect,
                sensor_mac))

    def sysStateFeed(self, hostname, module, info):
        """
        On 'connected': remove GyridDisconnect alerts and add GyridConnect info alert.
        On 'disconnected': add GyridDisconnect alert.
        """
        if module == 'gyrid':
            if info == 'connected':
                a = self.mailer.getAlerts(hostname, [Alert.Type.GyridDisconnect,
                    Alert.Type.GyridConnect])
                self.mailer.removeAlerts(a)
                self.mailer.addAlert(Alert(hostname, Alert.Type.GyridConnect,
                    info=1, warning=None, alert=None, fire=None))
            elif info == 'disconnected':
                self.mailer.addAlert(Alert(hostname, Alert.Type.GyridDisconnect,
                    info=1, warning=5, alert=10, fire=20))
