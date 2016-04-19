# Event System #

## What Is The Event System And What Should It Do? ##

The event system logs all input to the program and allows it to be replayed to 
diagnose and fix errors. (See: https://news.ycombinator.com/item?id=11384558)

The recording should consist of timestamped typed messages and their contents.
The timestamp is a Unix Timestamp and the type of the message is based on the
type of event which the bot received the message as. 

The format is as follows:

timestamp, type, author, contents

Each message should be separated with a newline.

When given the --replay option, the pomodoro-bot will ignore the previous 
parameters given and simulate being ran with the input recording. It will 
directly change the state of the pomodoro book to represent work/break periods
without actually waiting for the work and break times. (Which could obviously
take a very long time.)

