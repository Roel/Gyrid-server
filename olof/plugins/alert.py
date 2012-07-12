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
import re
import smtplib
import time

import olof.configuration
import olof.core
import olof.tools.validation

from olof.tools.datetimetools import getRelativeTime

class Mailer(object):
    """
    Class that handles e-mail interaction.
    """
    def __init__(self, plugin):
        """
        Initialisation.

        Start the looping call that sends e-mails every minute.

        @param   plugin (Olof)   Reference to main Olof server instance.
        """
        self.plugin = plugin

        self.alerts = []
        self.__alertMap = {}

        self.sendAlertsCall = task.LoopingCall(self.sendAlerts)
        self.sendAlertsCall.start(60)

    def unload(self, shutdown=False):
        """
        Unload the mailer.
        """
        self.sendAlertsCall.stop()

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
            if module != None:
                return [a[1] for a in self.__alertMap[origin] if a[0] in atype and a[1].module == module]
            else:
                return [a[1] for a in self.__alertMap[origin] if a[0] in atype]

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

    def __connect(self):
        """
        Connect to the SMTP server.

        @return   (bool)   True if a connection has been made, else False.
        """
        smtp_server = self.plugin.config.getValue('smtp_server')
        smtp_port = self.plugin.config.getValue('smtp_port')
        smtp_encryption = self.plugin.config.getValue('smtp_encryption')
        smtp_username = self.plugin.config.getValue('smtp_username')
        smtp_password = self.plugin.config.getValue('smtp_password')

        if None in [smtp_server, smtp_port]:
            self.plugin.logger.logError('Cannot send e-mail: missing SMTP configuration')
            return False
        else:
            try:
                if smtp_encryption == 'SSL':
                    self.s = smtplib.SMTP_SSL(smtp_server, smtp_port)
                else:
                    self.s = smtplib.SMTP(smtp_server, smtp_port)
                self.s.ehlo()
                if smtp_encryption == 'TLS':
                    self.s.starttls()
                    self.s.ehlo()
                if None not in [smtp_username, smtp_password]:
                    self.s.login(smtp_username, smtp_password)
            except Exception as e:
                self.plugin.logger.logException(e, 'Cannot send e-mail: SMTP connection failed')
                self.plugin.logger.logInfo('You may want to check your SMTP configuration')
                return False
            else:
                return True

    def __sendMail(self, to, subject, message):
        """
        Send an e-mail with given details.

        @param   to (str)        The address to send the e-mail to.
        @param   subject (str)   The subject of the e-mail.
        @param   message (str)   The message to send.
        """
        from_address = self.plugin.config.getValue('from_address')
        msg = "From: Gyrid Server <%s>\r\n" % from_address
        msg += "To: %s\r\n" % to
        msg += "Subject: %s\r\n\r\n" % subject
        msg += message
        try:
            self.s.sendmail(from_address, to, msg)
        except Exception as e:
            self.plugin.logger.logException(e, 'Cannot send e-mail')
            self.plugin.logger.logInfo('You may want to check your SMTP configuration')

    def __disconnect(self):
        """
        Disconnect from the SMTP server.
        """
        try:
            self.s.quit()
        except smtplib.SMTPServerDisconnected:
            pass

    def __sendAlerts(self):
        """
        Send the alerts, intelligently.
        """
        if len(self.alerts) == 0:
            return

        t = int(time.time())
        mails = []
        to_delete = []

        recipients = self.plugin.config.getValue('recipients')

        for alert in self.alerts:
            recipients_sent = []
            level = alert.getStatusLevel(t)
            if level is not None and not alert.isSent(level):
                for r in recipients:
                    if alert.origin in (['Server'] + [p.filename for p in self.plugin.server.pluginmgr.getPlugins()]):
                        projects = [alert.origin]
                    else:
                        projects = [i for i in alert.projects if i != None]
                    for project in projects:
                        if re.match(r[0], project):
                            for a in r[1]:
                                if level >= r[1][a]:
                                    if a not in recipients_sent:
                                        subj = alert.origin
                                        if alert.origin in [
                                            p.filename for p in self.plugin.server.pluginmgr.getPlugins()]:
                                            subj = 'Plugin: %s' % alert.origin
                                        mails.append([a, subj, alert.getMessageBody(level)])
                                        recipients_sent.append(a)
                alert.markSent(level)

                al = sorted(alert.action.keys())
                nextLevels = al[al.index(level)+1:]
                if (len([a for a in nextLevels if alert.action[a][0] == None]) == \
                    len(nextLevels)) and alert.autoexpire:
                    to_delete.append(alert)

        self.removeAlerts(to_delete)

        if len(mails) > 0:
            if self.__connect():
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
        SensorConnect, GyridDisconnect, GyridConnect, SensorFailed, \
        SensorRestored, MoveUploadFailed, MoveUploadRestored = range(11)

        Message = {ServerStartup: "Server has been started.",
                   ScannerConnect: "Scanner connected.",
                   ScannerDisconnect: "Scanner disconnected.",
                   GyridConnect: "Gyrid daemon connected.",
                   GyridDisconnect: "Gyrid daemon disconnected.",
                   SensorConnect: "Sensor %(module)s connected.",
                   SensorDisconnect: "Sensor %(module)s disconnected.",
                   SensorFailed: "No recent inquiry for sensor %(module)s.",
                   SensorRestored: "Received recent inquiry for sensor %(module)s.",
                   MoveUploadFailed: "Move upload failed.",
                   MoveUploadRestored: "Move upload restored."}

    class Level:
        """
        Class representing the level of alerts. They are, in increasing impact, Info, Warning, Alert and Fire.
        """
        Info, Warning, Alert, Fire = range(4)

        String = {Info: 'Info', Warning: 'Level 1 warning: minor', Alert: 'Level 2 warning: major',
            Fire: 'Level 3 warning: serious'}

    def __init__(self, origin, projects, type, module=None, etime=None, autoexpire=True, message=None,
                 info=1, warning=5, alert=20, fire=45):
        """
        Initialisation.

        @param   origin (str)        The origin of this alert (i.e. the hostname of the scanner).
        @param   projects (set)      A set of projects this alert belongs to.
        @param   type (Alert.Type)   The type this alert.
        @param   module (str)        The module of this alert (i.e. the MAC-address of the sensor), when applicable.
        @param   etime (int)         The time the event causing the alert occured, in UNIX time. Current time when None.
        @param   autoexpire (bool)   If the alert automatically expires and is deleted if all messages are sent.
                                       Defaults to True.
        @param   message (str)       The message to send with this alert. Optional. A default message is always added
                                       based on the alert's type.
        @param   info (int)          Time in minutes to wait before sending the 'info' level message. Defaults to 1.
        @param   warning (int)       Time in minutes to wait before sending the 'warning' level message. Defaults to 5.
        @param   alert (int)         Time in minutes to wait before sending the 'alert' level message. Defaults to 20.
        @param   fire (int)          Time in minutes to wait before sending the 'fire' level message. Defaults to 45.
        """
        self.origin = origin
        self.projects = projects
        self.type = type
        self.module = module
        self.etime = etime if etime != None else int(time.time())
        self.autoexpire = autoexpire
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
        msg += ' - %s: \r\n\r\n' % getRelativeTime(self.etime)
        msg += Alert.Type.Message[self.type] % {'origin': self.origin,
                                                'module': self.module}
        msg += '\r\n\r\n'
        if self.message:
            msg += self.message.strip()
            msg += '\r\n\r\n'
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
    def __init__(self, server, filename):
        """
        Initialisation. Add ServerStartup info alert.
        """
        olof.core.Plugin.__init__(self, server, filename)

        self.alerts = {}
        self.mailer = Mailer(self)

        self.mailer.addAlert(Alert('Server', [], Alert.Type.ServerStartup,
            info=1, warning=None, alert=None, fire=None))

        self.connections = {}
        self.recentInquiries = {}

        self.checkRecentInquiriesCall = task.LoopingCall(self.checkRecentInquiries)
        self.checkRecentInquiriesCall.start(30, now=False)

    def unload(self, shutdown=False):
        """
        Unload the plugin.
        """
        olof.core.Plugin.unload(self, shutdown)
        self.mailer.unload(shutdown)
        try:
            self.checkRecentInquiriesCall.stop()
        except AssertionError:
            pass

    def checkRecentInquiries(self):
        """
        Check if recent inquiries are made on all sensors. Add alerts when necessary.
        """
        now = int(time.time())
        to_delete = []
        for scanner in self.recentInquiries:
            ap = self.server.dataprovider.getActivePlugins(scanner)
            apn = dict([(p.filename, ap[p]) for p in ap])
            for mac in self.recentInquiries[scanner]:
                i = self.recentInquiries[scanner][mac]
                if (now - i[0]) > 60:
                    if ('alert' in apn) and (len(apn['alert']) > 0):
                        self.mailer.addAlert(Alert(scanner, i[1], Alert.Type.SensorFailed, mac))
                    to_delete.append(mac)

        for i in to_delete:
            del(self.recentInquiries[scanner][mac])
            if len(self.recentInquiries[scanner]) < 1:
                del(self.recentInquiries[scanner])

    def defineConfiguration(self):
        """
        Define the configuration options for this plugin.
        """
        def validateRecipients(value):
            """
            Validate recipients dictionary.
            """
            d = []
            if type(value) is not list:
                raise olof.tools.validation.ValidationError()
            else:
                for i in value:
                    if type(i) is tuple and len(i) == 2 and type(i[0]) is str and type(i[1]) is dict:
                        nd = {}
                        d.append((i[0], nd))
                        for a in i[1]:
                            if Alert.Level.Info <= i[1][a] <= Alert.Level.Fire:
                                try:
                                    nd[olof.tools.validation.isEmail(a)] = i[1][a]
                                except olof.tools.validation.ValidationError:
                                    pass
            return d

        def validateEncryption(value):
            """
            Validate encryption settings.
            """
            if value not in [None, 'SSL', 'TLS']:
                raise olof.tools.validation.ValidationError()
            else:
                return value

        options = []

        o = olof.configuration.Option('smtp_server')
        o.setDescription('SMTP server to use for sending e-mail.')
        options.append(o)

        o = olof.configuration.Option('smtp_port')
        o.setDescription('TCP port to use while connecting to the SMTP server.')
        o.addValue(olof.configuration.OptionValue(25, default=True))
        o.setValidation(olof.tools.validation.parseInt)
        options.append(o)

        o = olof.configuration.Option('smtp_encryption')
        o.setDescription('Type of encryption to use for the SMTP connection.')
        o.addValue(olof.configuration.OptionValue(None, 'Use no encryption. Typically connect on port 25.',
            default=True))
        o.addValue(olof.configuration.OptionValue('SSL', 'Use SSL encryption. Typically connect on port 465.'))
        o.addValue(olof.configuration.OptionValue('TLS', 'Use TLS encryption. Typically connect on port 587.'))
        o.setValidation(validateEncryption)
        options.append(o)

        o = olof.configuration.Option('smtp_username')
        o.setDescription('Username to use for logging in to the SMTP server.')
        options.append(o)

        o = olof.configuration.Option('smtp_password')
        o.setDescription('Password to use for logging in to the SMTP server.')
        options.append(o)

        o = olof.configuration.Option('from_address')
        o.setDescription("E-mailaddress to use as the 'From:' address.")
        options.append(o)

        o = olof.configuration.Option('recipients')
        o.setDescription("List containing e-mailaddresses of recipients of e-mailalerts. The list should contain " + \
            "tuples mapping a regex string to a dictionary. The regex string is matched against the project name " + \
            "of the originating scanner (or 'Server' in case of a server alert). The dictionary should map " + \
            "e-mailaddresses to an Alert.Level. The recipient list is processed from start to end, matching " + \
            "regexes sequentially. The processing continues when a match is found, but when the same e-mailaddress " + \
            "is listed multiple times, the level of the first match is used.")
        o.setValidation(validateRecipients)
        o.addValue(olof.configuration.OptionValue([], default=True))
        options.append(o)

        return options

    def connectionMade(self, hostname, projects, ip, port):
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

        self.mailer.addAlert(Alert(hostname, projects, Alert.Type.ScannerConnect,
                info=1, warning=None, alert=None, fire=None))

    def connectionLost(self, hostname, projects, ip, port):
        """
        Remove GyridDisconnect alerts and add ScannerDisconnect alert.
        """
        if hostname in self.connections and (ip, port) in self.connections[hostname]:
            self.connections[hostname].remove((ip, port))

        if hostname in self.connections and len(self.connections[hostname]) == 0:
            a = self.mailer.getAlerts(hostname, [Alert.Type.GyridDisconnect,
                Alert.Type.SensorDisconnect, Alert.Type.SensorFailed])
            self.mailer.removeAlerts(a)

            self.recentInquiries[hostname] = {}

            a = self.mailer.getAlerts(hostname, [Alert.Type.ScannerDisconnect])
            if len(a) == 0:
                self.mailer.addAlert(Alert(hostname, projects, Alert.Type.ScannerDisconnect))
            else:
                a[0].etime = int(time.time())

    def stateFeed(self, hostname, projects, timestamp, sensorMac, info):
        """
        On 'started_scanning': remove SensorDisconnect alerts and add SensorConnect info alert.
        On 'stopped_scanning': add SensorDisconnect alert.
        """
        if info == 'started_scanning':
            a = self.mailer.getAlerts(hostname, [Alert.Type.SensorDisconnect,
                Alert.Type.SensorConnect], sensorMac)
            self.mailer.removeAlerts(a)
            self.mailer.addAlert(Alert(hostname, projects, Alert.Type.SensorConnect,
                sensorMac, info=1, warning=None, alert=None, fire=None))
        elif info == 'stopped_scanning':
            self.mailer.addAlert(Alert(hostname, projects, Alert.Type.SensorDisconnect,
                sensorMac))
            del(self.recentInquiries[hostname][sensorMac])
        elif info == 'new_inquiry':
            if hostname in self.recentInquiries and sensorMac in self.recentInquiries[hostname]:
                a = self.mailer.getAlerts(hostname, [Alert.Type.SensorFailed], sensorMac)
                if len(a) > 0:
                    self.mailer.addAlert(Alert(hostname, projects, Alert.Type.SensorRestored,
                        sensorMac, info=1, warning=None, alert=None, fire=None))
                self.mailer.removeAlerts(a)
                self.mailer.removeAlerts(self.mailer.getAlerts(hostname, [Alert.Type.GyridDisconnect]))
            if hostname not in self.recentInquiries:
                self.recentInquiries[hostname] = {}
            self.recentInquiries[hostname][sensorMac] = [int(time.time()), projects]

    def sysStateFeed(self, hostname, projects, module, info):
        """
        On 'connected': remove GyridDisconnect alerts and add GyridConnect info alert.
        On 'disconnected': add GyridDisconnect alert.
        """
        if module == 'gyrid':
            if info == 'connected':
                a = self.mailer.getAlerts(hostname, [Alert.Type.GyridDisconnect,
                    Alert.Type.GyridConnect])
                self.mailer.removeAlerts(a)
                self.mailer.addAlert(Alert(hostname, projects, Alert.Type.GyridConnect,
                    info=1, warning=None, alert=None, fire=None))
            elif info == 'disconnected':
                self.mailer.addAlert(Alert(hostname, projects, Alert.Type.GyridDisconnect,
                    info=1, warning=5, alert=10, fire=20))
