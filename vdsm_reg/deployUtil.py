# Copyright 2009-2010 Red Hat, Inc. All rights reserved.
# Use is subject to license terms.
#
# Description: Deployment utilities.

import subprocess
import logging
import traceback
import socket
import re
import sys
import os
import os.path
import time
import grp
import pwd
import shutil
from xml.sax import saxutils
import struct
import httplib
import glob
import imp

# Path constants
P_BIN = '/bin/'
P_ETC_INITD = '/etc/init.d/'
P_ROOT_SSH = '/root/.ssh'
P_ROOT_AUTH_KEYS = P_ROOT_SSH + '/authorized_keys'
P_SBIN = '/sbin/'
P_USR_BIN = '/usr/bin/'
P_USR_SBIN = '/usr/sbin/'
P_LIBEXEC = '/usr/libexec/'

# Executables
EX_AWK = P_BIN + 'awk'
EX_BASH = P_BIN + 'bash'
EX_CAT = P_BIN + 'cat'
EX_CHKCONFIG = P_SBIN + 'chkconfig'
EX_DMIDECODE = P_USR_SBIN + 'dmidecode'
EX_ECHO = P_BIN + 'echo'
EX_GRUBBY = P_SBIN + 'grubby'
EX_HEAD = P_USR_BIN + 'head'
EX_HWCLOCK = P_SBIN + 'hwclock'
EX_IFCONFIG = P_SBIN + 'ifconfig'
EX_LSB_RELEASE = P_USR_BIN + 'lsb_release'
EX_OPENSSL = P_USR_BIN + 'openssl'
EX_OVIRT_FUNTIONS = P_LIBEXEC + 'ovirt-functions'
EX_REBOOT = P_SBIN + 'reboot'
EX_RPM = P_BIN + 'rpm'
EX_SED = P_BIN + 'sed'
EX_SERVICE = P_SBIN + 'service'
EX_SORT = P_BIN + 'sort'
EX_TRACEROUTE = P_BIN + 'traceroute'
EX_UNAME = P_BIN + 'uname'
EX_YUM = P_USR_BIN + 'yum'

# Other constants
READ_BUF_SIZE = 1024
DEF_KEY_LEN = 1024
HTTP_TIMEOUT = 30
ERR_NO_ROUTE = 7
SCRIPT_NAME_ADD = "addNetwork"
SCRIPT_NAME_DEL = "delNetwork"
IFACE_CONFIG = "/etc/sysconfig/network-scripts/ifcfg-"
MGT_BRIDGE_NAME = "rhevm"
REMOTE_SSH_KEY_FILE = "/rhevm.ssh.key.txt"
OVIRT_SAFE_DEL_FUNCTION = "ovirt_safe_delete_config"
OVIRT_STORE_FUNCTION = "ovirt_store_config"
CORE_DUMP_PATH = '/var/lib/vdsm/core'
CORE_PATTERN = '/proc/sys/kernel/core_pattern'
XML_QUOTES = {
    "\n":' ',
    "'":'~'
}

