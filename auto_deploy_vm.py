#!/usr/bin/python2.7
# -*- coding:utf-8 -*-

import os
import re
import sys
import uuid
import logging
import libvirt
import argparse
import commands
import ConfigParser
from xml.sax.saxutils import escape
from xml.etree.ElementTree import ( Element,
                                    SubElement,
                                    Comment,
                                    tostring,
                                    XML,
                                  )

LIBVIRTURL = 'qemu:///system'
TFTPROOT = '/var/lib/tftpboot'
DOMAINNM = 'mydomain.com'
LOGDIR = '/tmp/'
OS_VERSION = 'centos7'
CONFILE='./vauto.conf'
STORAGEDOMAINPATH='/home/vauto/vms'

logging.basicConfig(level = logging.DEBUG,
                format='[%(asctime)s]:[%(filename)s][%(levelname)s] %(message)s',
                datefmt='%a, %d %b %Y %H:%M:%S',
                filename='%s/%s.log' %(LOGDIR, OS_VERSION),
                filemode='w')

def __getConn():
    """
    Connect to the hypervisor.
    """
    return libvirt.open(LIBVIRTURL)

def __activeStrD(store):
    """
    Capture and log the execption during active vauto storage domain
    """
    try:
        store.create()
    except libvirt.libvirtError, e:
        logging.error("Cannot activate the vauto storage domain")
        errExit('', 1)
    store.setAutostart(True)
    
def __activeNet(net):
    """
    Capture and log the exception during active vauto network
    """
    try:
        net.create()
    except libvirt.libvirtError, e:
        logging.error("Cannot activate the vauto network")
        errExit('', 1)
    net.setAutostart(True)

def __eElement(tagName, text=None, **attrs):
    elem = Element(tagName)
    if text:
        elem.text = escape(text)
    if attrs:
       for attr,value in attrs.iteritems():
           elem.set(attr, escape(str(value)))
    return elem

def errExit(msg, exstat):
    """
    Exit program
    """
    if msg:
        print msg
    sys.exit(exstat)

def randomMAC():
    """
    Generate the random MAC address for QEMU
    """
    oui = [ 0x52, 0x54, 0x00 ]
    mac = oui + [
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff),
        random.randint(0x00, 0xff)]
    return ':'.join(map(lambda x: "%02x" % x, mac))

def createStrdomainDir():
    """
    Create the vauto Stroage Domain default directory
    """
    cmdstatus, cmdoutput = commands.getstatusoutput("/bin/df -h --output=avail --block-size=G /home  | /bin/grep G")
    cmdstatus, cmdoutput = commands.getstatusoutput("/bin/df --output=size,used,avail --block-size=K /home | /bin/tail -1 | /bin/sed 's/ //g'")
    if cmdstatus:
        logging.error("Failed to run df -h.")
        errExit('', 1)
    else:
       volcapacity = cmdoutput.split('K')
       volcapacity.remove('')
       partsize = volcapacity[2].strip()
       if partsize <= 20 * 1024 * 1024:
           logging.error("There is not enough space in %s for testing, available space must greater than 20G." % STORAGEDOMAINPATH)
           errExit('', 1)
       else:
           if os.path.isdir(STORAGEDOMAINPATH):
               # 'mode' should be an integer representing an octal mode (eg int('755', 8) --> 493)
               if stat.S_IMODE(os.stat(STORAGEDOMAINPATH).st_mode) != 511:
                   os.chmod(STORAGEDOMAINPATH, 0o777)
           else:
               os.makedirs(STORAGEDOMAINPATH, 0o777)
    return [ int(cap.strip()) * 1024 for cap in volcapacity ]

def findNatsubNetwork():
    """
    Find a suitable network segment for vauto nat Netowork
    """
    ipsubnet = "192.168."
    i = 10
    while True:
        cmdstatus, cmdoutput = commands.getstatusoutput("/sbin/ifconfig -a | /bin/grep -w inet | /bin/awk -F' ' '{print $2}' | grep '%s%s' " % (ipsubnet.replace('.', '\.'), str(i) + '\.'))
        if cmdstatus:
           break
        else:
           i += 2
    return [ipsubnet + str(i) + sub for sub in [".1", ".2", ".254" ]]
           
def addDHCPEntry(net, xml):
    """
    Add the DHCP entry for VM
    """
    logging.debug("Add the dhcp entry %s." % xml)
    return net.update(libvirt.VIR_NETWORK_UPDATE_COMMAND_ADD_LAST, libvirt.VIR_NETWORK_SECTION_IP_DHCP_HOST, -1 ,xml,0)

