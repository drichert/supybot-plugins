###
# Copyright (c) 2005, Jeremiah Fincher
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
###

import os
import csv

import supybot.conf as conf
import supybot.utils as utils
from supybot.utils.file import AtomicFile as transactionalFile
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircmsgs as ircmsgs
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks

### adapted from django.utils.text ###
import re
# modified to include ++ or -- at end of phrases
smart_split_re = re.compile(r'("(?:[^"\\]*(?:\\.[^"\\]*)*)"|\'(?:[^\'\\]*(?:\\.[^\'\\]*)*)\'|[^\s]+)(?:\+\+|\-\-|\+\-|\-\+)')
def smart_split(text):
    """
    Generator that splits a string by spaces, leaving quoted phrases together.
    Supports both single and double quotes, and supports escaping quotes with
    backslashes. In the output, strings will keep their initial and trailing
    quote marks.

    >>> list(smart_split('This is "a person\'s" test.'))
    ['This', 'is', '"a person\'s"', 'test.']
    """
    #text = force_unicode(text)
    for bit in smart_split_re.finditer(text):
        bit = bit.group(0)
        if bit[0] == '"' and bit[-3] == '"':
            yield '"' + bit[1:-3].replace('\\"', '"').replace('\\\\', '\\') + '"' + bit[-2:]
        elif bit[0] == "'" and bit[-3] == "'":
            yield "'" + bit[1:-3].replace("\\'", "'").replace("\\\\", "\\") + "'" + bit[-2:]
        else:
            yield bit