def _logExec(argv):
    """
        This function executes a given shell command while logging it.
    """
    out = None
    err = None
    rc = None
    try:
        logging.debug(argv)
        p = subprocess.Popen(argv , stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        out, err = p.communicate()
        rc = p.returncode
        logging.debug(out)
        logging.debug(err)
    except:
        logging.error(traceback.format_exc())
    return (out, err, rc)

#############################################################################################################
# Host Misc functions.
#############################################################################################################
def escapeXML(message):
    """
        Escape '&', '<', '>', and '\n' in a given string.
    """
    return saxutils.escape(message, XML_QUOTES)

def reboot():
    """
        This function reboots the machine.
    """
    fReturn = True

    out, err, ret = _logExec([EX_REBOOT])
    if ret:
        fReturn = False

    return fReturn

def setCoreDumpPath():
    logging.debug("setCoreDumpPath started.")
    fReturn = True
    try:
        _logExec([EX_ECHO, CORE_DUMP_PATH, ">", CORE_PATTERN])
        print "<BSTRAP component='CoreDump' status='OK'/>"
    except:
        fReturn = False
        print "<BSTRAP component='CoreDump' status='FAIL'/>"

    logging.debug("setCoreDumpPath end:" + str(fReturn))
    return fReturn

def cleanAll(random_num):
    """ Remove temp files.
    """
    fReturn = True
    try:
        # build semi-random filenames
        req_conffile = '/tmp/req_' + random_num + '.conf'
        cert_reqfile = '/tmp/cert_' + random_num + '.req'
        cert_pemfile = '/tmp/cert_' + random_num + '.pem'
        ca_pemfile = '/tmp/CA_' + random_num + '.pem'
        # remove unnecessary files
        os.unlink(req_conffile)
        os.unlink(cert_reqfile)
        os.unlink(cert_pemfile)
        os.unlink(ca_pemfile)

        if not isOvirt():
            vds_bstrap = '/tmp/vds_bootstrap_' + random_num + '.py'
            vds_bstrap_cmp = '/tmp/vds_bootstrap_complete_' + random_num + '.py'
            vds_bstrap_pyc = '/tmp/vds_bootstrap_' + random_num + '.pyc'
            vds_bstrap_cmp_pyc = '/tmp/vds_bootstrap_complete_' + random_num + '.pyc'
            vds_bstrap_deployutil = '/tmp/deployUtil.py'
            vds_bstrap_deployutil_pyc = '/tmp/deployUtil.pyc'
            os.unlink(vds_bstrap)
            os.unlink(vds_bstrap_cmp)
            os.unlink(vds_bstrap_pyc)
            os.unlink(vds_bstrap_cmp_pyc)
            os.unlink(vds_bstrap_deployutil)
            os.unlink(vds_bstrap_deployutil_pyc)

    except:
        pass

    print "<BSTRAP component='cleanAll' status='OK'/>"
    logging.debug("cleanAll end:" + str(fReturn))

    return fReturn

def setVdsConf(configStr, confFile):
    """
        This function changes local configuration according to the
        given 'key=value;' string.
    """
    fReturn = True
    logging.debug("setVdsConf: started. config:" + str(configStr))
    if not configStr:
        logging.debug("setVdsConf: nothing to set.")
        return True

    if not os.path.exists(confFile):
        strMessage = escapeXML("File " + confFile + "does not exist.")
        print "<BSTRAP component='VDS Configuration' status='FAIL' message='" + strMessage + "'/>"
        logging.debug("setVdsConf: " + strMessage)
        return False

    try:
        new_config_params = {}
        config_params = configStr.split(';')
        for item in config_params:
            key = item.split('=')[0].strip()
            val = item.split('=')[1].strip()
            new_config_params[key] = val

        for key in new_config_params.keys():
            val = new_config_params[key]
            logging.debug("setVdsConf: setting Key=" + str(key) + " to val=" + str(val))
            _updateFileLine(confFile, key, val)
            #_logExec([EX_SED, "-i", "s:^\s*"+key+"\s*=.*:"+key+"="+val+":", confFile])

        if isOvirt():
            # save the updated file
            logging.debug("setVdsConf: saving new config file")
            _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_STORE_FUNCTION, confFile])

        print "<BSTRAP component='VDS Configuration' status='OK'/>"
    except Exception, e:
        msg = escapeXML(str(e))
        print "<BSTRAP component='VDS Configuration' status='FAIL' message='%s'/>" % (msg)
        logging.debug("setVdsConf: exception " + msg)
        fReturn = False

    logging.debug("setVdsConf: ended.")
    return fReturn

def getMachineUUID():
    """
        This function parses the DMI data for the host's UUID. If not found, returns "None".
    """
    strReturn = "None"

    out, err, ret = _logExec([EX_BASH, "-c", EX_DMIDECODE + "|" + EX_AWK + " ' /^\tUUID: /{ print $2; } '"])
    if ret == 0 and "Not" not in out: #Avoid error string- 'Not Settable' or 'Not Present'
        strReturn = out.replace ("\n", "")
    else:
        logging.error("getMachineUUID: Could not find machine's UUID.")

    return strReturn

def getMacs():
    macs = []
    for b in glob.glob('/sys/class/net/*/device'):
        nic = b.split('/')[-2]
        addr = '/sys/class/net/' + nic + '/address'
        mac = file(addr).readlines()[0].split()[0]
        macs.append(mac)

    return macs

def getHostID():
    """
        This function concatenate the first serted mac address to the machine's UUID.
    """
    strReturn = getMachineUUID()

    macs = getMacs()

    if len(macs) > 0:
        strMAC = sorted(macs)[0]
    else:
        strMAC = ""
        logging.warning("getHostID: Could not find machine's MAC, returning UUID only.")

    if strReturn != "None":
        strReturn += "_" + strMAC
    else:
        strReturn = "_" + strMAC

    logging.debug("getHostID: " + str(strReturn))
    return strReturn

def _getIfaceByIP(addr):
    remote = struct.unpack('I', socket.inet_aton(addr))[0]
    for line in file('/proc/net/route').readlines()[1:]:
        iface, dest, gateway, flags, refcnt, use, metric, \
            mask, mtu, window, irtt = line.split()
        dest = int(dest, 16)
        mask = int(mask, 16)
        if remote & mask == dest & mask:
            return iface

    return None # should never get here w/ default gw

def _getMGTIface(vdcHostName):
    strVDCIP = "None"
    strReturn = None
    strVDCName = vdcHostName

    try:
        if vdcHostName != "None":
            logging.debug("_getMGTIface: read vdc_host_name: " + strVDCName)
            #Now find the IP. Note that gethostbyname(IP) == IP
            strVDCIP = socket.gethostbyname(strVDCName)
    except:
            strVDCIP = "None"
            logging.debug("_getMGTIface: error trying to figure out VDC's IP")

    logging.debug("_getMGTIface: using vdc_host_name " + strVDCName + " strVDCIP= " + strVDCIP)

    # Find the interface of the management IP
    if strVDCIP != "None":
        strReturn = _getIfaceByIP(strVDCIP)

    logging.debug("_getMGTIface VDC IP=" + str(strVDCIP) + " strIface=" + str(strReturn))
    return strReturn

