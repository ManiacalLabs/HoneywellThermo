"""Based on work done here:
http://www.theghostbit.com/2015/06/controlling-honeywell-thermostat.html
"""

import urllib2
import urllib
import json
import datetime
import re
import time
import math
import base64
import time
import httplib
import sys
import getopt
import os
import stat
import subprocess
import string

class jdict(dict):
    def __init__(self, *a, **k):
        super(jdict, self).__init__(*a, **k)
        #set the internal property dict to itself
        self.__dict__ = self
        #recurses through list and dict types, converting to jdict
        for k in self.__dict__:
            if isinstance(self.__dict__[k], dict):
                self.__dict__[k] = jdict(self.__dict__[k])
            elif isinstance(self.__dict__[k], list):
                for i in range(len(self.__dict__[k])):
                    if isinstance(self.__dict__[k][i], dict):
                        self.__dict__[k][i] = jdict(self.__dict__[k][i])

    #Undefined keys now return None instead of throwing exception
    def __getattr__(self, name):
        return None

COOKIE_RE = re.compile('\s*([^=]+)\s*=\s*([^;]*)\s*')


def client_cookies(cookiestr, container):
    if not container:
        container = {}
    toks = re.split(';|,', cookiestr)
    for t in toks:
        k = None
        v = None
        m = COOKIE_RE.search(t)
        if m:
            k = m.group(1)
            v = m.group(2)
            if (k in ['path', 'Path', 'HttpOnly']):
                k = None
                v = None
        if k:
            # print k,v
            container[k] = v
    return container


def export_cookiejar(jar):
    s = ""
    for x in jar:
        s += '%s=%s;' % (x, jar[x])
    return s

def _keyFromVal(d, val):
    for k, v in d.iteritems():
        if v == val:
            return k
    return None


