#
# Copyright 2009 Red Hat, Inc. and/or its affiliates.
#
# Licensed to you under the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.  See the files README and
# LICENSE_GPL_v2 which accompany this distribution.
#


"""
multipath module provides helper procedures for configuring multipath
daemon and maintaining its state
"""
import os
from glob import glob
import tempfile
import logging
import re
from collections import namedtuple

import constants
import misc
import iscsi
import supervdsm
import devicemapper

import storage_exception as se

DEV_ISCSI = "iSCSI"
DEV_FCP = "FCP"
DEV_MIXED = "MIXED"

MAX_CONF_COPIES = 5

TOXIC_CHARS = '()*+?|^$.\\'

MPATH_CONF = "/etc/multipath.conf"

OLD_TAGS = [ "# RHAT REVISION 0.2", "# RHEV REVISION 0.3", "# RHEV REVISION 0.4", "# RHEV REVISION 0.5" ]
MPATH_CONF_TAG = "# RHEV REVISION 0.6"
MPATH_CONF_PRIVATE_TAG = "# RHEV PRIVATE"
MPATH_CONF_TEMPLATE = MPATH_CONF_TAG + constants.STRG_MPATH_CONF

log = logging.getLogger("Storage.Multipath")

def rescan():
    """
    Forces multiupath daemon to rescan the list of available devices and
    refresh the mapping table. New devices can be found under /dev/mapper

    Should only be called from hsm._rescanDevices()
    """

    # First ask iSCSI to rescan all its sessions
    iscsi.rescan()

    supervdsm.getProxy().forceIScsiScan()

    # Now let multipath daemon pick up new devices
    misc.execCmd([constants.EXT_MULTIPATH])


def isEnabled():
    """
    Check the multipath daemon configuration. The configuration file
    /etc/multipath.conf should contain private tag in form
    "RHEV REVISION X.Y" for this check to succeed.
    If the tag above is followed by tag "RHEV PRIVATE" the configuration
    should be preserved at all cost.

    """
    if os.path.exists(MPATH_CONF):
        first = second = ''
        mpathconf = misc.readfileSUDO(MPATH_CONF)
        try:
            first = mpathconf[0]
            second = mpathconf[1]
        except IndexError:
            pass
        if MPATH_CONF_PRIVATE_TAG in second:
            log.info("Manual override for multipath.conf detected - "
                "preserving current configuration")
            if MPATH_CONF_TAG not in first:
                log.warning("This manual override for multipath.conf was based "
                    "on downrevved template. You are strongly advised to "
                    "contact your support representatives")
            return True

        if MPATH_CONF_TAG in first:
            log.debug("Current revision of multipath.conf detected, preserving")
            return True

        for tag in OLD_TAGS:
            if tag in first:
                log.info("Downrev multipath.conf detected, upgrade required")
                return False

    log.debug("multipath Defaulting to False")
    return False

def setupMultipath():
    """
    Set up the multipath daemon configuration to the known and
    supported state. The original configuration, if any, is saved
    """
    if os.path.exists(MPATH_CONF):
        misc.rotateFiles(os.path.dirname(MPATH_CONF), os.path.basename(MPATH_CONF), MAX_CONF_COPIES, cp=True, persist=True)
    f = tempfile.NamedTemporaryFile()
    f.write(MPATH_CONF_TEMPLATE)
    f.flush()
    cmd = [constants.EXT_CP, f.name, MPATH_CONF]
    rc = misc.execCmd(cmd)[0]
    if rc != 0:
        raise se.MultipathSetupError()
    # f close removes file - must be after copy
    f.close()
    misc.persistFile(MPATH_CONF)

    # Flush all unused multipath device maps
    misc.execCmd([constants.EXT_MULTIPATH, "-F"])

    cmd = [constants.EXT_SERVICE, "multipathd", "restart"]
    rc = misc.execCmd(cmd)[0]
    if rc != 0:
        # No dice - try to reload instead of restart
        cmd = [constants.EXT_SERVICE, "multipathd", "reload"]
        rc = misc.execCmd(cmd)[0]
        if rc != 0:
            raise se.MultipathRestartError()

def deduceType(a, b):
    if a == b:
        return a
    else:
        return DEV_MIXED

def getDeviceCapacities():
    sizes = {}
    partFile = open("/proc/partitions", "r")
    for l in partFile:
        try:
            major, minor, size, name = l.split()

            if not name.startswith("dm"):
                continue

            sizes[name] = int(size) * 1024
        except ValueError:
            continue

    return sizes

def getScsiSerial(physdev):
    blkdev = os.path.join("/dev", physdev)
    cmd = [constants.EXT_SCSI_ID, "--page=0x80",
                        "--whitelisted",
                        "--export",
                        "--replace-whitespace",
                        "--device=" + blkdev]
    (rc, out, err) = misc.execCmd(cmd, sudo=False)
    if rc == 0:
        for line in out:
            if line.startswith("ID_SERIAL="):
                return line.split("=")[1]
    return ""

HBTL = namedtuple("HBTL", "host bus target lun")
DeviceNumber = namedtuple("DeviceNumber", "Major Minor")