def getMGTIP(vdsmDir, vdcHostName):
    strReturn = "None"

    try:
        sys.path.append(vdsmDir)
        import netinfo # taken from vdsm rpm
    except:
        logging.error("getMGTIP: Faild to find vdsm modules!")
        return strReturn

    arNICs = None
    strIface = _getMGTIface(vdcHostName)

    if strIface is not None:
        arNICs = netinfo.ifconfig()

    logging.debug("getMGTIP: Host parsed interfaces:\n" + str(arNICs) + "\n")

    if arNICs != None:
        strReturn = arNICs[strIface]['addr']

    logging.debug("getMGTIP: Host MGT IP=" + strReturn)
    return strReturn

def preventDuplicate():
    """
      This function checks if the needed bridge (rhevm) already exist.
    """
    fFound = False

    if os.path.exists('/sys/class/net/' + MGT_BRIDGE_NAME):
        fFound = True
        logging.debug("Bridge rhevm already exists.")
    else:
        logging.debug("Bridge rhevm not found, need to create it.")

    return fFound

def isOvirt():
    """
        This function checks if current machine runs ovirt platform.
    """
    return os.path.exists('/etc/rhev-hypervisor-release')

def getOSVersion():
    """
        Return the OS' release from accordong to LSB specification.
    """
    strReturn = "Unknown OS"

    if os.path.exists(EX_LSB_RELEASE):
        out, err, rc = _logExec([EX_LSB_RELEASE, "-rs"])
        try:
            strReturn = out.replace("\n","")
        except:
            strReturn = "Unknown OS"

    return strReturn

def getKernelVersion():
    """
        Return current kernel release.
    """
    strReturn = '0'
    out, err, rc = _logExec([EX_UNAME, "-r"])
    if not rc:
        strReturn = out

    return strReturn

def updateKernelArgs(arg):
    """
        Update current kernel arguments using grubby.
    """
    fReturn = False
    try:
        out, err, ret = _logExec([EX_GRUBBY, "--update-kernel",
                                    "DEFAULT", "--args", arg] )
        if not ret:
            fReturn = True
    except:
        pass

    return fReturn

def getAddress(url):
    logging.debug("getAddress Entry. url=" + str(url))
    import urlparse
    strRetAddress = None
    strRetPort = None
    scheme = None
    netloc = None
    path = None
    query = None
    fragment = None

    (scheme, netloc, path, query, fragment) = urlparse.urlsplit(url)
    if scheme != '':      #('http', 'www.redhat.com', '/rhel/virtualization/', '', '')
        strRetAddress = netloc
    elif path != '':      #('', '', 'www.redhat.com', '', '')
        strRetAddress = path
    else:
        logging.error("Unable to parse: " + str(url))

    # Find port
    if strRetAddress is not None and ":" in strRetAddress:
        strRetAddress, strRetPort = strRetAddress.split(":")

    logging.debug("getAddress return. address=" + str(strRetAddress) + " port=" + str(strRetPort))
    return strRetAddress, strRetPort

def waitRouteRestore(maxCount, targetIP):
    logging.debug("waitRouteRestore Entry. maxCount=" + str(maxCount) + " targetIP:" + targetIP)

    fReturn = True
    count = 0
    ret1 = ERR_NO_ROUTE #no route error code
    while(count<maxCount and ret1 == ERR_NO_ROUTE):
        try:
            out1, err1, ret1 = _logExec([
                '/usr/bin/curl',
                '-s',
                '--connect-timeout', '10',
                '--max-filesize', '10',
                targetIP
            ])
        except:
            pass

        count = count + 1
        logging.debug(
            " count=" + str(count-1) +
            "\nout=" + out1 +
            "\nerr=" + str(err1) +
            "\nret=" + str(ret1)
        )
        time.sleep(1)

    if ret1 == ERR_NO_ROUTE:
        fReturn = False

    logging.debug("waitRouteRestore Return. fReturn=" + str(fReturn))
    return fReturn

def setService(srvName, action):
    """
        Perform an action (stop/start/status/...) on a service
    """
    nReturn = 0
    out = None
    err = None
    if type(srvName) == type(None):
        nReturn = 1
        message = "setService: ignoring None service."
        err = message
        logging.error(message)
    elif os.path.exists(P_ETC_INITD + srvName):
        out, err, nReturn = _logExec([EX_SERVICE, srvName, action])
    else:
        nReturn = 1
        err = "No such service: " + srvName

    return out, err, nReturn

def chkConfig(srvName, action, level=None):
    """
        Perform a set action (on/off/reset) on an init script
    """
    nReturn = 0
    out = None
    err = None
    if type(srvName) == type(None):
        nReturn = 1
        message = "chkConfig: ignoring None service."
        err = message
        logging.error(message)
    elif os.path.exists(P_ETC_INITD + srvName):
        if level:
            out, err, nReturn = _logExec([EX_CHKCONFIG, '--level', level, srvName, action])
        else:
            out, err, nReturn = _logExec([EX_CHKCONFIG, srvName, action])
    else:
        if action != "off":
            nReturn = 1
            err = "No such service: " + srvName
        else:
            logging.debug("chkConfig: ignoring uninstalled service: " + str(srvName))

    return out, err, nReturn


#############################################################################################################
# Host SSH functions.
#############################################################################################################

