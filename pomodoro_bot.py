import irc.bot
import irc.strings
from irc.client import is_channel
from collections import namedtuple
from threading import Thread
import os
import time
import json
import argparse
from inspect import getdoc
from http.server import HTTPServer
from http.server import SimpleHTTPRequestHandler


class PomodoroBot(irc.bot.SingleServerIRCBot):
    """The pomodoro bot sits in a channel and waits for someone to start a pomodoro.
    Once a user expresses interest a five minute wait period for other users to
    register begins. After that the bot loops through a work/break period according
    to a specific time split of minutes worked to minutes spent on break. There
    are three modes: Long, Lazy, and Fast. Long is a 50:10 split, Lazy is a 45:15
    split, and Fast is a 25:5 split. At each break users are expected to register
    themselves as working in the next pomodoro, if nobody registers the loop is
    broken and the bot goes back to its initial state. 

    The bot also keeps a table of all the users which are doing the current 
    pomodoro and what they're working on."""
    def __init__(self, control_nick, nickname, server, ip_address, port=6667):
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self._controller = control_nick
        self._channel_table = {}
        self._ip_address = ip_address
        self._logbook = WorkLogbook()

    def on_privmsg(self, connection, event):
        """Allow the bot controller to message PomodoroBot."""
        if event.source.nick != self._controller:
            print("You cannot send private commands to",
                  connection.get_nickname() + ".")
            return False
        arguments = event.arguments[0].split()
        try:
            if hasattr(self, "do_" + arguments[0]):
                command = getattr(self, "do_" + arguments[0])
                command(connection, event)
        except IndexError:
            pass

    def do_join(self, connection, event):
        """Join a channel specified by the bot controller."""
        arguments = event.arguments[0].split()
        try:
            if is_channel(arguments[1]):
                connection.join(arguments[1])
                self._channel_table[arguments[1].lower()] = Pomodoro(
                    connection,
                    arguments[1].lower())
            else:
                connection.notice(event.source.nick,
                                  "'" + arguments[1] + "' is not a channel.")
        except IndexError:
            usage_msg = "Usage: join <channel> Example: join #test"
            connection.notice(event.source.nick, usage_msg)

    def do_part(self, connection, event):
        """Part a channel specified by the bot controller."""
        arguments = event.arguments[0].split()
        try:
            connection.part(arguments[1])
        except IndexError:
            usage_msg = "Usage: part <channel> Example: part #test"
            connection.notice(event.source.nick, usage_msg)

    def on_pubmsg(self, connection, event):
        """Parse messages sent into a channel PomodoroBot is in for commands.
        If a command is found execute it."""
        arguments = event.arguments[0].split()
        try:
            if hasattr(self, "do_pub_" + arguments[0].strip(".")):
                command = getattr(self, "do_pub_" + arguments[0].strip("."))
            elif (arguments[0].strip(":") == connection.get_nickname()
                  and hasattr(self, "do_pub_" + arguments[1].strip("."))):
                command = getattr(self, "do_pub_" + arguments[1].strip("."))
            else:
                return False
            command(connection, event)
        except IndexError:
            pass

    def do_pub_pomodoro(self, connection, event):
        """Start a pomodoro if one isn't already running, if one is call for a 
        vote to change modes.

        Usage: .pomodoro <mode>, where mode is one of [fast, long, lazy].
        Example: .pomodoro fast"""
        arguments = event.arguments[0].split()
        try:
            mode = arguments[1]
        except IndexError:
            connection.notice(event.source.nick,
                              "Usage: pomodoro <mode>, where mode is one of"
                              + " [fast, long, lazy]." + " Example: .pomodoro fast")
            return False
        session = self._channel_table[event.target]
        if session.session_running() == "break" and not session.votes:
            connection.notice(event.target,
                              event.source.nick + " has requested to change the" +
                              " current setting from " +
                              self._channel_table[event.target].mode + "to " +
                              mode + ".")
            connection.notice(event.target,
                              "If you would like to back this change type "
                              + "'pomodoro " + mode + "' otherwise stay"
                              + " silent or type pomodoro <mode> to vote for a"
                              + " different one.")
            connection.notice(event.target,
                              "(Keep in mind you must be registered for the current"
                              + " pomodoro to vote against it.)")
        elif session.session_running() == "break":
            session.vote(mode, event.source.nick)
            connection.notice(event.source.nick,
                              "Your vote has been cast.")
            votes = session.votes()
            users = session.users()
            for mode in votes:
                if len(votes[mode]) >= len(users):
                    self._channel_table[event.target].pomodoro_stop()
                    self._channel_table[event.target] = Pomodoro(connection,
                                                                 event.target)
                    session = self._channel_table[event.target]
                    session.initialize_pomodoro(mode, delay=0)
                    break
        elif session.session_running() == "work":
            connection.notice(event.source.nick,
                              "You can't vote to change modes while a work"
                              + " session is running.")
            return False
        else:
            session.initialize_pomodoro(mode)
            modes = {"fast":(25,5), "long":(50,10), "lazy":(45,15), "test":(1,1)}
            connection.notice(event.target,
                                    event.source.nick + " has started a new "
                                     + mode + " (" + str(modes[mode][0]) + ":"
                                     + str(modes[mode][1]) + ") " 
                                     + "pomodoro session, if you would like to join in type "
                                     + "'.register <the thing you are working on>'. Example:"
                                     + " .register Programming a Pomodoro IRC Bot.")
            connection.notice(event.target,
                              "The session will start in five minutes.")

    def do_pub_register(self, connection, event):
        """Register to work in the next pomodoro session.

        Usage: .register <thing you're working on>
        Example: .register I'm writing a pomodoro bot."""
        arguments = event.arguments[0].split()
        goal = ""
        for word in arguments[1:]:
            goal = goal + " " + word
        if self._channel_table[event.target].session_running():
            try:
                self._channel_table[event.target].register_nick(event.source.nick,
                                                                goal)
            except IndexError:
                self._channel_table[event.target].register_nick(event.source.nick,
                                                                None)
            self._logbook.log_session(event.source.nick,
                                      self._channel_table[event.target].mode,
                                      goal)
            self._logbook.save_one(event.source.nick)
            connection.notice(event.source.nick,
                              "You have registered for the next session.")
        else:
            connection.notice(event.source.nick,
                              "There is no session running. You can start a new "
                              + "one with the 'pomodoro' command. Example: " +
                              "pomodoro fast.")

    def do_pub_registered(self, connection, event):
        """Send a list of registered users and what they're working on to the
        nick requesting the list.

        Usage: .registered
        Example: .registered"""
        users = self._channel_table[event.target].users()
        if users:
            for user in users:
                connection.notice(event.source.nick,
                                  str(user) + " | " + str(users[user]))
        else:
            connection.notice(event.source.nick,
                              "There are currently no registered users.")

    def do_pub_export(self, connection, event):
        """Export a log of your work sessions to a JSON format.

        Usage: .export
        Example: .export"""
        connection.notice(event.source.nick,
                          self._ip_address + ":12000/" + event.source.nick +
                          ".json")

    def do_pub_help(self, connection, event):
        """Send a help message to the user who requested it.

        Usage: .help, .help <command>
        Example: .help help"""
        arguments = event.arguments[0].split()
        help_msg = ["The PomodoroBot has the following commands:",
                    "pomodoro register registered help",
                    " ",
                    "To get more information about a command, type:",
                    " .help <command name>",
                    "Example:",
                    " .help help"]
        try:
            if hasattr(self, "do_pub_" + arguments[1]):
                doc = getdoc(getattr(self, "do_pub_" + arguments[1]))
                if doc:
                    serialized_doc = doc.split("\n")
                else:
                    serialized_doc = ""
                for line in serialized_doc:
                    connection.notice(event.source.nick,
                                      line)
            else:
                for line in help_msg:
                    connection.notice(event.source.nick,
                                      line)
        except IndexError:
            for line in help_msg:
                connection.notice(event.source.nick,
                                  line)
        