def getVendor(physDev):
    with open("/sys/block/%s/device/vendor" % physDev, "r") as f:
        return f.read().strip()

def getModel(physDev):
    with open("/sys/block/%s/device/model" % physDev, "r") as f:
        return f.read().strip()

def getFwRev(physDev):
    with open("/sys/block/%s/device/rev" % physDev, "r") as f:
        return f.read().strip()

def getHBTL(physdev):
    hbtl = os.listdir("/sys/block/%s/device/scsi_disk/" % physdev)
    if len(hbtl) > 1:
        log.warn("Found more the 1 HBTL, this shouldn't happen")

    return HBTL(*hbtl[0].split(":"))

def pathListIter(filterGuids=None):
    filteringOn = filterGuids is not None
    filterLen = len(filterGuids) if filteringOn else -1
    devsFound = 0

    knownSessions = {}

    # Capacities and serials are calculated in bulk
    # They have small data structures compared to multipath's
    capacities = getDeviceCapacities()
    svdsm = supervdsm.getProxy()
    pathStatuses = devicemapper.getPathsStatus()

    for guid in getMPDevNamesIter():
        if devsFound == filterLen:
            break

        if filteringOn and guid not in filterGuids:
            continue

        devsFound += 1

        dmId = devicemapper.getDmId(guid)

        devInfo = {
                "guid" : guid,
                "dm" : dmId,
                "capacity" : str(capacities.get(dmId, 0)),
                "serial" : svdsm.getScsiSerial(dmId),
                "paths" : [],
                "connections" : [],
                "devtypes" : [],
                "devtype" : "",
                "vendor" : "",
                "product" :"",
                "fwrev" : "",
                }


        for slave in devicemapper.getSlaves(dmId):
            if not devicemapper.isBlockDevice(slave):
                log.warning("No such physdev '%s' is ignored" % slave)
                continue

            if not devInfo["vendor"]:
                try:
                    devInfo["vendor"] = getVendor(slave)
                except Exception:
                    log.warn("Problem getting vendor from device `%s`", slave, exc_info=True)

            if not devInfo["product"]:
                try:
                    devInfo["product"] = getModel(slave)
                except Exception:
                    log.warn("Problem getting model name from device `%s`", slave, exc_info=True)

            if not devInfo["fwrev"]:
                try:
                    devInfo["fwrev"] = getFwRev(slave)
                except Exception:
                    log.warn("Problem getting fwrev from device `%s`", slave, exc_info=True)

            pathInfo = {}
            pathInfo["physdev"] = slave
            pathInfo["state"] = pathStatuses.get(slave, "failed")
            try:
                pathInfo["hbtl"] = getHBTL(slave)
            except Exception:
                log.warn("Problem getting hbtl from device `%s`", slave, exc_info=True)

            pathInfo["devnum"] = DeviceNumber(*devicemapper.getDevNum(slave))

            if iscsi.devIsiSCSI(slave):
                devInfo["devtypes"].append(DEV_ISCSI)
                pathInfo["type"] = DEV_ISCSI
                sessionID = iscsi.getiScsiSession(slave)
                if sessionID not in knownSessions:
                    knownSessions[sessionID] = iscsi.getdeviSCSIinfo(slave)
                devInfo["connections"].append(knownSessions[sessionID])
            else:
                devInfo["devtypes"].append(DEV_FCP)
                pathInfo["type"] = DEV_FCP

            if devInfo["devtype"] == "":
                devInfo["devtype"] = pathInfo["type"]
            elif devInfo["devtype"] != DEV_MIXED and devInfo["devtype"] != pathInfo["type"]:
                devInfo["devtype"] == DEV_MIXED

            devInfo["paths"].append(pathInfo)

        yield devInfo

def pathinfo(guid):
    res = None
    # We take the first result. There should
    # only be 1 result.
    for dev in pathListIter([guid]):
        res = dev
        break

    if res is None:
        return "", "", "", "", [], []

    return (res["vendor"], res["product"], res["serial"],
           res["devtype"], res["connections"], res["paths"])

TOXIC_REGEX = re.compile(r"[%s]" % re.sub(r"[\-\\\]]", lambda m : "\\" + m.group(), TOXIC_CHARS))
def getMPDevNamesIter():
    """
    Collect the list of all the multipath block devices.
    Return the list of device identifiers w/o "/dev/mapper" prefix
    """
    for dmInfoDir in glob("/sys/block/dm-*/dm/"):
        uuidFile = os.path.join(dmInfoDir, "uuid")
        try:
            with open(uuidFile, "r") as uf:
                uuid = uf.read().strip()
        except (OSError, IOError):
            continue

        if not uuid.startswith("mpath-"):
            continue

        nameFile = os.path.join(dmInfoDir, "name")
        try:
            with open(nameFile, "r") as nf:
                guid = nf.read().strip()
        except (OSError, IOError):
            continue

        if TOXIC_REGEX.match(guid):
            log.info("Device with unsupported GUID %s discarded", guid)
            continue

        yield guid

def devIsiSCSI(type):
    return type in [DEV_ISCSI, DEV_MIXED]


def devIsFCP(type):
    return type in [DEV_FCP, DEV_MIXED]