def getAuthKeysFile(IP, port):
    """
        This functions returns the public ssh key of rhev-m.
    """
    logging.debug('getAuthKeysFile begin. IP=' + str(IP) + " port=" + str(port))
    strKey = None
    res = None
    conn = None
    old_timeout = socket.getdefaulttimeout()
    socket.setdefaulttimeout(HTTP_TIMEOUT)
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    fOK = True

    try:
        nPort = 443
        if port is not None:
            nPort = int(port)

        sock.connect((IP, nPort))
        conn = httplib.HTTPSConnection(IP, nPort)
        conn.sock = getSSLSocket(sock)
        conn.request("GET", REMOTE_SSH_KEY_FILE)
        res = conn.getresponse()
    except:
        #logging.debug(traceback.format_exc())
        logging.debug("getAuthKeysFile failed in HTTPS. Retrying using HTTP.")
        strPort = ":"
        if port is None:
            strPort += "80"
        else:
            strPort += port

        try:
            conn = httplib.HTTPConnection(IP + strPort)
            conn.request("GET", REMOTE_SSH_KEY_FILE)
            res = conn.getresponse()
        except:
            logging.error("Failed to fetch keys using http.")
            logging.debug(traceback.format_exc())
            fOK = False
    else:
        logging.debug("getAuthKeysFile status: " + str(res.status) + " reason: " + res.reason)

    if res == None or res.status != 200:
        status = ""
        if res != None:
            status = str(res.status)
        if conn != None: conn.close()
        fOK = False
        logging.error("Failed to fetch keys: " + status)

    if fOK:
        try:
            try:
                strKey = str(res.read())
            except:
                logging.error("Failed to read ssh key.")
                logging.error(traceback.format_exc())
        finally:
            if conn != None: conn.close()

    socket.setdefaulttimeout(old_timeout)

    logging.debug('getAuthKeysFile end.')
    return strKey

def addSSHKey(path, strKey):
    resKeys = []

    try:
        for key in file(path):
            if key != '\n' and not key.endswith("== rhevm") or key.startswith("#"):
                resKeys.append(key)
    except IOError:
        logging.debug("Failed to read %s" % path)
    resKeys.append('\n' + strKey)

    if isOvirt():
        # No problem to write to the original file here, since until it is not
        # persisted the old values are in place
        open(path, 'w').write(''.join(resKeys))
    else:
        tmpFilePath = path + '.tmp'
        open(tmpFilePath, 'w').write(''.join(resKeys))
        os.rename(tmpFilePath, path)

def handleSSHKey(strKey):
    """
        This functions appends a given key to the root's authorized_keys file.
    """
    fReturn = True
    logging.debug('handleSSHKey start')
    if not os.path.exists(P_ROOT_SSH):
        logging.debug("handleSSHKey: creating .ssh dir.")
        try:
            os.mkdir(P_ROOT_SSH, 0700)
        except OSError, err:
            fReturn = False
            logging.debug("handleSSHKey: failed to create ssh dir!")

    if fReturn:
        try:
            addSSHKey(P_ROOT_AUTH_KEYS, strKey)
        except:
            fReturn = False
            logging.debug("handleSSHKey: failed to write authorized_keys!",
                          exc_info=True)

    if fReturn:
        try:
            os.chmod(P_ROOT_AUTH_KEYS, 0644)
        except:
            fReturn = False
            logging.debug("handleSSHKey: failed to chmod authorized_keys")

    if fReturn and isOvirt():
        # persist authorized_keys
        logging.debug("handleSSHKey: persist authorized_keys")
        out, err, ret = _logExec([EX_BASH, EX_OVIRT_FUNTIONS,
                                  OVIRT_STORE_FUNCTION, P_ROOT_AUTH_KEYS])

    logging.debug('handleSSHKey end')
    return fReturn

#############################################################################################################
# Host time functions.
#############################################################################################################

def setHostTime(VDCTime):
    logging.debug('setHostTime start.')
    import time
    fReturn = True

    try:
        ttp = time.strptime(VDCTime, '%Y-%m-%dT%H:%M:%S')
    except ValueError, e:
        logging.debug("setHostTime: Failed to parse RHEVM time. message= " + str(e))
        fReturn = False

    if fReturn:
        out, err, rc = _logExec([EX_HWCLOCK, "--set", "--utc",
            time.strftime('--date=%Y-%m-%d %H:%M:%S UTC', ttp)])
        if rc:
            logging.debug("setHostTime: Failed to set hwclock time. out=" + out + "\nerr=" + str(err) + "\nrc=" + str(rc))
            fReturn = False

    if fReturn:
          out, err, rc = _logExec([EX_HWCLOCK, "-s"])
          if rc:
            logging.debug("setHostTime: Failed to sync hwclock time to host. out=" + out + "\nerr=" + str(err) + "\nrc=" + str(rc))
            fReturn = False

    logging.debug('setHostTime end. Return:' + str(fReturn))
    return fReturn

#############################################################################################################
# Update configuration file functions.
#############################################################################################################

