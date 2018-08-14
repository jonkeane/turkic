"""
A lightweight server framework.

To use this module, import the 'application' function, which will dispatch
requests based on handlers. To define a handler, decorate a function with
the 'handler' decorator. Example:

>>> from turkic.server import handler, application
... @handler
... def spam():
...     return True
"""

import json
from turkic.database import session
from turkic.models import EventLog
from sqlalchemy import and_

handlers = {}

import logging
logger = logging.getLogger("turkic.server")

try:
    from wsgilog import log as wsgilog
except ImportError:
    def wsgilog(*args, **kwargs):
        return lambda x: x

def handler(type = "json", jsonify = None, post = False, environ = False):
    """
    Decorator to bind a function as a handler in the server software.

    type        specifies the Content-Type header
    jsonify     dumps data in json format if true
    environ     gives handler full control of environ if ture
    """
    type = type.lower()
    if type == "json" and jsonify is None:
        jsonify = True
        type == "text/json"
    def decorator(func):
        handlers[func.__name__] = (func, type, jsonify, post, environ)
        return func
    return decorator

@wsgilog(tostream=True)
def application(environ, start_response):
    """
    Dispatches the server application through a handler. Specify a handler
    with the 'handler' decorator.
    """
    path = environ.get("PATH_INFO", "").lstrip("/").split("/")

    logger.info("Got HTTP request: {0}".format("/".join(path)))

    try:
        action = path[0]
    except IndexError:
        raise Error404("Missing action.")

    try:
        handler, type, jsonify, post, passenviron = handlers[action]
    except KeyError:
        start_response("200 OK", [("Content-Type", "text/plain")])
        return ["Error 404\n", "Action {0} undefined.".format(action)]

    try:
        args = path[1:]
        if post:
            postdata = environ["wsgi.input"].read()
            if post == "json":
                args.append(json.loads(postdata))
            else:
                args.append(postdata)
        if passenviron:
            args.append(environ)
        try:
            response = handler(*args)
        finally:
            session.remove()
    except Error404 as e:
        start_response("404 Not Found", [("Content-Type", "text/plain")])
        return ["Error 404\n", str(e)]
    else:
        start_response("200 OK", [("Content-Type", type)])
        if jsonify:
            logger.debug("Response to " + str("/".join(path)) + ": " +
                str(response)[0:100])
            return [json.dumps(response)]
        else:
            return response

class Error404(Exception):
    """
    Exception indicating that an 404 error occured.
    """
    def __init__(self, message):
        Exception.__init__(self, message)




import models
from datetime import datetime

def get_open_assignments(hitid, assignmentid = None, workerid = None):
    """
    Helper function to get assignments
    """
    query = session.query(models.Assignment)
    query = query.join(models.HIT)
    query = query.filter(models.HIT.hitid == hitid)
    # add error handling in the case where there is less than one selected?

    if workerid is not None:
        query.filter(models.Assignment.workerid == workerid).first()

    return query.filter(models.Assignment.assignmentid == assignmentid).first()

def getjobstats(hitid, workerid):
    """
    Returns the worker status as a dictionary for the server.
    """
    status = {}

    hit = get_open_assignments(hitid)
    status["reward"] = hit.group.cost
    status["donationcode"] = hit.group.donation

    bonuses = [x.description() for x in hit.group.schedules]
    bonuses = [x for x in bonuses if x]
    status["bonuses"] = bonuses

    worker = session.query(models.Worker)
    worker = worker.filter(models.Worker.id == workerid)

    try:
        worker = worker.one()
    except:
        status["newuser"] = True
        status["numaccepted"] = 0
        status["numrejected"] = 0
        status["numsubmitted"] = 0
        status["verified"] = False
        status["blocked"] = False
    else:
        status["newuser"] = False
        status["numaccepted"] = worker.numacceptances
        status["numrejected"] = worker.numrejections
        status["numsubmitted"] = worker.numsubmitted
        status["verified"] = worker.verified
        status["blocked"] = worker.blocked
    return status

def savejobstats(hitid, assignmentid, timeaccepted, timecompleted, environ):
    """
    Saves statistics for a job.
    """
    # grab a hit from all HITs where the hitid matches the current hitid and
    # there is not already an assignmentid.
    assignment = get_open_assignments(hitid, assignmentid)

    assignment.timeaccepted = datetime.fromtimestamp(int(timeaccepted) / 1000)
    assignment.timecompleted = datetime.fromtimestamp(int(timecompleted) / 1000)
    assignment.timeonserver = datetime.now()

    assignment.ipaddress = environ.get("HTTP_X_FORWARDED_FOR", None)
    assignment.ipaddress = environ.get("REMOTE_ADDR", assignment.ipaddress)
    
    print("Saving job stats: ip {0}; assignmentid {1}; hitid {2}".format(assignment.ipaddress, assignmentid, hitid))

    session.add(assignment)
    session.commit()

def savedonationstatus(hitid, donation):
    """
    Saves the donation statistics
    """
    hit = get_open_assignments(hitid)
    hit.opt2donate = float(donation)
    hit.opt2donate = min(max(hit.opt2donate, 0), 1)

    session.add(hit)
    session.commit()

def markcomplete(hitid, assignmentid, workerid):
    """
    Marks a job as complete. Usually this is called right before the
    MTurk form is submitted.
    """
    print("Marking complete: hitid {0}; assignmentid {1}; workerid {2}".format(hitid, assignmentid, workerid))
    assignment = get_open_assignments(hitid, assignmentid)
    assignment.markcompleted(workerid, assignmentid)
    session.add(assignment)
    session.commit()
    print("Finished marking complete: assignmentid {0}; workerid {2}".format(assignmentid, workerid))


def saveeventlog(hitid, events):
    """
    Records the event log to database.
    """
    assignment = get_open_assignments(hitid)

    for timestamp, domain, message in events:
        timestamp = datetime.fromtimestamp(int(timestamp) / 1000)
        event = EventLog(assignment = assignment, domain = domain, message = message,
                         timestamp = timestamp)
        session.add(event)
    session.commit()

handlers["turkic_getjobstats"] = \
    (getjobstats, "text/json", True, False, False)
handlers["turkic_savejobstats"] = \
    (savejobstats, "text/json", True, False, True)
handlers["turkic_markcomplete"] = \
    (markcomplete, "text/json", True, False, False)
handlers["turkic_savedonationstatus"] = \
    (savedonationstatus, "text/json", True, False, False)
handlers["turkic_saveeventlog"] = \
    (saveeventlog, "text/json", True, "json", False)
