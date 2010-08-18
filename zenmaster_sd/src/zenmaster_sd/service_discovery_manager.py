#!/usr/bin/env python
# Software License Agreement (BSD License)
#
# Copyright (c) 2010, Jon Fink
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions
# are met:
#
#  * Redistributions of source code must retain the above copyright
#    notice, this list of conditions and the following disclaimer.
#  * Redistributions in binary form must reproduce the above
#    copyright notice, this list of conditions and the following
#    disclaimer in the documentation and/or other materials provided
#    with the distribution.
#  * The name of the author may not be used to endorse or promote
#    products derived from this software without specific prior written
#    permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS
# FOR A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE
# COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT,
# INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING,
# BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
# LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN
# ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.
#

import getopt
import logging
import os
import string
import sys
import time

USE_BONJOUR=False
if sys.platform == 'darwin':
    USE_BONJOUR=True

import select

if USE_BONJOUR:
    import pybonjour
else:
    import pybonjour # Only use for txtRecords
    import dbus, gobject, avahi
    gobject.threads_init()
    from dbus import DBusException
    from dbus.mainloop.glib import DBusGMainLoop

import threading

class ServiceDiscoveryManagerBase(threading.Thread):
    def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _name='ROS Master', _data='', _timeout=2.0, _freq=1.0):
        self.register_name = _name
        self.data = _data
        self.regtype = _regtype
        self.port = _port
        self.freq = _freq
        self.timeout = _timeout
        self.resolved = []
        self.setup()
        threading.Thread.__init__(self)
        
        self.remote_services_lock = threading.Lock()
        self.remote_services = {}

    def get_remote_services(self):
        self.remote_services_lock.acquire()
        copy = self.remote_services
        self.remote_services_lock.release()
        return copy

    def add_remote_service(self, name, hosttarget, port, txtRecord):
        uri = 'http://%s:%d/' % (hosttarget, port)
        self.remote_services_lock.acquire()
        self.remote_services[name]=uri
        print self.remote_services.keys()
        self.remote_services_lock.release()
        return uri

    def remove_remote_service(self, name):
        self.remote_services_lock.acquire()
        if self.remote_services.has_key(name):
            self.remote_services.pop(name)
        print self.remote_services.keys()
        self.remote_services_lock.release()

    def isServiceKnown(self, name, regtype, domain):
        service_known = False
        self.remote_services_lock.acquire()
        service_known = self.remote_services.has_key(name+'.'+regtype+domain)
        self.remote_services_lock.release()
        
        return service_known
        
if USE_BONJOUR:
    class ServiceDiscoveryManager(ServiceDiscoveryManagerBase):
        def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _name='ROS Master', _data={}, _timeout=2.0, _freq=1.0):
            data = pybonjour.TXTRecord(_data)
            ServiceDiscoveryManagerBase.__init__(self, _regtype, _port, _name, data, _timeout, _freq)

        def _shutdown(self):
            self.sdRef.close()

        def stop(self):
            self.run_flag = False

        def run(self):
            self.run_flag = True

            while self.run_flag:
                ready = select.select([self.sdRef, self.browse_sdRef], [], [], 1.0/self.freq)
                if self.sdRef in ready[0]:
                    pybonjour.DNSServiceProcessResult(self.sdRef)
                if self.browse_sdRef in ready[0]:
                    pybonjour.DNSServiceProcessResult(self.browse_sdRef)        

                # syncronize 

        def setup(self):
            self.sdRef = pybonjour.DNSServiceRegister(name=self.register_name,
                                                      regtype = self.regtype,
                                                      port = self.port,
                                                      txtRecord = self.data,
                                                      callBack = self.register_callback)

            self.browse_sdRef = pybonjour.DNSServiceBrowse(regtype = self.regtype,
                                                           callBack = self.browse_callback)


        def register_callback(self, sdRef, flags, errorCode, name, regtype, domain):
            if errorCode == pybonjour.kDNSServiceErr_NoError:
                print 'Registered service: %s, %s, %s' % (name, regtype, domain)

        def browse_callback(self, sdRef, flags, interfaceIndex, errorCode, serviceName,
                                regtype, replyDomain):
            if errorCode != pybonjour.kDNSServiceErr_NoError:
                return

            if not (flags & pybonjour.kDNSServiceFlagsAdd):
                self.remote_services_lock.acquire()
                if self.remote_services.has_key(serviceName+'.'+regtype+replyDomain):
                    self.remote_services.pop(serviceName+'.'+regtype+replyDomain)
                print self.remote_services.keys()
                self.remote_services_lock.release()
                return

            if self.isServiceKnown(serviceName, regtype, replyDomain):
                return


            resolve_sdRef = pybonjour.DNSServiceResolve(0,
                                                        interfaceIndex,
                                                        serviceName,
                                                        regtype,
                                                        replyDomain,
                                                        self.resolve_callback)
            try:
                while not self.resolved:
                    try:
                        ready = select.select([resolve_sdRef], [], [], self.timeout)
                    except KeyboardInterrupt:
                        pass
                    if resolve_sdRef not in ready[0]:
                        print 'Resolve timed out'
                        break
                    pybonjour.DNSServiceProcessResult(resolve_sdRef)
                else:
                    self.resolved.pop()
            finally:
                resolve_sdRef.close()

        def resolve_callback(self, sdRef, flags, interfaceIndex, errorCode, fullname,
                                 hosttarget, port, txtRecord):
            if errorCode == pybonjour.kDNSServiceErr_NoError:
                self.resolved.append(True)
                print 'Resolved service: %s, %s, %s' % (fullname, hosttarget, port)
                self.add_remote_service(fullname, hosttarget, port, pybonjour.TXTRecord().parse(data=txtRecord))