def _updateFileLine(fileName, key, value):
    """
        Update a line of a configuration file. This function will replace the whole line!
        The function returns success is replacment took place.
    """
    import stat
    from tempfile import mkstemp
    fReplaced = False
    logging.debug(
        "_updateFileLine: entry. File: " + str(fileName) +
        " key=" + str(key) +
        " value=" + str(value)
    )

    try:
        #Preserve current file mode
        mode = os.stat(fileName)[stat.ST_MODE]

        #Create temp file
        fh, abs_path = mkstemp()
        new_file = open(abs_path,'w')
        old_file = open(fileName)
        #Iterate over the existing file, while replacing if needed.
        for line in old_file:
            #Note: the line below must not have spaces before or after the '=', since it'll fail bash scripts !
            newLine = re.sub('^[#\s]*%s\s*=.*' % key , '%s=%s' % (key, value), line)
            if re.match('^%s=%s$' % (re.escape(key), re.escape(value)), newLine):
                logging.debug("_updateFileLine: replacing " + str(line) + " with: " + newLine)
                fReplaced = True
                line = newLine
            new_file.write(line)
        new_file.close()
        os.close(fh)
        old_file.close()
        #Move new file
        shutil.move(abs_path, fileName)

        #Restore original file mode
        os.chmod(fileName, mode)
    except:
        try:
            old_file.close()
        except:
            pass
        logging.error("_updateFileLine: error replacing " + str(key) + "=" + str(value))
        logging.error(traceback.format_exc())

    logging.debug("_updateFileLine: return: " + str(fReplaced))
    return fReplaced

#############################################################################################################
# Host bridge functions.
#############################################################################################################

def _getBridgeParams(bridgeName):
    import shlex

    fIsBridgeDevice = False
    lstReturn = []
    fileName = IFACE_CONFIG + bridgeName

    try:
        for line in file(fileName):
            line = line.strip()
            if line.startswith("DEVICE=") or \
               line.startswith("#") or \
               line.startswith("HWADDR="):
                pass
            elif line.startswith("TYPE="):
                t = line.split("=", 1)[1].strip()
                fIsBridgeDevice = (t == "Bridge")
            else:
                try:
                    line = ''.join(shlex.split(line))
                except:
                    logging.warn("_getBridgeParams: failed to read parse line %s", line)
                lstReturn.append(line)
    except Exception, e:
        logging.error("_getBridgeParams: failed to read params of file " + fileName + ".\n Error:" + str(e))
        lstReturn = []

    return lstReturn, fIsBridgeDevice

def _getOvirtBridgeParams(mgtBridge):
    """
        This helper function extract the relevant parameters of the existing
        ovirt bridge in order to re-create it as a managment bridge.
    """
    import netinfo # taken from vdsm rpm
    vlan = ''
    bonding = ''
    nic = None
    nics = []

    try:
        vlan, bonding, nics = netinfo.getVlanBondingNic(mgtBridge)
        nic = nics[0]
    except:
        nic = None
        logging.error("_getOvirtBridgeParams Failed to get bridge data:")
        logging.error(traceback.format_exc())

    return vlan, bonding, nic

def _getRHELBridgeParams(mgtIface):
    """
        This helper function extract the relevant parameters of the existing
        RHEL interface, in order to create a managment bridge.
    """
    import netinfo # taken from vdsm rpm
    vlan = ''
    bonding = ''
    nic = None

    try:
        vlans = netinfo.vlans()
        if mgtIface in vlans:
            nic = netinfo.getVlanDevice(mgtIface)
            vlan = netinfo.getVlanID(mgtIface)
        else:
            nic = mgtIface

        if nic in netinfo.bondings():
            logging.error(
                "_getRHELBridgeParams Found bonding: " +
                str(nic) +
                ". This network configuration is not supported! Please configure rhevm bridge manually and re-install."
            )
            nic = None
    except:
        logging.error("_getRHELBridgeParams Failed to test for VLAN data")
        logging.error(traceback.format_exc())
        nic = None

    return vlan, bonding, nic

def setSafeVdsmNetworkConfig():
    """consider current network configuration as safe and remove its backup"""
    if versionCompare(getOSVersion(), "6.0") < 0:
        shutil.rmtree("/etc/sysconfig/network-scripts/.vdsmback")
    else:
        import glob
        for f in glob.glob("/var/lib/vdsm/netconfback/*"):
            if os.path.isdir(f):
                shutil.rmtree(f)
            else:
                os.remove(f)


