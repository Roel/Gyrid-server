#-*- coding: utf-8 -*-
#
# This file belongs to Gyrid Server.
#
# Copyright (C) 2011-2012  Roel Huybrechts
# All rights reserved.

"""
Module providing useful tools regarding dates and times.
"""

import datetime

def getRelativeTime(timestamp, now=None, levels=1, futurePrefix="in ", pastSuffix=" ago", wrapper=None):
    """
    Get a relative string representation from comparing two timestamps.

    @param   timestamp            First timestamp to compare. Should be either a datetime.datetime instance or a UNIX
                                    timestamp as an integer or floating point value.
    @param   now                  Second timestamp to compare. Should be either a datetime.datetime instance or a UNIX
                                    timestamp as an integer or floating point value. Optional: use the current time when
                                    omitted.
    @param   levels (int)         The maximum number of time levels to use when formatting the string. Defaults to 1.
    @param   futurePrefix (str)   The prefix to use when formatting a time in the future. Defaults to "in ".
    @param   pastSuffix (str)     The suffix to use when formatting a time in the past. Defaults to " ago".
    @param   wrapper (method)     An optional wrapper method. Takes one argument: the first timestamp in the comparison
                                    as a datetime.datetime instance. Should return two strings which a pre- and appended
                                    to the resulting string respectively.
    """
    def timeSince(d, now=None, reversed=False):
        """
        Takes two datetime objects and returns the time between d and now
        as a nicely formatted string, e.g. "10 minutes".  If d occurs after now,
        then "0 minutes" is returned.

        Units used are years, months, weeks, days, hours, minutes and seconds.
        Microseconds are ignored.  Up to two adjacent units will be displayed.
        For example, "2 weeks, 3 days" and "1 year, 3 months" are possible outputs,
        but "2 weeks, 3 hours" and "1 year, 5 days" are not.

        Adapted from http://blog.natbat.co.uk/archive/2003/Jun/14/time_since
        Adapted from django.utils.timesince, more info in LICENSE.
        """
        def singularOrPlural(singular, plural, number):
            return singular if number == 1 else plural

        chunks = (
          (60 * 60 * 24 * 365, lambda n: singularOrPlural('year', 'years', n)),
          (60 * 60 * 24 * 30, lambda n: singularOrPlural('month', 'months', n)),
          (60 * 60 * 24 * 7, lambda n : singularOrPlural('week', 'weeks', n)),
          (60 * 60 * 24, lambda n : singularOrPlural('day', 'days', n)),
          (60 * 60, lambda n: singularOrPlural('hour', 'hours', n)),
          (60, lambda n: singularOrPlural('minute', 'minutes', n)),
          (1, lambda n: singularOrPlural('second', 'seconds', n)),
        )
        # Convert datetime.date to datetime.datetime for comparison.
        if not isinstance(d, datetime.datetime):
            d = datetime.datetime(d.year, d.month, d.day)
        if now and not isinstance(now, datetime.datetime):
            now = datetime.datetime(now.year, now.month, now.day)
        elif now and type(now) is int or type(now) is float:
            now = datetime.datetime.fromtimestamp(now)

        if not now:
            now = datetime.datetime.now()

        delta = (d - now) if reversed else (now - d)
        # ignore microseconds
        since = delta.days * 24 * 60 * 60 + delta.seconds
        if since <= 0:
            # d is in the future compared to now, stop processing.
            return u'0 minutes'
        for i, (seconds, name) in enumerate(chunks):
            count = since // seconds
            if count != 0:
                break
        s = '%(number)d %(type)s' % {'number': count, 'type': name(count)}
        for j in range(levels-1):
            if i +j + 1 < len(chunks):
                # Now get the second item
                seconds2, name2 = chunks[i + j + 1]
                count2 = (since - (seconds * count)) // seconds2
                if count2 != 0:
                    s += ', %(number)d %(type)s' % {'number': count2, 'type': name2(count2)}
        return s

    def timeUntil(d, now=None):
        """
        Like timesince, but returns a string measuring the time until
        the given time.
        """
        return timeSince(d, now, reversed=True)

    if type(timestamp) is int or type(timestamp) is float:
        timestamp = datetime.datetime.fromtimestamp(timestamp)

    now = datetime.datetime.now()
    d = {'futurePrefix': '',
         'pastSuffix': '',
         'wrapPrefix': '',
         'wrapSuffix': ''}

    if wrapper != None:
        d['wrapPrefix'], d['wrapSuffix'] = wrapper(timestamp)

    if timestamp < now:
        d['relativeTime'] = timeSince(timestamp, now)
        d['pastSuffix'] = pastSuffix
    elif timestamp > now:
        d['relativeTime'] = timeUntil(timestamp, now)
        d['futurePrefix'] = futurePrefix
    else:
        d['relativeTime'] = "just now"
        d['futurePrefix'] = d['pastSuffix'] = ""

    return "%(wrapPrefix)s%(futurePrefix)s%(relativeTime)s%(pastSuffix)s%(wrapSuffix)s" % d