else:
    class ServiceDiscoveryManager(ServiceDiscoveryManagerBase):
        def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _name='ROS Master', _data={}, _timeout=2.0, _freq=1.0):
            data = []
            for k in _data.keys():
                data.append(str(k)+'='+str(_data[k]))

            ServiceDiscoveryManagerBase.__init__(self, _regtype, _port, _name, data, _timeout, _freq)

            self.group = None

        def _shutdown(self):
            if self.group != None:
                self.group.Reset()

        def stop(self):
            if self.group != None:
                self.group.Reset()
                self.group = None

            self.run_flag = False
            self.loop.quit()
            
        def run(self):
            self.run_flag = True
            self.loop.run()

        def setup(self):
            loop = DBusGMainLoop()
            bus = dbus.SystemBus(mainloop=loop)

            # Advertise self.regtype service
            server = dbus.Interface(bus.get_object(avahi.DBUS_NAME,
                                                   avahi.DBUS_PATH_SERVER),
                                    avahi.DBUS_INTERFACE_SERVER)

            g = dbus.Interface(bus.get_object(avahi.DBUS_NAME,
                                              server.EntryGroupNew()),
                               avahi.DBUS_INTERFACE_ENTRY_GROUP)

            g.AddService(avahi.IF_UNSPEC, avahi.PROTO_UNSPEC, dbus.UInt32(0),
                         self.register_name, self.regtype, "", "", 
                         dbus.UInt16(self.port), self.data)
            g.Commit()


            # Look for self.regtype services
            browser = dbus.Interface(bus.get_object(avahi.DBUS_NAME,
                                                    server.ServiceBrowserNew(avahi.IF_UNSPEC, avahi.PROTO_UNSPEC, 
                                                                             self.regtype, "", dbus.UInt32(0))),
                                     avahi.DBUS_INTERFACE_SERVICE_BROWSER)
            browser.connect_to_signal("ItemNew", self.add_service_handler)
            browser.connect_to_signal("ItemRemove", self.remove_service_handler)

            self.group = g
            self.server = server
            self.bus = bus
            self.browser = browser
            self.loop = gobject.MainLoop()

        def service_resolved(self, interface, protocol, name, regtype, 
                             domain, host, aprotocol, address, port, txtRecord, flags, *extra_args):
            text = {}
            for i in txtRecord:
                x = "".join((chr(c) for c in i))
                xsplit = x.split("=")
                if len(xsplit) == 2:
                    text[xsplit[0]] = xsplit[1]

            print 'Resolved service: %s, %s, %s (%s)' % (name, host, port, text)

            self.add_remote_service(str(name)+'.'+str(regtype)+'.'+str(domain), str(host), int(port), text)

        def print_error(self, *args):
            print 'error_handler'
            print args[0]

        def add_service_handler(self, interface, protocol, name, stype, domain, flags):
            print "Found service '%s' type '%s' domain '%s' " % (name, stype, domain)

            if flags & avahi.LOOKUP_RESULT_LOCAL:
                # skip local service
                print "Skipping local service"
                return

            if self.isServiceKnown(name, stype, domain):
                return

            self.server.ResolveService(interface, protocol, name, stype, domain, avahi.PROTO_UNSPEC, dbus.UInt32(0),
                                       reply_handler=self.service_resolved, error_handler=self.print_error)

        def remove_service_handler(self, interface, protocol, name, stype, domain, flags):
            print "Remove service '%s' type '%s' domain '%s' " % (name, stype, domain)

            if flags & avahi.LOOKUP_RESULT_LOCAL:
                # skip local service
                print "Skipping local service"
                #return

            self.remove_remote_service(str(name)+'.'+str(stype)+'.'+str(domain))


if __name__=='__main__':
    print 'Press Ctrl+C to kill'
    data = {'master_uri':'http://localhost'}
    sd = ServiceDiscoveryManager(_data=data)
    sd.start()

    try:
        try:
            while True:
                pass
        except KeyboardInterrupt:
            pass
    finally:
        sd.stop()
        if sd.isAlive():
            sd.join()            