def makeBridge(vdcName, vdsmDir):
    """
        Create (for RHEL) or rename (oVirt default bridge) to rhevm bridge.
    """
    logging.debug('makeBridge begin.')
    sys.path.append(vdsmDir)
    try:
        imp.find_module('netinfo') # taken from vdsm rpm
    except ImportError:
        logging.error("makeBridge Faild to find vdsm modules!")
        return False

    fReturn = True
    out = ""
    err = None
    ret = None
    nic = None
    fIsOvirt = isOvirt()

    # get current management interface
    mgtIface = _getMGTIface(vdcName)
    if mgtIface is None:
        fReturn = False
        logging.debug("makeBridge got mgtIface None. This is a routing or resolution issue.")
    else:
        mgtBridge = mgtIface
        if fIsOvirt and mgtIface.startswith('br'):
            mgtIface = mgtIface.replace("br", "", 1) #oVirt naming convention: br + iface

    if fReturn:
        # Read params from current bridge (bootproto, etc)
        Iface = mgtIface
        if fIsOvirt: Iface = mgtBridge
        lstBridgeOptions, fIsBridgeDevice = _getBridgeParams(Iface)

        if len(lstBridgeOptions) == 0:
            logging.error("makeBridge Failed to read existing nic parameters")
            fReturn = False
        elif fIsBridgeDevice and not fIsOvirt:
            logging.error("makeBridge found existing bridge named: " + Iface)
            fReturn = False
        else:
            logging.debug("makeBridge found the following bridge paramaters: " + str(lstBridgeOptions))
            # No more handling GATEWAYDEV.

    if fReturn:
        if fIsOvirt:
            vlan, bonding, nic = _getOvirtBridgeParams(mgtBridge)
        else:
            vlan, bonding, nic = _getRHELBridgeParams(mgtIface)
        fReturn = (nic is not None)

    #Delete existing bridge in oVirt
    if fReturn and fIsOvirt:
        try:
            out, err, ret = _logExec([os.path.join(vdsmDir, SCRIPT_NAME_DEL), mgtBridge, vlan, bonding, nic])
            if ret:
                if ret == 17: #ERR_BAD_BRIDGE
                    logging.debug("makeBridge Ignoring error of del existing bridge. out=" + out + "\nerr=" + str(err) + "\nret=" + str(ret))
                else:
                    fReturn = False
                    logging.debug("makeBridge Failed to del existing bridge. out=" + out + "\nerr=" + str(err) + "\nret=" + str(ret))
        except:
            fReturn = False
            logging.debug("makeBridge Failed to del existing bridge. out=" + out + "\nerr=" + str(err) + "\nret=" + str(ret))

    #Add rhevm bridge
    if fReturn:
        try:
            lstBridgeOptions.append('blockingdhcp=true')
            out, err, ret = _logExec([os.path.join(vdsmDir, SCRIPT_NAME_ADD) , MGT_BRIDGE_NAME, vlan, bonding, nic] + lstBridgeOptions)
            if ret:
                fReturn = False
                logging.debug("makeBridge Failed to add rhevm bridge out=" + out + "\nerr=" + str(err) + "\nret=" + str(ret))
        except:
            fReturn = False
            logging.debug("makeBridge Failed to add rhevm bridge out=" + out + "\nerr=" + str(err) + "\nret=" + str(ret))

    #Save current config by removing the undo files:
    try:
        if fReturn and not fIsOvirt:
            setSafeVdsmNetworkConfig()
    except:
        logging.debug(traceback.format_exc())

    if not fReturn:
        logging.error(
            "makeBridge errored: " +
            " out=" + out +
            "\nerr=" + str(err) +
            "\nret=" + str(ret)
        )

    logging.debug('makeBridge return.')
    return fReturn

#############################################################################################################
# Host package / rpm functions.
#############################################################################################################

def getPackageInfo(pckg_type, rpm_name, op):
    """
        Return an indication if given package name is installed or not.
    """
    strReturn = "FAIL"
    out, err, rc = _logExec([EX_RPM, "-q", rpm_name])
    if rc:
        if op == 'install':
            if pckg_type != "DEVEL":
                strReturn = "FAIL"
                out += err
            else:
                strReturn = "WARN"
        else:
            strReturn = "WARN"
    else:
        strReturn = "OK"

    return strReturn, out

def versionCompare(pkg1, pkg2):
    """
        Return an indication if given package1 is:
        -1: pkg1 < pkg2
        0: pkg1 == pkg2
        1: pkg1 > pkg2
        99 import Exception
    """
    nReturn = 0

    try:
        import rpmUtils
        import rpmUtils.miscutils
    except:
        nReturn = 99

    if nReturn == 0:
        nReturn = rpmUtils.miscutils.compareEVR(
            rpmUtils.miscutils.stringToVersion(pkg1),
            rpmUtils.miscutils.stringToVersion(pkg2)
        )

    return nReturn

def yumCleanCache():
    """
        Clean yum's current cache.
    """
    fReturn = False
    out, err, ret = _logExec([EX_YUM, "clean", "all"] )
    if not ret:
        fReturn = True

    return fReturn

def yumInstallDeleteUpdate(pckgName, action, args=None):
    """
        Call yum to install, delete or update a given package name.
    """
    execFunc = [EX_YUM, "-y"]
    if args is not None:
        execFunc += args

    if action == "install":
        execFunc.append(action)
    elif action == "remove":
        execFunc.append(action)
    else:
        execFunc.append("update")
    execFunc.append(pckgName)

    return _logExec(execFunc)

def installAndVerify(pckgType, pckgName, action, args=None):
    """
        This function uses other module functions to install or update
        a package, and then verify it.
    """
    fReturn = True
    out, err, ret = yumInstallDeleteUpdate(pckgName, action, args=None)
    msg = None
    if not ret:
        fReturn, msg = getPackageInfo(pckgType, pckgName, 'install')
    else:
        fReturn = False
        msg = out + err

    return fReturn, msg

def yumFind(pkgName):
    """
        Returns a list of available packages exists in yum's db.
    """
    import yum
    lReturn = None

    my = yum.YumBase()
    my.preconf.debuglevel = 0 # Remove yum noise
    lReturn = my.pkgSack.searchNevra(name=pkgName)

    return lReturn

def yumSearch(pkgName):
    """
        Returns True is package exists in yum's db.
    """
    fReturn = False

    pkgs = yumFind(pkgName)
    if pkgs and len(pkgs)>0:
        fReturn = True
        logging.debug("yumSearch: found " + str(pkgName) + " entries: " + str(pkgs))
    else:
        logging.debug("yumSearch: package " + str(pkgName) + " not found!")

    return fReturn

