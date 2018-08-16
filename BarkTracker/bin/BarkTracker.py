#!/usr/bin/python

import numpy
import soundbox
import pyaudio
import analyse
import smtplib  # for emailing people
import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.header import Header
from email.utils import formataddr
from multiprocessing import Process

import signal
import sys

def signal_handler(sig, frame):
        print("Thanks for using bark tracker! Here's your summary:")
        summary = {session[0]: session[1]-session[0] for session in bark_sessions}

        total_duration = sum(summary.values(),datetime.timedelta(0))
        print("Today we saw {0} barksessions, for a total barktime of {1}.".format(len(bark_sessions), timedelta_format(total_duration)))

        print("details:")
        for start, duration in summary.items():
            print("{0}:  session of  {1}".format(str(start.time()), timedelta_format(duration)))
        sys.exit(0)


def timedelta_format(time_delta):
    seconds = int(time_delta.total_seconds())
    periods = [
        ('year',        60*60*24*365),
        ('month',       60*60*24*30),
        ('day',         60*60*24),
        ('hour',        60*60),
        ('minute',      60),
        ('second',      1)
    ]

    strings=[]
    for period_name, period_seconds in periods:
        if seconds > period_seconds:
            period_value , seconds = divmod(seconds, period_seconds)
            has_s = 's' if period_value > 1 else ''
            strings.append("%s %s%s" % (period_value, period_name, has_s))

    return " ".join(strings)



debug = False

# The following variables should be customized by the user

dog_name = "" # name of the barker

gmailUser = ""   # sender e-mail
gmailPassword = ""     # sender password
from_name = "" # name of the sender of the e-mail
from_email = "" # email of the sender
recipients = [] # array of email addresses to send the message to
streamChunk = 1024               # chunk used for the audio input stream
sampleRate = 48000               # the sample rate of the user's mic
input_device_index = 0           # device index for the user's mic
numChannels = 2                  # number of channels for the user's mic
audio_format = pyaudio.paInt16   # the audio format
ambient_db = -4                  # the ambience noise level in db

stricter_timer = 40             # be stricter if re-bark within this # of sec
reward_timer = 15               # reward a silence after this # of seconds
bark_alert = False              # True when barking is ongoing

# private variables
if debug:
    ambient_db = -18

pyaud = pyaudio.PyAudio()

bark_sessions = []

last_bark = datetime.datetime.min
last_email = datetime.datetime.min

session_email_sent = False


# open input stream
stream = pyaud.open(
    format=audio_format,
    channels=numChannels,
    rate=sampleRate,
    input_device_index=input_device_index,
    input=True)


def send_email(subject, text):
    message = MIMEMultipart('alternative')
    message['Subject'] = subject    # The subject of the email
    message['From'] = formataddr((str(Header(from_name, 'utf-8')), from_email))  # Where its being sent from (chosen by user)
    message['Reply-To'] = formataddr((str(Header(from_name, 'utf-8')), from_email))  # Where its being sent from (chosen by user)
    message['To'] = ", ".join(recipients)      # Who gets the e-mail
    mimeText = MIMEText(text, 'plain')
    message.attach(mimeText)

    mailServer = smtplib.SMTP('smtp.gmail.com', 587)
    mailServer.ehlo()
    mailServer.starttls()
    mailServer.ehlo()
    mailServer.login(gmailUser, gmailPassword)  # logs into email address (entered above) using password (also entered above)   

    mailServer.sendmail(from_email, recipients, message.as_string())          #send the email to the recipient
    mailServer.quit()  # Stop doing things with the mail server


def send_email_async(subject, text):
    if debug:
        print("mail:")
        print("subject: %s" % subject)
        print("content: %s" % text)
        return

    p = Process(target=send_email, args=(subject, text,))
    p.start()           # actually start the process


print("Starting BarkTracker")

# listen for end of program
signal.signal(signal.SIGINT, signal_handler)

while True:
    stream = pyaud.open(
        format=audio_format,
        channels=numChannels,
        rate=sampleRate,
        input_device_index=input_device_index,
        input=True)    

    rawsamps = stream.read(streamChunk)
    samps = numpy.fromstring(rawsamps, dtype=numpy.int16)
    stream.close()

    current_loudness = analyse.loudness(samps)
    currentTime = datetime.datetime.now()

    timeDifference = currentTime - last_bark

    if current_loudness <= ambient_db:
        if bark_alert and timeDifference > datetime.timedelta(seconds=reward_timer):
            print("{0}: Bark stopped. Calm again.".format(currentTime.strftime("%H:%M:%S")))
            if session_email_sent:
                send_email_async("Bark alert lifted.", "All is calm again.")
            bark_sessions[-1][1] = currentTime - datetime.timedelta(seconds=reward_timer)
            session_email_sent = False

            soundbox.reward()
            bark_alert = False
        continue

    bark_alert = True
    
    if(timeDifference > datetime.timedelta(seconds=stricter_timer)):
        print("{0}: New bark detected ({1:.2f} dB). Trying the short messages."
              .format(currentTime.strftime("%H:%M:%S"),current_loudness))     

        text = dog_name + " is being noisy at " + \
            currentTime.strftime("%Y-%m-%d %H:%M:%S") + \
            "\n\nHe is producing a volume of " + \
            str(current_loudness) + "dB."

        bark_sessions.append([currentTime, -1])
        # send_email_async("New bark detected", text)
        soundbox.warn_short()

    else:

        text = dog_name + " is being noisy at " + \
            currentTime.strftime("%H:%M:%S") + \
            "\n\nHe is producing a volume of " + \
            str(current_loudness) + "dB."

        timeSinceLastEmail = currentTime - last_email
        timeSinceStartSession = currentTime - bark_sessions[-1][0]


        if not session_email_sent and timeSinceStartSession > datetime.timedelta(seconds=20):
            print("{0}: More then 20 seconds, sending first warning ({1:.2f} dB)."
              .format(currentTime.strftime("%H:%M:%S"),current_loudness))
            send_email_async("New persistent bark for longer than 20 seconds.", text)
            last_email = currentTime
            session_email_sent = True

        elif session_email_sent and (timeSinceLastEmail > datetime.timedelta(seconds=20)) :
            print("{0}: consecutive warning. ({1:.2f} dB). Re-sending e-mail."
              .format(currentTime.strftime("%H:%M:%S"),current_loudness))

            send_email_async("Still going, persistent bark for longer than 20 seconds.", text)
            last_email = currentTime
            session_email_sent = True
        else:
            print("{0}: Persistent bark detected ({1:.2f} dB). Trying the long messages."
                .format(currentTime.strftime("%H:%M:%S"),current_loudness))

        soundbox.warn_long()

    last_bark = datetime.datetime.now()
 