class SqliteKarmaDB(object):
    def __init__(self, filename):
        self.dbs = ircutils.IrcDict()
        self.filename = filename

    def close(self):
        for db in self.dbs.itervalues():
            db.close()

    def _getDb(self, channel):
        try:
            import sqlite
        except ImportError:
            raise callbacks.Error, 'You need to have PySQLite installed to ' \
                                   'use Karma.  Download it at ' \
                                   '<http://pysqlite.org/>'
        filename = plugins.makeChannelFilename(self.filename, channel)
        if filename in self.dbs:
            return self.dbs[filename]
        if os.path.exists(filename):
            self.dbs[filename] = sqlite.connect(filename)
            return self.dbs[filename]
        db = sqlite.connect(filename)
        self.dbs[filename] = db
        cursor = db.cursor()
        cursor.execute("""CREATE TABLE karma (
                          id INTEGER PRIMARY KEY,
                          name TEXT,
                          normalized TEXT UNIQUE ON CONFLICT IGNORE,
                          added INTEGER,
                          subtracted INTEGER
                          )""")
        db.commit()
        def p(s1, s2):
            return int(ircutils.nickEqual(s1, s2))
        db.create_function('nickeq', 2, p)
        return db

    def get(self, channel, thing):
        db = self._getDb(channel)
        thing = thing.lower()
        cursor = db.cursor()
        cursor.execute("""SELECT added, subtracted FROM karma
                          WHERE normalized=%s""", thing)
        if cursor.rowcount == 0:
            return None
        else:
            return map(int, cursor.fetchone())

    def gets(self, channel, things):
        db = self._getDb(channel)
        cursor = db.cursor()
        normalizedThings = dict(zip(map(str.lower, things), things))
        criteria = ' OR '.join(['normalized=%s'] * len(normalizedThings))
        sql = """SELECT name, added-subtracted FROM karma
                 WHERE %s ORDER BY added-subtracted DESC""" % criteria
        cursor.execute(sql, *normalizedThings)
        L = [(name, int(karma)) for (name, karma) in cursor.fetchall()]
        for (name, _) in L:
            del normalizedThings[name.lower()]
        neutrals = normalizedThings.values()
        neutrals.sort()
        return (L, neutrals)

    def top(self, channel, limit):
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT name, added-subtracted FROM karma
                          ORDER BY added-subtracted DESC LIMIT %s""", limit)
        return [(t[0], int(t[1])) for t in cursor.fetchall()]

    def bottom(self, channel, limit):
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT name, added-subtracted FROM karma
                          ORDER BY added-subtracted ASC LIMIT %s""", limit)
        return [(t[0], int(t[1])) for t in cursor.fetchall()]

    def rank(self, channel, thing):
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT added-subtracted FROM karma
                          WHERE name=%s""", thing)
        if cursor.rowcount == 0:
            return None
        karma = int(cursor.fetchone()[0])
        cursor.execute("""SELECT COUNT(*) FROM karma
                          WHERE added-subtracted > %s""", karma)
        rank = int(cursor.fetchone()[0])
        return rank+1

    def size(self, channel):
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT COUNT(*) FROM karma""")
        return int(cursor.fetchone()[0])

    def increment(self, channel, name):
        db = self._getDb(channel)
        cursor = db.cursor()
        normalized = name.lower()
        cursor.execute("""INSERT INTO karma VALUES (NULL, %s, %s, 0, 0)""",
                       name, normalized)
        cursor.execute("""UPDATE karma SET added=added+1
                          WHERE normalized=%s""", normalized)
        db.commit()

    def decrement(self, channel, name):
        db = self._getDb(channel)
        cursor = db.cursor()
        normalized = name.lower()
        cursor.execute("""INSERT INTO karma VALUES (NULL, %s, %s, 0, 0)""",
                       name, normalized)
        cursor.execute("""UPDATE karma SET subtracted=subtracted+1
                          WHERE normalized=%s""", normalized)
        db.commit()

    def most(self, channel, kind, limit):
        if kind == 'increased':
            orderby = 'added'
        elif kind == 'decreased':
            orderby = 'subtracted'
        elif kind == 'active':
            orderby = 'added+subtracted'
        else:
            raise ValueError, 'invalid kind'
        sql = """SELECT name, %s FROM karma ORDER BY %s DESC LIMIT %s""" % \
              (orderby, orderby, limit)
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute(sql)
        return [(name, int(i)) for (name, i) in cursor.fetchall()]

    def clear(self, channel, name):
        db = self._getDb(channel)
        cursor = db.cursor()
        normalized = name.lower()
        cursor.execute("""UPDATE karma SET subtracted=0, added=0
                          WHERE normalized=%s""", normalized)
        db.commit()

    def dump(self, channel, filename):
        filename = conf.supybot.directories.data.dirize(filename)
        fd = transactionalFile(filename)
        out = csv.writer(fd)
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""SELECT name, added, subtracted FROM karma""")
        for (name, added, subtracted) in cursor.fetchall():
            out.writerow([name, added, subtracted])
        fd.close()

    def load(self, channel, filename):
        filename = conf.supybot.directories.data.dirize(filename)
        fd = file(filename)
        reader = csv.reader(fd)
        db = self._getDb(channel)
        cursor = db.cursor()
        cursor.execute("""DELETE FROM karma""")
        for (name, added, subtracted) in reader:
            normalized = name.lower()
            cursor.execute("""INSERT INTO karma
                              VALUES (NULL, %s, %s, %s, %s)""",
                           name, normalized, added, subtracted)
        db.commit()
        fd.close()

KarmaDB = plugins.DB('Karma',
                     {'sqlite': SqliteKarmaDB})

class Karma(callbacks.Plugin):
    callBefore = ('Factoids', 'MoobotFactoids', 'Infobot')
    def __init__(self, irc):
        self.__parent = super(Karma, self)
        self.__parent.__init__(irc)
        self.db = KarmaDB()

    def die(self):
        self.__parent.die()
        self.db.close()

    def _normalizeThing(self, thing):
        assert thing
        if thing[0] == '(' and thing[-1] == ')':
            thing = thing[1:-1]
        return thing

    def _respond(self, irc, channel):
        if self.registryValue('response', channel):
            irc.replySuccess()
        else:
            irc.noReply()

    def _doKarma(self, irc, channel, thing):
        assert thing[-2:] in ('++', '--', '+-', '-+')
        assert thing[:-2] not in ('<', '-', '<!')
        thing_end = thing[-2:]
        thing = thing[:-2].strip('\'"')
        if thing:
            if ircutils.strEqual(thing, irc.msg.nick) and \
                    not self.registryValue('allowSelfRating', channel):
                irc.error('You\'re not allowed to adjust your own karma.')
            else:
                if thing_end == '++':
                    self.db.increment(channel, self._normalizeThing(thing))
                elif thing_end == '--':
                    self.db.decrement(channel, self._normalizeThing(thing))
                else:
                    self.db.increment(channel, self._normalizeThing(thing))
                    self.db.decrement(channel, self._normalizeThing(thing))                    
                self._respond(irc, channel)
        
#        if thing.endswith('++'):
#            thing = thing[:-2]
#            thing = thing.strip('\'"')
#            if ircutils.strEqual(thing, irc.msg.nick) and \
#               not self.registryValue('allowSelfRating', channel):
#                irc.error('You\'re not allowed to adjust your own karma.')
#            elif thing:
#                self.db.increment(channel, self._normalizeThing(thing))
#                self._respond(irc, channel)
#        else:
#            thing = thing[:-2]
#            thing = thing.strip('\'"')
#            if ircutils.strEqual(thing, irc.msg.nick) and \
#               not self.registryValue('allowSelfRating', channel):
#                irc.error('You\'re not allowed to adjust your own karma.')
#            elif thing:
#                self.db.decrement(channel, self._normalizeThing(thing))
#                self._respond(irc, channel)

    def invalidCommand(self, irc, msg, tokens):
        channel = msg.args[0]
        if not irc.isChannel(channel):
            return
#        if tokens[-1][-2:] in ('++', '--'):
#            thing = ' '.join(tokens)
#            self._doKarma(irc, channel, thing)
        # let's be a little smarter about grabbing things
        # <bob> thanks.  john++  you're awesome
        # should only increment 'john'
        for token in tokens:
            self._doKarma(irc, channel, thing)

    def doPrivmsg(self, irc, msg):
        # We don't handle this if we've been addressed because invalidCommand
        # will handle it for us.  This prevents us from accessing the db twice
        # and therefore crashing.
        if not (msg.addressed or msg.repliedTo):
            channel = msg.args[0]
            if irc.isChannel(channel) and \
               self.registryValue('allowUnaddressedKarma', channel):
                irc = callbacks.SimpleProxy(irc, msg)
#                thing = msg.args[1].rstrip()
#                if thing[-2:] in ('++', '--'):
#                    self._doKarma(irc, channel, thing)
                # same here as above in invalidCommand
                #for token in msg.args[1].split():
                for token in smart_split(msg.args[1]):
                    self._doKarma(irc, channel, token)

    def karma(self, irc, msg, args, channel, things):
        """[<channel>] [<thing> ...]

        Returns the karma of <text>.  If <thing> is not given, returns the top
        three and bottom three karmas.  If one <thing> is given, returns the
        details of its karma; if more than one <thing> is given, returns the
        total karma of each of the things. <channel> is only necessary if
        the message isn't sent on the channel itself.
        """
        name = ' '.join(things)
#        if len(things) == 1:
#            name = things[0]
        if name:
            t = self.db.get(channel, name)
            if t is None:
                irc.reply(format('%s has neutral karma.', name))
            else:
                (added, subtracted) = t
                total = added - subtracted
                if self.registryValue('simpleOutput', channel):
                    s = format('%s: %i', name, total)
                else:
                    s = format('Karma for %q has been increased %n and '
                               'decreased %n for a total karma of %s.',
                               name, (added, 'time'), (subtracted, 'time'),
                               total)
                irc.reply(s)
#        elif len(things) > 1:
#            (L, neutrals) = self.db.gets(channel, things)
#            if L:
#                s = format('%L', [format('%s: %i', *t) for t in L])
#                if neutrals:
#                    neutral = format('.  %L %h neutral karma',
#                                     neutrals, len(neutrals))
#                    s += neutral
#                irc.reply(s + '.')
#            else:
#                irc.reply('I didn\'t know the karma for any of those things.')
        else: # No name was given.  Return the top/bottom N karmas.
            limit = self.registryValue('rankingDisplay', channel)
            top = self.db.top(channel, limit)
            highest = [format('%q (%s)', s, t)
                       for (s, t) in self.db.top(channel, limit)]
            lowest = [format('%q (%s)', s, t)
                      for (s, t) in self.db.bottom(channel, limit)]
            if not (highest and lowest):
                irc.error('I have no karma for this channel.')
                return
            rank = self.db.rank(channel, msg.nick)
            if rank is not None:
                total = self.db.size(channel)
                rankS = format('  You (%s) are ranked %i out of %i.',
                               msg.nick, rank, total)
            else:
                rankS = ''
            s = format('Highest karma: %L.  Lowest karma: %L.%s',
                       highest, lowest, rankS)
            irc.reply(s)
    karma = wrap(karma, ['channel', any('something')])

    _mostAbbrev = utils.abbrev(['increased', 'decreased', 'active'])
    def most(self, irc, msg, args, channel, kind):
        """[<channel>] {increased,decreased,active}

        Returns the most increased, the most decreased, or the most active
        (the sum of increased and decreased) karma things.  <channel> is only
        necessary if the message isn't sent in the channel itself.
        """
        L = self.db.most(channel, kind,
                         self.registryValue('mostDisplay', channel))
        if L:
            L = [format('%q: %i', name, i) for (name, i) in L]
            irc.reply(format('%L', L))
        else:
            irc.error('I have no karma for this channel.')
    most = wrap(most, ['channel',
                       ('literal', ['increased', 'decreased', 'active'])])

    def clear(self, irc, msg, args, channel, name):
        """[<channel>] <name>

        Resets the karma of <name> to 0.
        """
        self.db.clear(channel, name)
        irc.replySuccess()
    clear = wrap(clear, [('checkChannelCapability', 'op'), 'text'])

    def getName(self, nick, msg, match):
        addressed = callbacks.addressed(nick, msg)
        name = callbacks.addressed(nick,
                   ircmsgs.IrcMsg(prefix='',
                                  args=(msg.args[0], match.group(1)),
                                  msg=msg))
        if not name:
            name = match.group(1)
        if not addressed:
            if not self.registryValue('allowUnaddressedKarma'):
                return ''
            if not msg.args[1].startswith(match.group(1)):
                return ''
            name = match.group(1)
        elif addressed:
            if not addressed.startswith(name):
                return ''
        name = name.strip('()')
        return name

    def dump(self, irc, msg, args, channel, filename):
        """[<channel>] <filename>

        Dumps the Karma database for <channel> to <filename> in the bot's
        data directory.  <channel> is only necessary if the message isn't sent
        in the channel itself.
        """
        self.db.dump(channel, filename)
        irc.replySuccess()
    dump = wrap(dump, [('checkCapability', 'owner'), 'channeldb', 'filename'])

    def load(self, irc, msg, args, channel, filename):
        """[<channel>] <filename>

        Loads the Karma database for <channel> from <filename> in the bot's
        data directory.  <channel> is only necessary if the message isn't sent
        in the channel itself.
        """
        self.db.load(channel, filename)
        irc.replySuccess()
    load = wrap(load, [('checkCapability', 'owner'), 'channeldb', 'filename'])

    def karmawar(self, irc, msg, args, nick, dice):
        """<nick> [<dice>]

        Initiate a karma battle with another user
        """
        if not dice:
            dice = 3
        attack_rolls = ["%d" % self.rng.randrange(1, 6) for x in range(3)]
        irc.reply("%s rolls %d dice: %s" % (nick, dice, commaAndify(attack_rolls)))
        def_rols = ["%d" % self.rng.randrange(1,6) for x in range(2)]
        irc.reply("%s rolls 2 dice: %s" % (nick, commaAndify(def_rolls)))
        
    karmawar = wrap(karmawar, ['nickInChannel', optional('nonNegativeInt')])

Class = Karma

# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