def yumSearchVersion(pkgName, ver, startWith=True):
    """
        Returns True is package exists in yum's db with the given version.
        Note: yum internal code has verEQ and verGT. We should use it ASAP.
    """
    fReturn = False

    pkgs = yumFind(pkgName)
    if pkgs and len(pkgs)>0:
        for item in pkgs:
            if startWith:
                if str(item).startswith(ver):
                    fReturn = True
                    logging.debug("yumSearchVersion: pkg " + str(item) + " starts with: " + ver)
                else:
                    logging.debug("yumSearchVersion: pkg " + str(item) + " does not start with: " + ver)
            else:
                if str(item) == ver:
                    fReturn = True
                    logging.debug("yumSearchVersion: pkg " + str(item) + " matches: " + ver)
                else:
                    logging.debug("yumSearchVersion: pkg " + str(item) + " does not match: " + ver)
    else:
        logging.debug("yumSearchVersion: package " + str(pkgName) + " not found!")

    return fReturn

#############################################################################################################
# Host PKI functions.
#############################################################################################################

def _tsDir(confFile):
    import ConfigParser

    config = ConfigParser.ConfigParser()
    config.read(confFile)
    try:
        tsDir = config.get('vars', 'trust_store_path')
    except:
        tsDir = '/etc/pki/vdsm'
    return tsDir

def certPaths(confFile, fAddID=False):
    tsDir = _tsDir(confFile)

    VDSMCERT = tsDir + "/certs/vdsmcert.pem"
    if fAddID:
        VDSMCERT = tsDir + "/certs/vdsm-" + os.environ.get("SSH_CONNECTION").split()[2] + "-cert.pem"
    CACERT = tsDir + "/certs/cacert.pem"

    return CACERT, VDSMCERT

def pkiCleanup(key, cert):
    """
        Removes all the previously installed keys and certificates
    """
    if os.path.exists(key):
        if isOvirt():
            _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_SAFE_DEL_FUNCTION, key])
        else:
            os.unlink(key)

    if os.path.exists(cert):
        if isOvirt():
            _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_SAFE_DEL_FUNCTION, cert])
        else:
            os.unlink(cert)

def _linkOrPersist(src, dst):
    # we have to copy the key and cert since ovirt currently cannot persist
    # softlinks
    if isOvirt():
        shutil.copy2(src, dst)
        st = os.stat(src)
        os.chown(dst, st.st_uid, st.st_gid)
        _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_STORE_FUNCTION, dst])
    else:
        try:
            os.unlink(dst)
        except:
            pass
        os.symlink(src, dst)

def instCert(random_num, confFile):
    """ Install certificate.
    """
    fReturn = True

    try:
        logging.debug("instCert: start. num=" + str(random_num))
        # build semi-random filenames
        cert_pemfile = '/tmp/cert_' + random_num + '.pem'
        ca_pemfile = '/tmp/CA_' + random_num + '.pem'
        gGroup = grp.getgrnam('kvm')
        nGID = gGroup.gr_gid
        uUserInfo = pwd.getpwnam('vdsm')
        nUID = uUserInfo.pw_uid
        CACERT, VDSMCERT = certPaths(confFile)

        # Delete old certificates
        logging.debug("instCert: try to delete old certificates")
        pkiCleanup(VDSMCERT, CACERT)

        logging.debug("instCert: install new certificates")
        # install .pem files
        shutil.copy(cert_pemfile, VDSMCERT)
        os.chown (VDSMCERT, nUID, nGID)
        os.chmod (VDSMCERT, 0444)
        shutil.copy(ca_pemfile, CACERT)
        os.chown (CACERT, nUID, nGID)
        os.chmod (CACERT, 0444)

        if isOvirt():
            # save the certificates
            logging.debug("instCert: persist new certificates")
            out, err, ret = _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_STORE_FUNCTION, VDSMCERT, CACERT])

        ts = _tsDir(confFile)
        VDSMKEY = ts + '/keys/vdsmkey.pem'
        if not os.path.exists(ts + '/libvirt-spice'):
            os.makedirs(ts + '/libvirt-spice')
        _linkOrPersist(CACERT, ts + '/libvirt-spice/ca-cert.pem')
        _linkOrPersist(VDSMCERT, ts + '/libvirt-spice/server-cert.pem')
        _linkOrPersist(VDSMKEY, ts + '/libvirt-spice/server-key.pem')
        if not os.path.exists('/etc/pki/libvirt/private'):
            os.makedirs('/etc/pki/libvirt/private')
        _linkOrPersist(VDSMCERT, '/etc/pki/libvirt/clientcert.pem')
        _linkOrPersist(VDSMKEY, '/etc/pki/libvirt/private/clientkey.pem')
        _linkOrPersist(CACERT, '/etc/pki/CA/cacert.pem')

        print "<BSTRAP component='instCert' status='OK'/>"
        logging.debug("instCert: ended.")
    except:
        fReturn = False
        logging.debug("instCert: failed.", exc_info=True)
        print "<BSTRAP component='instCert' status='FAIL'/>"

    return fReturn