class Pomodoro():
    """Pomodoro channel data structure. Keeps track of who is currently 
    working in the channel, whether a pomodoro is running and in what mode."""
    def __init__(self, connection, channel):
        self._connection = connection
        self._channel = channel
        self._current_users = {}
        self._pomodoro_session = False
        self._votes = {}
        self._modes = {"fast":(25,5), "long":(50,10), "lazy":(45,15), "test":(1,1)}
        self.mode = None
        
    def initialize_pomodoro(self, mode, delay=300):
        """Begin a registration period for a new pomodoro with the mode <mode>, 
        mode is one of:

        Fast: A 25-5 minutes worked/break time split.
        Long: A 50-10 minutes worked/break time split.
        Lazy: A 45/15 minutes worked/break time split."""
        self.mode = mode.lower()
        self._pomodoro_session = "work"
        self._votes = {}
        self._connection.execute_delayed(delay, self.pomodoro_start, (self.mode,))
        
    def pomodoro_start(self, mode):
        """Start a pomodoro session with the mode <mode>, mode is one of:

        Fast: A 25-5 minutes worked/break time split.
        Long: A 50-10 minutes worked/break time split.
        Lazy: A 45/15 minutes worked/break time split."""
        now = time.gmtime()
        work_period = self._modes[mode][0]
        now_to_end = (now.tm_min + work_period)
        overflow = True if now_to_end % 60 < now.tm_min else False
        start_above_ten = True if now.tm_min >= 10 else False
        end_above_ten = True if now_to_end % 60 >= 10 else False
        self._votes = {}
        start = ":" + str(now.tm_min) if start_above_ten else ":0" + str(now.tm_min)
        if overflow and end_above_ten:
            end = ":" + str(now_to_end % 60) + " of the next hour."
        elif overflow:
            end = ":0" + str(now_to_end % 60) + " of the next hour."
        elif end_above_ten:
            end = ":" + str(now_to_end) + "."
        else:
            end = ":0" + str(now_to_end) + "."
        self._connection.notice(self._channel,
                                "Pomodoro starts at " + start + " and ends at "
                                + end)
        self._connection.execute_delayed(work_period * 60,
                                         self.pomodoro_break,
                                         (mode,))

    def pomodoro_break(self, mode):
        """Take a break from working of the length specified by the mode."""
        break_period = str(self._modes[mode][1])
        self._connection.notice(self._channel,
                                break_period + " minute break.")
        self._connection.notice(self._channel,
                                "Please register for the next pomodoro sometime"
                                + " between now and the next " + break_period
                                + " minutes.")
        self._current_users.clear()
        self._pomodoro_session = "break"
        
        def callback(users):
            """Registration callback closure that either iterates the pomodoro
            loop or cleans up if nobody registers."""
            if users:
                self.pomodoro_start(mode)
            else:
                self._pomodoro_session = False
            
        self._connection.execute_delayed(int(break_period) * 60,
                                         callback,
                                         (self._current_users,))

    def pomodoro_stop(self):
        """Set the current users to none so that the pomodoro stops after the
        current break."""
        self._current_users = {}

    def register_nick(self, nickname, goal):
        """Register a nickname for the current Pomodoro Session. Goal is the thing
        that a user is working on for this session."""
        if self._pomodoro_session:
            if goal:
                self._current_users[nickname] = goal
            else:
                self._current_users[nickname] = ""
        else:
            raise RegistrationError(nickname)

    def vote(self, mode, nickname):
        """Vote to change the mode to a different mode."""
        self._votes[mode].add(nickname)
        
    def votes(self):
        """Return the vote tallies for changing the mode."""
        if self._votes:
            return self._votes
        else:
            return False

    def users(self):
        """Return the current users."""
        return self._current_users

    def session_running(self):
        """Return whether or not there is currently a session running.

        This function can return one of three values, False, in which case there
        is no session running at all, "work" in which case a work session is 
        running, and "break" which means that a session is running but it is
        currently in the break period."""
        return self._pomodoro_session

    class RegistrationError(Exception):
        """Error raised when a nickname is registered when a pomodoro is not in
        session."""
        def __init__(self, nickname):
            self._nickname = nickname

        def __str__(self):
            return repr(self._nickname)
        
