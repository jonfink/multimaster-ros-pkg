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

from service_discovery_manager import *

class ROSMasterDiscoveryManager(ServiceDiscoveryManager):
    def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _master_uri=None, _timeout=2.0, _freq=1.0, new_master_callback=None):
        self.new_master_callback = new_master_callback
        self.master_uri = _master_uri
        self.service_name = self.master_uri
        if self.service_name == None:
            self.service_name = 'ROS Master'

        data = {'master_uri':self.master_uri}
        ServiceDiscoveryManager.__init__(self, _name=self.service_name, _regtype=_regtype, _port=_port, _data=data, _timeout=_timeout, _freq=_freq)

    def add_remote_service(self, name, hosttarget, port, txtRecord):
        remote_master_uri = None
        try:
            remote_master_uri = txtRecord['master_uri']
        except KeyError:
            pass

        if remote_master_uri and (remote_master_uri == self.master_uri):
            return

        uri = ServiceDiscoveryManager.add_remote_service(self, name, hosttarget, port, txtRecord)
        if self.new_master_callback:
            self.new_master_callback(uri)

