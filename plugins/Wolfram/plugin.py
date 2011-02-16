from supybot.commands import *
import supybot.callbacks as callbacks

import urllib
from xml.etree import ElementTree

app_id = '62VUEW-H6XTUTU32R'

class Wolfram(callbacks.Privmsg):

    def alpha(self, irc, msg, args, question):
        """Ask Mr. Wolfram a question, get an "answer"...maybe?
        """
        u = "http://api.wolframalpha.com/v2/query?"
        q = urllib.urlencode({'input': question, 'appid': app_id})
        xml = urllib.urlopen(u + q).read()
        tree = ElementTree.fromstring(xml)

        answer = None
        for pod in tree.findall('.//pod'):
            title = pod.attrib['title']
            irc.reply(title)
            if title != 'Result':
                continue
            plaintext = pod.find('.//plaintext')
            if plaintext.text:
                answer = plaintext.text
            break

        if answer:
            irc.reply(answer.encode("utf-8"))
        else:
            irc.reply("huh, I dunno, sorry!")

    alpha = wrap(alpha, ['text'])


Class = Wolfram