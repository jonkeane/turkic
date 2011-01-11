import base64
import time
import hashlib
import hmac
import httplib
import urllib
from xml.etree import ElementTree

class Server(object):
    def __init__(self, signature, accesskey, localhost, sandbox = False):
        self.signature = signature
        self.accesskey = accesskey
        self.localhost = localhost
        self.sandbox = sandbox

        if sandbox:
            self.server = "mechanicalturk.sandbox.amazonaws.com:80"
        else:
            self.server = "mechanicalturk.amazonaws.com:80"

    def request(self, operation, parameters = {}):
        """
        Sends the request to the Turk server and returns a response object.
        """

        if not self.signature or not self.accesskey:
            raise RuntimeError("Signature or access key missing")

        timestamp = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        hmacstr = hmac.new(config.signature, "AWSMechanicalTurkRequester" + operation + timestamp, hashlib.sha1)
        hmacstr = base64.encodestring(hmacstr.digest()).strip()

        baseurl = "/?" + urllib.urlencode({
                    "Service": "AWSMechanicalTurkRequester",
                    "AWSAccessKeyId": config.accesskey,
                    "Version": "2008-08-02",
                    "Operation": operation,
                    "Signature": hmacstr,
                    "Timestamp": timestamp})
        url = baseurl + "&" + urllib.urlencode(parameters)

        conn = httplib.HTTPConnection(self.server)
        conn.request("GET", url)
        response = Response(operation, conn.getresponse())
        conn.close()
        return response

    def createhit(self, title, description, page, amount, duration, lifetime, keywords = "", autoapprove = 604800, height = 650):
        """
        Creates a HIT on Mechanical Turk.
        
        If successful, returns a Response object that has fields:
            hit_id          The HIT ID
            hit_type_id     The HIT group ID

        If unsuccessful, a CommunicationError is raised with a message describing the failure.
        """
        r = {"Title": title,
            "Description": description,
            "Keywords": keywords,
            "Reward.1.Amount": amount,
            "Reward.1.CurrencyCode": "USD",
            "AssignmentDurationInSeconds": duration,
            "AutoApprovalDelayInSeconds": autoapprove,
            "LifetimeInSeconds": lifetime}

        r["Question"] = "<ExternalQuestion xmlns=\"http://mechanicalturk.amazonaws.com/AWSMechanicalTurkDataSchemas/2006-07-14/ExternalQuestion.xsd\">" +\
        "<ExternalURL>{0}/{1}</ExternalURL>".format(self.localhost, page) +\
        "<FrameHeight>{0}</FrameHeight>".format(height) +\
        "</ExternalQuestion>"

        r = self.request("CreateHIT", r);
        r.validate("HIT/Request/IsValid", "HIT/Request/Errors/Error/Message")
        r.store("HIT/HITId", "hitid")
        r.store("HIT/HITTypeId", "hittypeid")
        return r

    def accept(self, assignmentid, feedback = ""):
        """
        Accepts the assignment and pays the worker.
        """
        r = self.request("ApproveAssignment", {"AssignmentId": assignmentid, "RequesterFeedback": feedback})
        r.validate("ApproveAssignmentResult/Request/IsValid", "ApproveAssignmentResult/Request/Errors/Error/Message")
        return r

    def reject(self, assignmentid, feedback = ""):
        """
        Rejects the assignment and does not pay the worker.
        """
        r = self.request("RejectAssignment", {"AssignmentId": assignmentid, "RequesterFeedback": feedback})
        r.validate("RejectAssignmentResult/Request/IsValid", "RejectAssignmentResult/Request/Errors/Error/Message")
        return r

    def bonus(self, workerid, assignmentid, amount, feedback = ""):
        """
        Grants a bonus to a worker for an assignment.
        """
        r = self.request("GrantBonus",
            {"WorkerId": workerid,
             "AssignmentId": assignmentid,
             "BonusAmount.1.Amount": amount,
             "BonusAmount.1.CurrencyCode": "USD",
             "Reason": feedback});
        r.validate("GrantBonusResult/Request/IsValid", "GrantBonusResult/Request/Errors/Error/Message")
        return r

    def block(self, workerid, reason = ""):
        """
        Blocks the worker from working on any of our HITs.
        """
        r = self.request("BlockWorker", {"WorkerId": workerid, "Reason": reason})
        r.validate("BlockWorkerResult/Request/IsValid", "BlockWorkerResult/Request/Errors/Error/Message")
        return r

    def unblock(self, workerid, reason = ""):
        """
        Unblocks the worker and allows him to work for us again.
        """
        r = self.request("UnblockWorker", {"WorkerId": workerid, "Reason": reason})
        r.validate("UnblockWorkerResult/Request/IsValid", "UnblockWorkerResult/Request/Errors/Error/Message")
        return r

    @property
    def balance(self):
        """
        Returns a response object with the available balance in the amount attribute.
        """
        r = self.request("GetAccountBalance")
        r.validate("GetAccountBalanceResult/Request/IsValid")
        r.store("GetAccountBalanceResult/AvailableBalance/Amount", "amount", float)
        r.store("GetAccountBalanceResult/AvailableBalance/CurrencyCode", "currency")
        return r.amount

class Response(object):
    """
    A generic response from the MTurk server.
    """
    def __init__(self, operation, httpresponse):
        self.operation = operation
        self.httpresponse = httpresponse
        self.data = httpresponse.read()
        self.tree = ElementTree.fromstring(self.data)
        self.values = {}

    def validate(self, valid, errormessage = None):
        """
        Validates the response and raises an exception if invalid.
        
        Valid contains a path that must contain False if the response is invalid.
        
        If errormessage is not None, use this field as the error description.
        """
        valide = self.tree.find(valid)
        if valide is None:
            raise CommunicationError("XML malformed", self)
        elif valide.text.strip() == "False":
            if errormessage:
                errormessage = self.tree.find(errormessage)
                if errormessage is None:
                    raise CommunicationError("Response not valid and XML malformed", self)
                raise CommunicationError(errormessage.text.strip(), self)
            else:
                raise CommunicationError("Response not valid", self)

    def store(self, path, name, type = str):
        """
        Stores the text at path into the attribute name.
        """
        node = self.tree.find(path)
        if node is None:
            raise CommunicationError("XML malformed (cannot find {0})".format(path))
        self.values[name] = type(node.text.strip())

    def __getattr__(self, name):
        """
        Used to lookup attributes.
        """
        if name not in self.values:
            raise AttributeError("{0} is not stored".format(name))
        return self.values[name]

class CommunicationError(Exception):
    """
    The error raised due to a communication failure with MTurk.
    """
    def __init__(self, error, response):
        self.error = error
        self.response = response

    def __str__(self):
        return self.error

try:
    import config
except ImportError:
    pass
else:
    server = Server(config.signature, config.accesskey, config.localhost, config.sandbox)