class WorkLogbook():
    """Data structure representing the work logbook for pomodoro sessions.

    Each user of the bot's sessions are stored in a JSON log file which is 
    updated every time they register for a session. For each session the datetime,
    type of pomodoro, and goal registered with are recorded."""
    def __init__(self):
        self._session_tuple = namedtuple("Session", ['datetime', 'type', 'goal'])
        self._logbook = {}
        self.load()

    def log_session(self, nick, type, goal):
        """Log a work session for a given nick.

        For each session the datetime, type of pomodoro, and goal registered 
        with are recorded."""
        datetime = self._iso_8601()
        if nick.lower() in self._logbook:
            self._logbook[nick.lower()].append(self._session_tuple(datetime,
                                                                   type, goal))
        else:
            self._logbook[nick.lower()] = []
            self._logbook[nick.lower()].append(self._session_tuple(datetime,
                                                                   type,goal))
        return True

    def _iso_8601(self):
        """Return an ISO 8601 datetime in UTC."""
        return time.strftime("%Y-%m-%dT%H-%M-%SZ", time.gmtime())

    def save_all(self):
        """Save the WorkLogbook to disk.

        The WorkLogbook is saved to disk in a JSON format. Each nick's log is
        stored in a seperate file."""
        for nick in self._logbook:
            self.save_one(nick)
        return True

    def save_one(self, nick):
        """Save the WorkLogbook entries for a given nick to disk."""
        outfile = open(nick + ".json", "w")
        json.dump(self._logbook[nick], outfile)
        outfile.close()
        return True

    def load(self):
        """Load the WorkLogbook from disk.

        The Worklogbook is saved to disk in a JSON format. Each nick's log is 
        stored in a seperate file."""
        filenames = os.listdir()
        for filename in filenames:
            nick = filename.split(".")[0]
            infile = open(filename)
            sessions = json.load(infile)
            infile.close()
            named_tuples = []
            for session in sessions:
                named_tuples.append(
                    self._session_tuple(session[0],
                                        session[1],
                                        session[2]))
            self._logbook[nick] = named_tuples
        return True
    
parser = argparse.ArgumentParser()
parser.add_argument("controller_nick",
                    help="The nickname of the user that controls the bot.")
parser.add_argument("bot_nick",
                    help="The nickname of the bot.")
parser.add_argument("server_address",
                    help="The address of the server to connect to.")
parser.add_argument("ip_address",
                    help="The IP address of the server running the bot.")
parser.add_argument("-p", "--port", type=int, default=6667)
arguments = parser.parse_args()

try:
    os.chdir("work_logs/")
except FileNotFoundError:
    os.mkdir("work_logs/")

bot = PomodoroBot(arguments.controller_nick,
                  arguments.bot_nick,
                  arguments.server_address,
                  arguments.ip_address,
                  arguments.port)

bot_thread = Thread(target=bot.start,
                    daemon=False)
bot_thread.start()
    
httpd = HTTPServer(('', 12000), SimpleHTTPRequestHandler)
httpd_thread = Thread(target=httpd.serve_forever,
                      daemon=False)
httpd_thread.start()
