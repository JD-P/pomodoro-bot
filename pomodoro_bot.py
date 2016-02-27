import irc.bot
import irc.strings
from irc.client import is_channel
from collections import namedtuple
import time
import argparse

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
    def __init__(self, control_nick, nickname, server, port=6667):
        irc.bot.SingleServerIRCBot.__init__(self, [(server, port)], nickname, nickname)
        self._controller = control_nick
        self._channel_table = {}

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
                self._channel_table[arguments[1]] = Pomodoro(connection,
                                                             arguments[1])
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

        Usage: pomodoro <mode>, where mode is one of [fast, long, lazy].
        Example: pomodoro fast"""
        arguments = event.arguments[0].split()
        try:
            mode = arguments[1]
        except IndexError:
            connection.notice(event.source.nick,
                              "Usage: pomodoro <mode>, where mode is one of"
                              + " [fast, long, lazy]." + " Example: pomodoro fast")
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
        """Register to work in the next pomodoro session."""
        arguments = event.arguments[0].split()
        if self._channel_table[event.target].session_running():
            try:
                self._channel_table[event.target].register_nick(event.source.nick,
                                                                arguments[1])
            except IndexError:
                self._channel_table[event.target].register_nick(event.source.nick,
                                                                None)
            connection.notice(event.source.nick,
                              "You have registered for the next session.")
        else:
            connection.notice(event.source.nick,
                              "There is no session running. You can start a new "
                              + "one with the 'pomodoro' command. Example: " +
                              "pomodoro fast.")
        
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

    def initialize_pomodoro(self, mode, delay=300):
        """Begin a registration period for a new pomodoro with the mode <mode>, 
        mode is one of:

        Fast: A 25-5 minutes worked/break time split.
        Long: A 50-10 minutes worked/break time split.
        Lazy: A 45/15 minutes worked/break time split."""
        mode = mode.lower()
        self._pomodoro_session = "work"
        self._votes = {}
        self._connection.execute_delayed(delay, self.pomodoro_start, (mode,))
        
    def pomodoro_start(self, mode):
        """Start a pomodoro session with the mode <mode>, mode is one of:

        Fast: A 25-5 minutes worked/break time split.
        Long: A 50-10 minutes worked/break time split.
        Lazy: A 45/15 minutes worked/break time split."""
        now = time.gmtime()
        work_period = self._modes[mode][0]
        now_to_end = (now.tm_min + work_period)
        overflow = True if now_to_end % 60 < now.tm_min else False
        start_above_ten = True if now.tm_min < 10 else False
        end_above_ten = True if now_to_end % 60 > 10 else False
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
                                break_period + "minute break.")
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
        
        
parser = argparse.ArgumentParser()
parser.add_argument("controller_nick")
parser.add_argument("bot_nick")
parser.add_argument("server_address")
parser.add_argument("-p", "--port", default=6667)
arguments = parser.parse_args()

bot = PomodoroBot(arguments.controller_nick,
                  arguments.bot_nick,
                  arguments.server_address,
                  arguments.port)
bot.start()