class HoneywellThermo(object):
    AUTH = "https://mytotalconnectcomfort.com/portal"
    COOKIE_RE = re.compile('\s*([^=]+)\s*=\s*([^;]*)\s*')

    SystemStates = jdict({
        "Off" : 2,
        "Heat" : 1,
        "Cool" : 3,
        "Auto" : 4,
        "EmHeat" : 5
    })

    FanStates = jdict({
        "On" : 1,
        "Auto" : 0,
        "Circulate" : 2
    })

    def __init__(self, user, passw, zones=None):
        self.user = user
        self.passw = passw
        if not isinstance(zones, dict):
            zones = None
        self.zones = zones

    def login(self):
        # Get initial cookie config
        cookiejar = None

        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Encoding": "sdch",
                   "Host": "mytotalconnectcomfort.com",
                   "DNT": "1",
                   "Origin": "https://mytotalconnectcomfort.com/portal",
                   "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36"
                   }
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")
        conn.request("GET", "/portal/", None, headers)
        r0 = conn.getresponse()
        if r0.status != 200:
            raise Exception("Login failure while getting auth cookie.")

        for x in r0.getheaders():
            (n, v) = x
            if (n.lower() == "set-cookie"):
                cookiejar = client_cookies(v, cookiejar)

        # Do actual login
        params = urllib.urlencode({"timeOffset": "240",
                                   "UserName": self.user,
                                   "Password": self.passw,
                                   "RememberMe": "false"})

        newcookie = export_cookiejar(cookiejar)

        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Encoding": "sdch",
                   "Host": "mytotalconnectcomfort.com",
                   "DNT": "1",
                   "Origin": "https://mytotalconnectcomfort.com/portal/",
                   "Cookie": newcookie,
                   "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36"
                   }
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")
        conn.request("POST", "/portal/", params, headers)
        r1 = conn.getresponse()

        for x in r1.getheaders():
            (n, v) = x
            if (n.lower() == "set-cookie"):
                cookiejar = client_cookies(v, cookiejar)

        # set the connection cookie
        self.cookie = export_cookiejar(cookiejar)

        if ((r1.getheader("Location") == None) or (r1.status != 302)):
            raise Exception(
                "Login Fail: Status={0} {1}".format(r1.status, r1.reason))

        headers = {"Content-Type": "application/x-www-form-urlencoded",
                   "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                   "Accept-Encoding": "sdch",
                   "Host": "mytotalconnectcomfort.com",
                   "DNT": "1",
                   "Origin": "https://mytotalconnectcomfort.com/portal/",
                   "Cookie": self.cookie,
                   "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36"
                   }
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")
        conn.request("GET", "/portal/", None, headers)
        r2 = conn.getresponse()
        loc = r2.getheader("location")
        if not loc:
            raise Exception(
                "Error fetching zone details! Response {}".format(r2.status))

        try:
            self.location = loc.split("/")[2]
        except:
            raise Exception("Location data returned in wrong format.")

        if not self.zones:
            self.getZones()

    def getZones(self):
        headers = {
            "Accept": 'application/json; q=0.01',
            "DNT": "1",
            "Accept-Encoding": "gzip,deflate,sdch",
            'Content-Type': 'application/json; charset=UTF-8',
            "Cache-Control": "max-age=0",
            "Accept-Language": "en-US,en,q=0.8",
            "Connection": "keep-alive",
            "Host": "mytotalconnectcomfort.com",
            "Referer": "https://mytotalconnectcomfort.com/portal/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36",
            "Referer": "https://mytotalconnectcomfort.com/portal/" + self.location + "/Zones",
            "Cookie": self.cookie
        }
        params = json.dumps({"locationId": self.location})
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")
        conn.request("POST", "/portal/Device/GetZoneListData?locationId=" + self.location + "&page=1",
                     params, headers)
        r = conn.getresponse()

        if r.status == 200:
            zones = json.loads(r.read())
            # print zones
            self.zones = {}
            c = 1
            for z in zones:
                self.zones["Zone " + str(c)] = str(z["DeviceID"])
                c += 1
        else:
            raise Exception("Failure fetching zone details.")

        return self.zones

    def __resolveZone(self, zone):
        if zone in self.zones:
            zone = self.zones[zone]
        return str(zone)

    def getZoneDetails(self, zone):
        zone = self.__resolveZone(zone)

        t = datetime.datetime.now()
        utc_seconds = (time.mktime(t.timetuple()))
        utc_seconds = int(utc_seconds * 1000)

        location = "/portal/Device/CheckDataSession/" + \
            zone + "?_=" + str(utc_seconds)

        headers = {
            "Accept": "*/*",
            "DNT": "1",
            "Accept-Encoding": "gzip,deflate,sdch",
            "Accept-Encoding": "plain",
            "Cache-Control": "max-age=0",
            "Accept-Language": "en-US,en,q=0.8",
            "Connection": "keep-alive",
            "Host": "mytotalconnectcomfort.com",
            "Referer": "https://mytotalconnectcomfort.com/portal/",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36",
            "Cookie": self.cookie
        }
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")
        conn.request("GET", location, None, headers)
        r = conn.getresponse()
        if (r.status != 200):
            raise Exception(
                "Failure fetching zone details. {0} {1}".format(r.status, r.reason))

        j = r.read()
        j = json.loads(j)

        d = j['latestData']['uiData']
        has_out_h = d['OutdoorHumidityAvailable'] and d[
            'OutdoorHumiditySensorNotFault']
        has_in_h = d['IndoorHumiditySensorAvailable'] and d[
            'IndoorHumiditySensorNotFault']
        has_out_t = d['OutdoorTemperatureAvailable'] and d[
            'OutdoorHumiditySensorNotFault']
        fanState = _keyFromVal(HoneywellThermo.FanStates, j['latestData']['fanData']["fanMode"])
        systemSwitch = _keyFromVal(HoneywellThermo.SystemStates, d["SystemSwitchPosition"])
        result = {
            "IndoorTemp": d["DispTemperature"],
            "IndoorHumidity": d["IndoorHumidity"] if has_in_h else None,
            "OutdoorTemp": d["OutdoorTemperature"] if has_out_t else None,
            "OutdoorHumidity": d["OutdoorHumidity"] if has_out_h else None,
            "CoolSetpoint": d["CoolSetpoint"],
            "HeatSetpoint": d["HeatSetpoint"],
            "HoldUntil ": d["TemporaryHoldUntilTime"],
            "StatusCool": bool(d["StatusCool"]),
            "StatusHeat": bool(d["StatusHeat"]),
            "FanStatus": fanState,
            "SystemSwitch" : systemSwitch
        }

        return result

    def getAllZoneDetails(self):
        result = {}
        for z in self.zones:
            result[z] = self.getZoneDetails(z)
        return result

    def set(self, zone, coolTemp=None, coolState=None,
            heatTemp=None, heatState=None,
            holdTime=None, fanState=None, systemState=None):

        zone = self.__resolveZone(zone)
        try:
            i_zone = int(zone)
        except:
            raise Exception("Invalid Zone ID")

        stop_time = None
        if holdTime:
            t = datetime.datetime.now()
            stop_time = ((t.hour + hold_time) % 24) * 60 + t.minute
            stop_time = stop_time / 15

        payload = {
            "DeviceID": i_zone,
            "CoolNextPeriod": stop_time,
            "CoolSetpoint": None,
            "FanMode": None,
            "HeatNextPeriod": stop_time,
            "HeatSetpoint": None,
            "StatusCool": None,
            "StatusHeat": None,
            "SystemSwitch": None
        }

        if coolTemp is not None:
            payload["CoolSetpoint"] = coolTemp
            payload["CoolNextPeriod"] = stop_time
            #coolState = heatState = True

        if heatTemp is not None:
            payload["HeatSetpoint"] = heatTemp
            payload["HeatNextPeriod"] = stop_time
            #heatState = coolState = True

        if coolState is not None:
            payload["StatusCool"] = 1 if coolState else 0

        if heatState is not None:
            payload["StatusHeat"] = 1 if heatState else 0

        if fanState is not None:
            if fanState not in HoneywellThermo.FanStates:
                key = _keyFromVal(HoneywellThermo.FanStates, fanState)
                if key is None:
                    raise Exception("Invalid Fan State")
            else:
                fanState = HoneywellThermo.FanStates[fanState]

            payload["FanMode"] = fanState

        if systemState is not None:
            if systemState not in HoneywellThermo.SystemStates:
                key = _keyFromVal(HoneywellThermo.SystemStates, systemState)
                if key is None:
                    raise Exception("Invalid System State.")
            else:
                systemState = HoneywellThermo.SystemStates[systemState]

            payload["SystemSwitch"] = systemState

        location = "/portal/Device/SubmitControlScreenChanges"

        rawj = json.dumps(payload)
        print rawj
        conn = httplib.HTTPSConnection("mytotalconnectcomfort.com")

        headers = {
            "Accept": 'application/json, text/javascript, */*; q=0.01',
            "Accept-Encoding": "gzip,deflate,sdch",
            'Content-Type': 'application/json; charset=UTF-8',
            'Origin': "https://mytotalconnectcomfort.com",
            "Cache-Control": "max-age=0",
            "Accept-Language": "en-US,en,q=0.8",
            "Connection": "keep-alive",
            "Host": "mytotalconnectcomfort.com",
            "X-Requested-With": "XMLHttpRequest",
            "User-Agent": "Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/28.0.1500.95 Safari/537.36",
            'Referer': "https://mytotalconnectcomfort.com/portal/Device/Control/" + zone + "?page=1",
            "Cookie": self.cookie
        }

        conn.request("POST", location, rawj, headers)
        r = conn.getresponse()
        if (r.status != 200):
            raise Exception(
                "Failure sending settings. {0} {1}".format(r.status, r.reason))
