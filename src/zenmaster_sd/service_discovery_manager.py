#!/usr/bin/env python

import getopt
import logging
import os
import string
import sys
import time

import select
import pybonjour
import threading

class ServiceDiscoveryManager(threading.Thread):
    def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _name=None, _data='', _timeout=2.0, _freq=1.0):
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

    def _shutdown(self):
        self.sdRef.close()

    def stop(self):
        self.run_flag = False

    def get_remote_services(self):
        self.remote_services_lock.acquire()
        copy = self.remote_services
        self.remote_services_lock.release()
        return copy

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

        service_known = False
        self.remote_services_lock.acquire()
        service_known = self.remote_services.has_key(serviceName+'.'+regtype+replyDomain)
        self.remote_services_lock.release()

        if service_known:
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
            self.add_remote_service(fullname, hosttarget, port, txtRecord)

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

if __name__=='__main__':
    sd = ServiceDiscoveryManager()
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