def delDHCPEntry(net, xml):
    """
    Delete the DHCP entry for VM
    """
    logging.debug("Delete the dhcp entry %s." % xml)
    return net.update(libvirt.VIR_NETWORK_UPDATE_COMMAND_DELETE, libvirt.VIR_NETWORK_SECTION_IP_DHCP_HOST, -1 ,xml,0)

def defineStorageDomainXML(storename):
    """
    Create vauto Storage Domain XML
    """
    volsize = createStrdomainDir()
    root = __eElement('pool', type='dir')
    root.append(
        Commnet('Generate by vauto.py, you can modify using: virsh pool-edit vauto')
        )

    root.append(__eElement('name', storename))
    root.append(__eElement('uuid', str(uuid.uuid1())))
    root.append(__eElement('capacity', str(volsize[0]), unit='bytes'))
    root.append(__eElement('allocation', str(volsize[1]), unit='bytes'))
    root.append(__eElement('available',str(volsize[2]), unit='bytes'))
    elemsrc = __eElement('source')
    root.append(elemsrc)
    elemtrgt = __eElement('target')
    elempath = __eElement('path', STORAGEDOMAINPATH)
    elemtrgt.append(elempath)
    elemper = XML('<permissions><mode>0755</mode><owner>-1</owner><group>-1</group></permissions>')
    elemtrgt.append(elemper)
    root.append(elemtrgt)

    return tostring(root)

def defineNetworkXML(netName):
    """
    Create vauto nat Network XML
    """
    root = Element('network')
    root.append(
        Comment('Generate by vauto.py, you can modify using: virsh net-edit vauto')
        )

    root.append(__eElement('name', netName))
    root.append(__eElement('uuid', str(uuid.uuid1())))
    root.append(__eElement('forward', mode='nat'))
    root.append(__eElement('bridge', name='vautonet0', stp='on', delay='0'))
    root.append(__eElement('mac', address=randomMAC()))
    subnet = findNatsubNetwork()
    elemIP = __eElement('ip', address=subnet[0], netmask='255.255.255.0')
    elemdhcp = __eElement('dhcp')
    elemdhcp.append(__eElement('range', start=subnet[1], end=subnet[2]))
    elemdhcp.append(__eElement('bootp', file='pxelinux.0', server=subnet[0]))
    elemIP.append(elemdhcp)
    root.append(elemIP)

    return tostring(root)

def createStorage(conn):
    """
    Create vauto storage domain if necessory
    """
    try:
       store = conn.storagePoolLookupByName('vauto')
    except libvirt.libvirtError, e:
       logging.warn("Cannot fine vauto storage domain")
       store = None

    if store is None:
       strxml = defineStorageDomainXML('vauto')
       strdef = conn.storagePoolDefineXML(strxml)
       __activeStrD(strdef)
    if not store.isActive():
       __activeStrD(store)

def createNetwork(conn):
    """
    Create vauto nat network
    """ 
    try:
        net = conn.networkLookupByName('vauto')
    except libvirt.libvirtError, e:
        logging.warn("Cannot find vauto network.")
        net = None

    if net is None:
        netxml = defineNetworkXML('vauto')
        netdef = conn.networkDefineXML(netxml)
        __activeNet(netdef)
    if not net.isActive():
        __activeNet(net)

def removeNetwork(conn):
    """
    Remove vauto nat network
    """
    try:
        net =  conn.networkLookupByName('vauto')
    except libvirt.libvirtError, e:
        logging.warn("Cannot find vauto network.")
        return
    if net.isActive():
        net.destroy()
    if net.isPersistent():
        net.undefine()

def parseArgs():
    parser = argparse.ArgumentParser(usage='./vauto.py [option]', description='VAuto is an auto testing tool')
    parser.add_argument('--config-network', action = 'store_true', default = False, dest = 'confvautonet', help='Configure the vauto network') 
    parser.add_argument('--config-storage', action = 'store_true', default = False, dest = 'confvautostr', help='Configure the vauto storage') 
    args = parser.parse_args()

    return args

def main():
    # Check user role
    if os.geteuid() != 0:
        logging.error("Failed to run this script by non-root users.")
        errExit("Must be run as root. Aborting.", 1)

    args = parseArgs()
    conn = __getConn()


if __name__ == "__main__":
    main()