def getSSLSocket(sock):
    """
        Returns ssl socket according to python version
    """
    try:
        import ssl
        return ssl.wrap_socket(sock)
    except ImportError:
        # in python 2.4 importing ssl will fail
        ssl = socket.ssl(sock)
        return httplib.FakeSocket(sock, ssl)

def createCSR(orgName, subject, random_num, tsDir, vdsmKey, dhKey):
    template = """
    RANDFILE               = ~/.rnd
    [ req ]
    distinguished_name     = req_distinguished_name
    prompt                 = no
    [ v3_ca ]
    subjectKeyIdentifier=hash
    authorityKeyIdentifier=keyid:always,issuer:always
    basicConstraints = CA:true
    [ req_distinguished_name ]
    O = %s
    CN = %s
    """ % (repr(orgName), subject)

    req_conffile = '/tmp/req_' + random_num + '.conf'
    cert_reqfile = '/tmp/cert_' + random_num + '.req'
    open(req_conffile, "w").write(template)

    if not os.path.exists(tsDir + "/keys"):
        os.mkdir(tsDir + "/keys")

    if not os.path.exists(tsDir + "/certs"):
        os.mkdir(tsDir + "/certs")

    # create private key
    _logExec([EX_OPENSSL, "genrsa", "-out", vdsmKey, str(DEF_KEY_LEN)])
    # create request for certificate
    execfn = [EX_OPENSSL, "req", "-new", "-key", vdsmKey,
                "-config", req_conffile, "-out", cert_reqfile]
    _logExec(execfn)
    if versionCompare(getOSVersion(), "6.0") < 0:
        gGroup = grp.getgrnam('kvm')
    else:
        gGroup = grp.getgrnam('qemu')
    nGID = gGroup.gr_gid
    uUserInfo = pwd.getpwnam('vdsm')
    nUID = uUserInfo.pw_uid
    os.chown (vdsmKey, nUID, nGID)
    os.chmod (vdsmKey, 0440)

    # openssl dhparam -out dh1024.pem 1024
    _logExec([EX_OPENSSL, "dhparam", "-out", dhKey, str(DEF_KEY_LEN)])
    os.chown (dhKey, nUID, nGID)
    os.chmod (dhKey, 0440)

    if isOvirt():
        # save the certificates
        out, err, ret = _logExec([EX_BASH, EX_OVIRT_FUNTIONS, OVIRT_STORE_FUNCTION, vdsmKey, dhKey])

def _cpuid(func):
    f = file('/dev/cpu/0/cpuid')
    f.seek(func)
    return struct.unpack('IIII', f.read(16))

def _prdmsr(cpu, index):
    f = file("/dev/cpu/%d/msr" % cpu)
    f.seek(index)
    try:
        return struct.unpack('L', f.read(8))[0]
    except:
        return -1

def _cpu_has_vmx_support():
    eax, ebx, ecx, edx = _cpuid(1)
    # CPUID.1:ECX.VMX[bit 5] -> VT
    return ecx & (1 << 5) != 0

def _vmx_enabled_by_bios():
    MSR_IA32_FEATURE_CONTROL = 0x3a
    MSR_IA32_FEATURE_CONTROL_LOCKED = 0x1
    MSR_IA32_FEATURE_CONTROL_VMXON_ENABLED = 0x4

    msr = _prdmsr(0, MSR_IA32_FEATURE_CONTROL);
    return (msr & (MSR_IA32_FEATURE_CONTROL_LOCKED |
                   MSR_IA32_FEATURE_CONTROL_VMXON_ENABLED)) != MSR_IA32_FEATURE_CONTROL_LOCKED

def _cpu_has_svm_support():
    SVM_CPUID_FEATURE_SHIFT = 2
    SVM_CPUID_FUNC = 0x8000000a

    eax, ebx, ecx, edx = _cpuid(0x80000000)
    if eax < SVM_CPUID_FUNC:
        return 0

    eax, ebx, ecx, edx = _cpuid(0x80000001)
    if not (ecx & (1 << SVM_CPUID_FEATURE_SHIFT)):
        return 0
    return 1

def _svm_enabled_by_bios():
    SVM_VM_CR_SVM_DISABLE = 4
    MSR_VM_CR = 0xc0010114

    vm_cr = _prdmsr(0, MSR_VM_CR)
    if vm_cr & (1 << SVM_VM_CR_SVM_DISABLE):
        return 0
    return 1

def cpuVendorID():
    for line in file('/proc/cpuinfo').readlines():
        if ':' in line:
            k, v = line.split(':', 1)
            k = k.strip()
            v = v.strip()
        if k == 'vendor_id':
            if v == 'GenuineIntel':
                return v
            elif v == 'AuthenticAMD':
                return v
    return ''

def virtEnabledInCpuAndBios():
    try:
        vendor = cpuVendorID()
        logging.debug('CPU vendor is %s', vendor)

        if vendor == 'GenuineIntel':
            bios_en = _vmx_enabled_by_bios()
            has_cpu = _cpu_has_vmx_support();
        elif vendor == 'AuthenticAMD':
            bios_en = _svm_enabled_by_bios();
            has_cpu = _cpu_has_svm_support();
        else:
            return False

        logging.debug('virt support in cpu: %s, in bios: %s', has_cpu, bios_en)
        return bios_en and has_cpu
    except:
        logging.error(traceback.format_exc())
        return False