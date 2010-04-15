# Software License Agreement (BSD License)
#
# Copyright (c) 2008, Willow Garage, Inc.
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
#  * Neither the name of Willow Garage, Inc. nor the names of its
#    contributors may be used to endorse or promote products derived
#    from this software without specific prior written permission.
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
# Copyright (c) 2008, Willow Garage, Inc.
# Revision $Id: zenmaster.py 6875 2009-11-12 21:10:24Z kwc $

"""Command-line handler for ROS zenmaster (Python Master)"""

import getopt
import logging
import os
import string
import sys
import time

import rospy
import rospy.masterslave 
from rospy.masterslave import *

from rospy.init import DEFAULT_NODE_PORT, DEFAULT_MASTER_PORT

# Environment variables used to configure master/slave

from roslib.rosenv import ROS_ROOT, ROS_MASTER_URI, ROS_HOSTNAME, ROS_NAMESPACE, ROS_PACKAGE_PATH, ROS_LOG_DIR

from service_discovery_manager import *

class ROSMasterDiscoveryManager(ServiceDiscoveryManager):
    def __init__(self, _regtype='_rosmaster._tcp', _port=11311, _master_uri=None, _timeout=2.0, _freq=1.0, new_master_callback=None):
        self.new_master_callback = new_master_callback
        self.master_uri = _master_uri
        data = pybonjour.TXTRecord({'master_uri': self.master_uri})
        ServiceDiscoveryManager.__init__(self, _regtype=_regtype, _port=_port, _data=data, _timeout=_timeout, _freq=_freq)

    def add_remote_service(self, name, hosttarget, port, txtRecord):
        remote_master_uri = None
        try:
            remote_master_uri = pybonjour.TXTRecord().parse(data=txtRecord)['master_uri']
        except KeyError:
            pass

        if remote_master_uri and (remote_master_uri == self.master_uri):
            return

        uri = ServiceDiscoveryManager.add_remote_service(self, name, hosttarget, port, txtRecord)
        if self.new_master_callback:
            self.new_master_callback(uri)

class ROSMasterHandlerSD(ROSHandler):
    """
    XML-RPC handler for ROS master APIs.
    API routines for the ROS Master Node. The Master Node is a
    superset of the Slave Node and contains additional API methods for
    creating and monitoring a graph of slave nodes.
##
    By convention, ROS nodes take in caller_id as the first parameter
    of any API call.  The setting of this parameter is rarely done by
    client code as ros::msproxy::MasterProxy automatically inserts
    this parameter (see ros::client::getMaster()).
    """
    
    def __init__(self):
        """ctor."""
        super(ROSMasterHandlerSD, self).__init__(MASTER_NAME, None, False)
        self.thread_pool = rospy.threadpool.MarkedThreadPool(NUM_WORKERS)
        # pub/sub/providers: dict { topicName : [publishers/subscribers names] }
        self.ps_lock = threading.Condition(threading.Lock())

        self.reg_manager = RegistrationManager(self.thread_pool)

        # maintain refs to reg_manager fields
        self.publishers  = self.reg_manager.publishers
        self.subscribers = self.reg_manager.subscribers
        self.services = self.reg_manager.services
        self.param_subscribers = self.reg_manager.param_subscribers
        
        self.topics_types = {} #dict { topicName : type }

        self.sd_name = '_rosmaster._tcp'

        self.whitelist_topics = []
        self.whitelist_services = []
        self.whitelist_params = []

        self.blacklist_topics = ['/clock', '/rosout', '/rosout_agg', '/time']
        self.blacklist_services = ['/rosout/get_loggers', '/rosout/set_logger_level']
        self.blacklist_params = ['/run_id']

        ## parameter server dictionary
        self.param_server = rospy.paramserver.ParamDictionary(self.reg_manager)

        self.sd = None

        self.last_master_activity_time = time.time()

    def _shutdown(self, reason=''):
        if self.sd is not None:
            self.sd.stop()
            if self.sd.isAlive():
                self.sd.join()
        
        if self.thread_pool is not None:
            self.thread_pool.join_all(wait_for_tasks=False, wait_for_threads=False)
            self.thread_pool = None

        return super(ROSMasterHandlerSD, self)._shutdown(reason)

    def _valid_topic(self, topic):
        if len(self.whitelist_topics) == 0:
            return not self._blacklisted_topic(topic)
        d = ','
        return (d.join(self.whitelist_topics).find(topic) >= 0)
                       
    def _valid_service(self, service):
        if len(self.whitelist_services) == 0:
            return not self._blacklisted_service(service)
        d = ','
        return (d.join(self.whitelist_services).find(service) >= 0)

    def _valid_param(self, param):
        if len(self.whitelist_params) == 0:
            return not self._blacklisted_param(param)
        d = ','
        return (d.join(self.whitelist_params).find(param) >= 0)

    def _blacklisted_topic(self, topic):
        d = ','
        return (d.join(self.blacklist_topics).find(topic) >= 0)

    def _blacklisted_service(self, service):
        d = ','
        return (d.join(self.blacklist_services).find(service) >= 0)

    def _blacklisted_param(self, key):
        d = ','
        return (d.join(self.blacklist_params).find(key) >= 0)

    def read_params(self):
        if self.param_server.has_param('/sd_name'):
            self.sd_name = self.param_server.get_param('/sd_name')
            print 'Setting sd_name: %s' % (self.sd_name)

        if self.param_server.has_param('/blackist_topics'):
            blacklist_topics_str = self.param_server.get_param('/blacklist_topics')
            self.blacklist_topics.extend(blacklist_topics_str.split(','))
            self.blacklist_topics = list(set(self.blacklist_topics))
            
        if self.param_server.has_param('/blacklist_services'):
            blacklist_services_str = self.param_server.get_param('/blacklist_services')
            self.blacklist_services.extend(blacklist_services_str.split(','))
            self.blacklist_services = list(set(self.blacklist_services))
            
        if self.param_server.has_param('/blacklist_params'):
            blacklist_params_str = self.param_server.get_param('/blacklist_params')
            self.blacklist_params.extend(blacklist_params_str.split(','))
            self.blacklist_params = list(set(self.blacklist_params))

        if self.param_server.has_param('/whitelist_topics'):
            whitelist_topics_str = self.param_server.get_param('/whitelist_topics')
            self.whitelist_topics.extend(whitelist_topics_str.split(','))
            self.whitelist_topics = list(set(self.whitelist_topics))
            
        if self.param_server.has_param('/whitelist_services'):
            whitelist_services_str = self.param_server.get_param('/whitelist_services')
            self.whitelist_services.extend(whitelist_services_str.split(','))
            self.whitelist_services = list(set(self.whitelist_services))
            
        if self.param_server.has_param('/whitelist_params'):
            whitelist_params_str = self.param_server.get_param('/whitelist_params')
            self.whitelist_params.extend(whitelist_params_str.split(','))
            self.whitelist_params = list(set(self.whitelist_params))

    def start_service_discovery(self, local_master_uri):
        self.read_params()
        
        self.sd = ROSMasterDiscoveryManager(self.sd_name, 11311, _master_uri=local_master_uri, new_master_callback=self.new_master_callback)

        self.sd.start()

    def new_master_callback(self, remote_master_uri):
        state = self.getSystemState(remote_master_uri)
        publishers = state[2][0]
        subscribers = state[2][1]
        services = state[2][2]

        #master = xmlrpcapi(remote_master_uri)
        master = xmlrpclib.MultiCall(xmlrpclib.ServerProxy(remote_master_uri))

        for topic in publishers:
            topic_name = topic[0]
            topic_prefix = '/'
            if not self._valid_topic(topic_name):
                continue
            for publisher in topic[1]:
                (ret, msg, publisher_uri) = self.lookupNode(remote_master_uri, publisher)
                if ret == 1:
                    args = (publisher, topic_prefix+topic_name.lstrip('/'), self.topics_types[topic_name], publisher_uri)
                    #print 'Calling remoteRegisterPublisher(%s, %s, %s, %s)' % args
                    master.remoteRegisterPublisher(*args)

        for topic in subscribers:
            topic_name = topic[0]
            if not self._valid_topic(topic_name):
               continue
            for subscriber in topic[1]:
                (ret, msg, subscriber_uri) = self.lookupNode(remote_master_uri, subscriber)
                if ret == 1 and self.topics_types.has_key(topic_name):
                    args = (subscriber, topic_name, self.topics_types[topic_name], subscriber_uri)
                    #print 'Calling remoteRegisterSubscriber(%s, %s, %s, %s)' % args
                    master.remoteRegisterSubscriber(*args)

        for service in services:
            service_name = service[0]
            if not self._valid_service(service_name):
                continue
            for provider in service[1]:
                (ret, msg, provider_uri) = self.lookupNode(remote_master_uri, provider)
                (ret, msg, service_uri) = self.lookupService(remote_master_uri, service_name)
                if ret == 1:
                    args = (provider, service_name, service_uri, provider_uri)
                    #print 'Calling remoteRegisterService(%s, %s, %s, %s)' % args
                    master.remoteRegisterService(*args)

        param_names = self.param_server.get_param_names()

        for key in param_names:
            if not self._valid_param(key):
                continue
            value=self.param_server.get_param(key)
            #print 'setting up for remoteSetParams (%s, %s)' % (key, remoteParamDict[key])
            args = (remote_master_uri, key, value)
            master.remoteSetParam(*args)

        result = master()

    @apivalidate('')
    def getMasterUri(self, caller_id): #override super behavior
        """
        Get the URI of the master(this) node.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @return: [code, msg, masterUri]
        @rtype: [int, str, str]
        """
        return self.getUri(caller_id)

    ## static map for tracking which arguments to a function should be remapped
    ## { methodName : [ arg indices ]
    _mremap_table = { } 

    @classmethod
    def remappings(cls, method_name):
        """
        @internal
        @return list: parameters (by pos) that should be remapped because they are names
        """
        if method_name in cls._mremap_table:
            return cls._mremap_table[method_name]
        else:
            return ROSHandler.remappings(method_name)

    ################################################################
    # PARAMETER SERVER ROUTINES
    
    _mremap_table['deleteParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'),))
    def deleteParam(self, caller_id, key):
        """
        Parameter Server: delete parameter
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param key: parameter name
        @type  key: str
        @return: [code, msg, 0]
        @rtype: [int, str, int]
        """
        try:
            key = resolve_name(key, caller_id)
            self.param_server.delete_param(key, self._notify_param_subscribers)
            mloginfo("-PARAM [%s] by %s",key, caller_id) 

            if self._valid_param(key):
                args = (caller_id, key)
                if self.sd is not None:
                    remote_master_uri = self.sd.get_remote_services().values()
                    for m in remote_master_uri:
                        master = xmlrpcapi(m)
                        code, msg, val = master.remoteDeleteParam(*args)
                        if code != 1:
                            logwarn("unable to delete param [%s] on master %s: %s" % (key, m, msg))
           
            return  1, "parameter %s deleted"%key, 0                
        except KeyError, e:
            return -1, "parameter [%s] is not set"%key, 0

    _mremap_table['remoteDeleteParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'),))
    def remoteDeleteParam(self, caller_id, key):
        """
        Parameter Server: delete parameter on remote master
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param key: parameter name
        @type  key: str
        @return: [code, msg, 0]
        @rtype: [int, str, int]
        """
        try:
            key = resolve_name(key, caller_id)
            self.param_server.delete_param(key, self._notify_param_subscribers)
            mloginfo("-PARAM [%s] by %s",key, caller_id)            
            return  1, "parameter %s deleted"%key, 0                
        except KeyError, e:
            return -1, "parameter [%s] is not set"%key, 0

    _mremap_table['setParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'), not_none('value')))
    def setParam(self, caller_id, key, value):
        """
        Parameter Server: set parameter.  NOTE: if value is a
        dictionary it will be treated as a parameter tree, where key
        is the parameter namespace. For example:::
          {'x':1,'y':2,'sub':{'z':3}}

        will set key/x=1, key/y=2, and key/sub/z=3. Furthermore, it
        will replace all existing parameters in the key parameter
        namespace with the parameters in value. You must set
        parameters individually if you wish to perform a union update.
        
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param key: parameter name
        @type  key: str
        @param value: parameter value.
        @type  value: XMLRPCLegalValue
        @return: [code, msg, 0]
        @rtype: [int, str, int]
        """
        key = resolve_name(key, caller_id)
        self.param_server.set_param(key, value, self._notify_param_subscribers)
        mloginfo("+PARAM [%s] by %s",key, caller_id)

        if self._valid_param(key):
            args = (caller_id, key, value)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                for m in remote_master_uri:
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteSetParam(*args)
                    if code != 1:
                        logwarn("unable to set param [%s] on master %s: %s" % (key, m, msg))

        self.last_master_activity_time = time.time()
        return 1, "parameter %s set"%key, 0

    _mremap_table['remoteSetParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'), not_none('value')))
    def remoteSetParam(self, caller_id, key, value):
        """
        Parameter Server: set parameter on remote master. 
        NOTE: if value is a
        dictionary it will be treated as a parameter tree, where key
        is the parameter namespace. For example:::
          {'x':1,'y':2,'sub':{'z':3}}

        will set key/x=1, key/y=2, and key/sub/z=3. Furthermore, it
        will replace all existing parameters in the key parameter
        namespace with the parameters in value. You must set
        parameters individually if you wish to perform a union update.
        
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param key: parameter name
        @type  key: str
        @param value: parameter value.
        @type  value: XMLRPCLegalValue
        @return: [code, msg, 0]
        @rtype: [int, str, int]
        """
        key = resolve_name(key, caller_id)
        self.param_server.set_param(key, value, self._notify_param_subscribers)
        mloginfo("+PARAM [%s] by %s",key, caller_id)
        return 1, "parameter %s set"%key, 0

    _mremap_table['getParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'),))
    def getParam(self, caller_id, key):
        """
        Retrieve parameter value from server.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param key: parameter to lookup. If key is a namespace,
        getParam() will return a parameter tree.
        @type  key: str
        getParam() will return a parameter tree.

        @return: [code, statusMessage, parameterValue]. If code is not
            1, parameterValue should be ignored. If key is a namespace,
            the return value will be a dictionary, where each key is a
            parameter in that namespace. Sub-namespaces are also
            represented as dictionaries.
        @rtype: [int, str, XMLRPCLegalValue]
        """
        try:
            key = resolve_name(key, caller_id)
            return 1, "Parameter [%s]"%key, self.param_server.get_param(key)
        except KeyError, e: 
            return -1, "Parameter [%s] is not set"%key, 0

    _mremap_table['searchParam'] = [0] # remap key
    @apivalidate(0, (non_empty_str('key'),))
    def searchParam(self, caller_id, key):
        """
        Search for parameter key on parameter server. Search starts in caller's namespace and proceeds
        upwards through parent namespaces until Parameter Server finds a matching key.

        searchParam's behavior is to search for the first partial match.
        For example, imagine that there are two 'robot_description' parameters::
          
           /robot_description
             /robot_description/arm
             /robot_description/base
           /pr2/robot_description
             /pr2/robot_description/base

        If I start in the namespace /pr2/foo and search for
        'robot_description', searchParam will match
        /pr2/robot_description. If I search for 'robot_description/arm'
        it will return /pr2/robot_description/arm, even though that
        parameter does not exist (yet).

        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param key: parameter key to search for.
        @type  key: str
        @return: [code, statusMessage, foundKey]. If code is not 1, foundKey should be
            ignored. 
        @rtype: [int, str, str]
        """
        search_key = self.param_server.search_param(caller_id, key)
        if search_key:
            return 1, "Found [%s]"%search_key, search_key
        else:
            return -1, "Cannot find parameter [%s] in an upwards search"%key, ''

    _mremap_table['subscribeParam'] = [0] # remap key
    @apivalidate(0, (is_api('caller_api'), non_empty_str('key'),))
    def subscribeParam(self, caller_id, caller_api, key):
        """
        Retrieve parameter value from server and subscribe to updates to that param. See
        paramUpdate() in the Node API. 
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param key: parameter to lookup.
        @type  key: str
        @param caller_api: API URI for paramUpdate callbacks.
        @type  caller_api: str
        @return: [code, statusMessage, parameterValue]. If code is not
           1, parameterValue should be ignored. parameterValue is an empty dictionary if the parameter
           has not been set yet.
        @rtype: [int, str, XMLRPCLegalValue]
        """
        key = resolve_name(key, caller_id)        
        try:
            # ps_lock has precedence and is required due to
            # potential self.reg_manager modification
            self.ps_lock.acquire()
            val = self.param_server.subscribe_param(key, (caller_id, caller_api))
        finally:
            self.ps_lock.release()
        return 1, "Subscribed to parameter [%s]"%key, val

    _mremap_table['unsubscribeParam'] = [0] # remap key
    @apivalidate(0, (is_api('caller_api'), non_empty_str('key'),))
    def unsubscribeParam(self, caller_id, caller_api, key):
        """
        Retrieve parameter value from server and subscribe to updates to that param. See
        paramUpdate() in the Node API. 
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param key: parameter to lookup.
        @type  key: str
        @param caller_api: API URI for paramUpdate callbacks.
        @type  caller_api: str
        @return: [code, statusMessage, numUnsubscribed]. 
           If numUnsubscribed is zero it means that the caller was not subscribed to the parameter.
        @rtype: [int, str, int]
        """        
        key = resolve_name(key, caller_id)        
        try:
            # ps_lock is required due to potential self.reg_manager modification
            self.ps_lock.acquire()
            retval = self.param_server.unsubscribe_param(key, (caller_id, caller_api))
        finally:
            self.ps_lock.release()
        return 1, "Unsubscribe to parameter [%s]"%key, 1


    _mremap_table['hasParam'] = [0] # remap key
    @apivalidate(False, (non_empty_str('key'),))
    def hasParam(self, caller_id, key):
        """
        Check if parameter is stored on server. 
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param key: parameter to check
        @type  key: str
        @return: [code, statusMessage, hasParam]
        @rtype: [int, str, bool]
        """
        key = resolve_name(key, caller_id)
        if self.param_server.has_param(key):
            return 1, key, True
        else:
            return 1, key, False            

    @apivalidate([])
    def getParamNames(self, caller_id):
        """
        Get list of all parameter names stored on this server.
        This does not adjust parameter names for caller's scope.
        
        @param caller_id: ROS caller id    
        @type  caller_id: str
        @return: [code, statusMessage, parameterNameList]
        @rtype: [int, str, [str]]
        """
        return 1, "Parameter names", self.param_server.get_param_names()
            
    ##################################################################################
    # NOTIFICATION ROUTINES

    def _notify(self, registrations, task, key, value):
        """
        Generic implementation of callback notification
        @param registrations: Registrations
        @type  registrations: L{Registrations}
        @param task: task to queue
        @type  task: fn
        @param key: registration key
        @type  key: str
        @param value: value to pass to task
        @type  value: Any
        """
        # cache thread_pool for thread safety
        thread_pool = self.thread_pool
        if not thread_pool:
            return
        
        if registrations.has_key(key):
            try:            
                for node_api in registrations.get_apis(key):
                    # use the api as a marker so that we limit one thread per subscriber
                    thread_pool.queue_task(node_api, task, (node_api, key, value))
            except KeyError:
                _logger.warn('subscriber data stale (key [%s], listener [%s]): node API unknown'%(key, s))
        
    def _notify_param_subscribers(self, updates):
        """
        Notify parameter subscribers of new parameter value
        @param updates [([str], str, any)*]: [(subscribers, param_key, param_value)*]
        @param param_value str: parameter value
        """
        # cache thread_pool for thread safety
        thread_pool = self.thread_pool
        if not thread_pool:
            return

        for subscribers, key, value in updates:
            # use the api as a marker so that we limit one thread per subscriber
            for caller_id, caller_api in subscribers:
                self.thread_pool.queue_task(caller_api, self.param_update_task, (caller_id, caller_api, key, value))

    def param_update_task(self, caller_id, caller_api, param_key, param_value):
        """
        Contact api.paramUpdate with specified parameters
        @param caller_id: caller ID
        @type  caller_id: str
        @param caller_api: XML-RPC URI of node to contact
        @type  caller_api: str
        @param param_key: parameter key to pass to node
        @type  param_key: str
        @param param_value: parameter value to pass to node
        @type  param_value: str
        """
        mloginfo("paramUpdate[%s]", param_key)
        code, _, _ = xmlrpcapi(caller_api).paramUpdate('/master', param_key, param_value)
        if code == -1:
            try:
                # ps_lock is required due to potential self.reg_manager modification
                self.ps_lock.acquire()
                # reverse lookup to figure out who we just called
                matches = self.reg_manager.reverse_lookup(caller_api)
                for m in matches:
                    retval = self.param_server.unsubscribe_param(param_key, (m.id, caller_api))
            finally:
                self.ps_lock.release()


    def _notify_topic_subscribers(self, topic, pub_uris):
        """
        Notify subscribers with new publisher list
        @param topic: name of topic
        @type  topic: str
        @param pub_uris: list of URIs of publishers.
        @type  pub_uris: [str]
        """
        self._notify(self.subscribers, publisher_update_task, topic, pub_uris)

    def _notify_service_update(self, service, service_api):
        """
        Notify clients of new service provider
        @param service: name of service
        @type  service: str
        @param service_api: new service URI
        @type  service_api: str
        """
        ###TODO:XXX:stub code, this callback doesnot exist yet
        self._notify(self.service_clients, service_update_task, service, service_api)
        
    ##################################################################################
    # SERVICE PROVIDER

    _mremap_table['registerService'] = [0] # remap service
    @apivalidate(0, ( is_service('service'), is_api('service_api'), is_api('caller_api')))
    def registerService(self, caller_id, service, service_api, caller_api):
        """
        Register the caller as a provider of the specified service.
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param service: Fully-qualified name of service 
        @type  service: str
        @param service_api: Service URI 
        @type  service_api: str
        @param caller_api: XML-RPC URI of caller node 
        @type  caller_api: str
        @return: (code, message, ignore)
        @rtype: (int, str, int)
        """        
        try:
            self.ps_lock.acquire()
            self.reg_manager.register_service(service, caller_id, caller_api, service_api)
            mloginfo("+SERVICE [%s] %s %s", service, caller_id, caller_api)
            if 0: #TODO
                self._notify_service_update(service, service_api)
        finally:
            self.ps_lock.release()

        if self._valid_service(service):
            args = (caller_id, service, service_api, caller_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote registerService(%s, %s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteRegisterService(*args)
                    if code != 1:
                        logwarn("unable to register service [%s] with master %s: %s"%(service, m, msg))

        self.last_master_activity_time = time.time()
        return 1, "Registered [%s] as provider of [%s]"%(caller_id, service), 1

    _mremap_table['remoteRegisterService'] = [0] # remap service
    @apivalidate(0, ( is_service('service'), is_api('service_api'), is_api('caller_api')))
    def remoteRegisterService(self, caller_id, service, service_api, caller_api):
        """
        Register the caller as a provider of the specified service.
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param service: Fully-qualified name of service 
        @type  service: str
        @param service_api: Service URI 
        @type  service_api: str
        @param caller_api: XML-RPC URI of caller node 
        @type  caller_api: str
        @return: (code, message, ignore)
        @rtype: (int, str, int)
        """        
        try:
            self.ps_lock.acquire()
            self.reg_manager.register_service(service, caller_id, caller_api, service_api)
            mloginfo("+SERVICE [%s] %s %s", service, caller_id, caller_api)
            if 0: #TODO
                self._notify_service_update(service, service_api)
        finally:
            self.ps_lock.release()
        return 1, "Registered [%s] as provider of [%s]"%(caller_id, service), 1

    _mremap_table['lookupService'] = [0] # remap service
    @apivalidate(0, (is_service('service'),))
    def lookupService(self, caller_id, service):
        """
        Lookup all provider of a particular service.
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param service: fully-qualified name of service to lookup.
        @type: service: str
        @return: (code, message, serviceUrl). service URL is provider's
           ROSRPC URI with address and port.  Fails if there is no provider.
        @rtype: (int, str, str)
        """
        try:
            self.ps_lock.acquire()
            service_url = self.services.get_service_api(service)
        finally:
            self.ps_lock.release()
        if service_url:
            return 1, "rosrpc URI: [%s]"%service_url, service_url
        else:
            return -1, "no provider", ''

    _mremap_table['unregisterService'] = [0] # remap service
    @apivalidate(0, ( is_service('service'), is_api('service_api')))
    def unregisterService(self, caller_id, service, service_api):
        """
        Unregister the caller as a provider of the specified service.
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param service: Fully-qualified name of service
        @type  service: str
        @param service_api: API URI of service to unregister. Unregistration will only occur if current
           registration matches.
        @type  service_api: str
        @return: (code, message, numUnregistered). Number of unregistrations (either 0 or 1).
           If this is zero it means that the caller was not registered as a service provider.
           The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """
        try:
            self.ps_lock.acquire()
            retval = self.reg_manager.unregister_service(service, caller_id, service_api)
            if 0: #TODO
                self._notify_service_update(service, service_api)
            mloginfo("-SERVICE [%s] %s %s", service, caller_id, service_api)
        finally:
            self.ps_lock.release()

        if retval[2] == 0:
            return retval

        if self._valid_service(service):
            args = (caller_id, service, service_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote unregisterService(%s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteUnregisterService(*args)
                    if code != 1:
                        logwarn("unable to unregister service [%s] with master %s: %s"%(service, m, msg))
        
        return retval

    _mremap_table['remoteUnregisterService'] = [0] # remap service
    @apivalidate(0, ( is_service('service'), is_api('service_api')))
    def remoteUnregisterService(self, caller_id, service, service_api):
        """
        Unregister the caller as a provider of the specified service.
        @param caller_id str: ROS caller id
        @type  caller_id: str
        @param service: Fully-qualified name of service
        @type  service: str
        @param service_api: API URI of service to unregister. Unregistration will only occur if current
           registration matches.
        @type  service_api: str
        @return: (code, message, numUnregistered). Number of unregistrations (either 0 or 1).
           If this is zero it means that the caller was not registered as a service provider.
           The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """
        try:
            self.ps_lock.acquire()
            retval = self.reg_manager.unregister_service(service, caller_id, service_api)
            if 0: #TODO
                self._notify_service_update(service, service_api)
            mloginfo("-SERVICE [%s] %s %s", service, caller_id, service_api)
            return retval
        finally:
            self.ps_lock.release()

    ##################################################################################
    # PUBLISH/SUBSCRIBE

    _mremap_table['registerSubscriber'] = [0] # remap topic
    @apivalidate(0, ( is_topic('topic'), valid_type_name('topic_type'), is_api('caller_api')))
    def registerSubscriber(self, caller_id, topic, topic_type, caller_api):
        """
        Subscribe the caller to the specified topic. In addition to receiving
        a list of current publishers, the subscriber will also receive notifications
        of new publishers via the publisherUpdate API.        
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic str: Fully-qualified name of topic to subscribe to. 
        @param topic_type: Datatype for topic. Must be a package-resource name, i.e. the .msg name.
        @type  topic_type: str
        @param caller_api: XML-RPC URI of caller node for new publisher notifications
        @type  caller_api: str
        @return: (code, message, publishers). Publishers is a list of XMLRPC API URIs
           for nodes currently publishing the specified topic.
        @rtype: (int, str, [str])
        """
        #NOTE: subscribers do not get to set topic type
        try:
            self.ps_lock.acquire()

            sub_uris = self.subscribers.get_apis(topic)
            d=','
            if d.join(sub_uris).find(caller_api) >= 0:
                pub_uris = self.publishers.get_apis(topic)
                return 1, "Already subscribed to [%s]"%topic, pub_uris

            self.reg_manager.register_subscriber(topic, caller_id, caller_api)
            mloginfo("+SUB [%s] %s %s",topic, caller_id, caller_api)
            if topic_type != rospy.names.TOPIC_ANYTYPE or not topic in self.topics_types:
                self.topics_types[topic] = topic_type
            pub_uris = self.publishers.get_apis(topic)
        finally:
            self.ps_lock.release()

        if self._valid_topic(topic):
            args = (caller_id, topic, topic_type, caller_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote registerSubscriber(%s, %s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteRegisterSubscriber(*args)
                    if code != 1:
                        logwarn("unable to register subscription [%s] with master %s: %s"%(topic, m, msg))
                    else:
                        pub_uris.extend(val)

        self.last_master_activity_time = time.time()
        return 1, "Subscribed to [%s]"%topic, pub_uris

    _mremap_table['remoteRegisterSubscriber'] = [0] # remap topic
    @apivalidate(0, ( is_topic('topic'), valid_type_name('topic_type'), is_api('caller_api')))
    def remoteRegisterSubscriber(self, caller_id, topic, topic_type, caller_api):
        """
        Subscribe the caller to the specified topic. In addition to receiving
        a list of current publishers, the subscriber will also receive notifications
        of new publishers via the publisherUpdate API.        
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic str: Fully-qualified name of topic to subscribe to. 
        @param topic_type: Datatype for topic. Must be a package-resource name, i.e. the .msg name.
        @type  topic_type: str
        @param caller_api: XML-RPC URI of caller node for new publisher notifications
        @type  caller_api: str
        @return: (code, message, publishers). Publishers is a list of XMLRPC API URIs
           for nodes currently publishing the specified topic.
        @rtype: (int, str, [str])
        """
        #NOTE: subscribers do not get to set topic type
        try:
            self.ps_lock.acquire()

            sub_uris = self.subscribers.get_apis(topic)
            d=','
            if d.join(sub_uris).find(caller_api) >= 0:
                pub_uris = self.publishers.get_apis(topic)
                return 1, "Already subscribed to [%s]"%topic, pub_uris

            self.reg_manager.register_subscriber(topic, caller_id, caller_api)
            mloginfo("+SUB [%s] %s %s",topic, caller_id, caller_api)
            if topic_type != rospy.names.TOPIC_ANYTYPE or not topic in self.topics_types:
                self.topics_types[topic] = topic_type
            pub_uris = self.publishers.get_apis(topic)
        finally:
            self.ps_lock.release()

        return 1, "Subscribed to [%s]"%topic, pub_uris

    _mremap_table['unregisterSubscriber'] = [0] # remap topic    
    @apivalidate(0, (is_topic('topic'), is_api('caller_api')))
    def unregisterSubscriber(self, caller_id, topic, caller_api):
        """
        Unregister the caller as a publisher of the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to unregister.
        @type  topic: str
        @param caller_api: API URI of service to unregister. Unregistration will only occur if current
           registration matches.    
        @type  caller_api: str
        @return: (code, statusMessage, numUnsubscribed). 
          If numUnsubscribed is zero it means that the caller was not registered as a subscriber.
          The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """
        try:
            self.ps_lock.acquire()
            retval = self.reg_manager.unregister_subscriber(topic, caller_id, caller_api)
            mloginfo("-SUB [%s] %s %s",topic, caller_id, caller_api)
        finally:
            self.ps_lock.release()

        if retval[2] == 0:
            return retval

        # Handle remote masters
        if self._valid_topic(topic):
            args = (caller_id, topic, caller_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote unregisterSubscriber(%s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteUnregisterSubscriber(*args)
                    if code != 1:
                        logwarn("unable to unregister subscription [%s] with master %s: %s"%(topic, m, msg))

        return retval

    _mremap_table['remoteUnregisterSubscriber'] = [0] # remap topic    
    @apivalidate(0, (is_topic('topic'), is_api('caller_api')))
    def remoteUnregisterSubscriber(self, caller_id, topic, caller_api):
        """
        Unregister the caller as a publisher of the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to unregister.
        @type  topic: str
        @param caller_api: API URI of service to unregister. Unregistration will only occur if current
           registration matches.    
        @type  caller_api: str
        @return: (code, statusMessage, numUnsubscribed). 
          If numUnsubscribed is zero it means that the caller was not registered as a subscriber.
          The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """
        try:
            self.ps_lock.acquire()

            retval = self.reg_manager.unregister_subscriber(topic, caller_id, caller_api)
            mloginfo("-SUB [%s] %s %s",topic, caller_id, caller_api)
        finally:
            self.ps_lock.release()

        return retval

    _mremap_table['registerPublisher'] = [0] # remap topic   
    @apivalidate(0, ( is_topic('topic'), valid_type_name('topic_type'), is_api('caller_api')))
    def registerPublisher(self, caller_id, topic, topic_type, caller_api):
        """
        Register the caller as a publisher the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to register.
        @type  topic: str
        @param topic_type: Datatype for topic. Must be a
        package-resource name, i.e. the .msg name.
        @type  topic_type: str
        @param caller_api str: ROS caller XML-RPC API URI
        @type  caller_api: str
        @return: (code, statusMessage, subscriberApis).
        List of current subscribers of topic in the form of XMLRPC URIs.
        @rtype: (int, str, [str])
        """
        #NOTE: we need topic_type for getPublishedTopics.
        try:
            self.ps_lock.acquire()

            # check if we already have registration of this topic, caller_id pair
            pub_uris = self.publishers.get_apis(topic)
            d=','
            if d.join(pub_uris).find(caller_api) >= 0:
                sub_uris = self.subscribers.get_apis(topic)
                return 1, "Already registered [%s] as publisher of [%s]"%(caller_id, topic), sub_uris

            self.reg_manager.register_publisher(topic, caller_id, caller_api)
            # don't let '*' type squash valid typing
            if topic_type != rospy.names.TOPIC_ANYTYPE or not topic in self.topics_types:
                self.topics_types[topic] = topic_type
            pub_uris = self.publishers.get_apis(topic)
            self._notify_topic_subscribers(topic, pub_uris)
            mloginfo("+PUB [%s] %s %s",topic, caller_id, caller_api)
            sub_uris = self.subscribers.get_apis(topic)            
        finally:
            self.ps_lock.release()

        # Handle remote masters
        topic_prefix = '/'
        if self._valid_topic(topic):
            args = (caller_id, topic_prefix+topic.lstrip('/'), topic_type, caller_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote registerPublisher(%s, %s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteRegisterPublisher(*args)
                    if code != 1:
                        logwarn("unable to register publication [%s] with remote master %s: %s"%(topic, m, msg))
                    else:
                        sub_uris.extend(val)

        self.last_master_activity_time = time.time()
        return 1, "Registered [%s] as publisher of [%s]"%(caller_id, topic), sub_uris

    _mremap_table['remoteRegisterPublisher'] = [0] # remap topic   
    @apivalidate(0, ( is_topic('topic'), valid_type_name('topic_type'), is_api('caller_api')))
    def remoteRegisterPublisher(self, caller_id, topic, topic_type, caller_api):
        """
        Register the caller as a publisher the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to register.
        @type  topic: str
        @param topic_type: Datatype for topic. Must be a
        package-resource name, i.e. the .msg name.
        @type  topic_type: str
        @param caller_api str: ROS caller XML-RPC API URI
        @type  caller_api: str
        @return: (code, statusMessage, subscriberApis).
        List of current subscribers of topic in the form of XMLRPC URIs.
        @rtype: (int, str, [str])
        """
        #NOTE: we need topic_type for getPublishedTopics.
        try:
            self.ps_lock.acquire()

            # check if we already have registration of this topic, caller_id pair
            pub_uris = self.publishers.get_apis(topic)
            d=','
            if d.join(pub_uris).find(caller_api) >= 0:
                sub_uris = self.subscribers.get_apis(topic)
                return 1, "Already registered [%s] as publisher of [%s]"%(caller_id, topic), sub_uris

            print 'reg_manager.register_publisher(%s, %s, %s)' % (topic, caller_id, caller_api)

            self.reg_manager.register_publisher(topic, caller_id, caller_api)
            # don't let '*' type squash valid typing
            if topic_type != rospy.names.TOPIC_ANYTYPE or not topic in self.topics_types:
                self.topics_types[topic] = topic_type
            pub_uris = self.publishers.get_apis(topic)
            self._notify_topic_subscribers(topic, pub_uris)
            mloginfo("+PUB [%s] %s %s",topic, caller_id, caller_api)
            sub_uris = self.subscribers.get_apis(topic)            
        finally:
            self.ps_lock.release()

        return 1, "Registered [%s] as publisher of [%s]"%(caller_id, topic), sub_uris

    _mremap_table['unregisterPublisher'] = [0] # remap topic   
    @apivalidate(0, (is_topic('topic'), is_api('caller_api')))
    def unregisterPublisher(self, caller_id, topic, caller_api):
        """
        Unregister the caller as a publisher of the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to unregister.
        @type  topic: str
        @param caller_api str: API URI of service to
           unregister. Unregistration will only occur if current
           registration matches.
        @type  caller_api: str
        @return: (code, statusMessage, numUnregistered). 
           If numUnregistered is zero it means that the caller was not registered as a publisher.
           The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """            
        try:
            self.ps_lock.acquire()

            retval = self.reg_manager.unregister_publisher(topic, caller_id, caller_api)
            if retval[VAL]:
                self._notify_topic_subscribers(topic, self.publishers.get_apis(topic))
            mloginfo("-PUB [%s] %s %s",topic, caller_id, caller_api)

            if retval[2] == 0:
                return retval

        except Exception, e:
            print e
        finally:
            self.ps_lock.release()

        # Handle remote masters
        if self._valid_topic(topic):
            topic_prefix='/'
            args = (caller_id, topic_prefix+topic.lstrip('/'), caller_api)
            if self.sd is not None:
                remote_master_uri = self.sd.get_remote_services().values()
                if len(remote_master_uri) > 0:
                    print 'Remote unregisterPublisher(%s, %s, %s)' % args
                for m in remote_master_uri:
                    print '... on %s' % m
                    master = xmlrpcapi(m)
                    code, msg, val = master.remoteUnregisterPublisher(*args)
                    if code != 1:
                        logwarn("unable to unregister publication [%s] with master: %s"%(topic, msg))

        return retval

    _mremap_table['remoteUnregisterPublisher'] = [0] # remap topic   
    @apivalidate(0, (is_topic('topic'), is_api('caller_api')))
    def remoteUnregisterPublisher(self, caller_id, topic, caller_api):
        """
        Unregister the caller as a publisher of the topic.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param topic: Fully-qualified name of topic to unregister.
        @type  topic: str
        @param caller_api str: API URI of service to
           unregister. Unregistration will only occur if current
           registration matches.
        @type  caller_api: str
        @return: (code, statusMessage, numUnregistered). 
           If numUnregistered is zero it means that the caller was not registered as a publisher.
           The call still succeeds as the intended final state is reached.
        @rtype: (int, str, int)
        """            
        try:
            self.ps_lock.acquire()
            retval = self.reg_manager.unregister_publisher(topic, caller_id, caller_api)
            if retval[VAL]:
                self._notify_topic_subscribers(topic, self.publishers.get_apis(topic))
            mloginfo("-PUB [%s] %s %s",topic, caller_id, caller_api)
        finally:
            self.ps_lock.release()

        return retval


    ##################################################################################
    # GRAPH STATE APIS

    _mremap_table['lookupNode'] = [0] # remap node
    @apivalidate('', (valid_name('node'),))
    def lookupNode(self, caller_id, node_name):
        """
        Get the XML-RPC URI of the node with the associated
        name/caller_id.  This API is for looking information about
        publishers and subscribers. Use lookupService instead to lookup
        ROS-RPC URIs.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param node: name of node to lookup
        @type  node: str
        @return: (code, msg, URI)
        @rtype: (int, str, str)
        """
        try:
            self.ps_lock.acquire()
            node = self.reg_manager.get_node(node_name)
            if node is not None:
                retval = 1, "node api", node.api
            else:
                retval = -1, "unknown node [%s]"%node_name, ''
        finally:
            self.ps_lock.release()
        return retval
        
    _mremap_table['getPublishedTopics'] = [0] # remap subgraph
    @apivalidate(0, (empty_or_valid_name('subgraph'),))
    def getPublishedTopics(self, caller_id, subgraph):
        """
        Get list of topics that can be subscribed to. This does not return topics that have no publishers.
        See L{getSystemState()} to get more comprehensive list.
        @param caller_id: ROS caller id
        @type  caller_id: str
        @param subgraph: Restrict topic names to match within the specified subgraph. Subgraph namespace
           is resolved relative to the caller's namespace. Use '' to specify all names.
        @type  subgraph: str
        @return: (code, msg, [[topic1, type1]...[topicN, typeN]])
        @rtype: (int, str, [[str, str],])
        """
        try:
            self.ps_lock.acquire()
            # force subgraph to be a namespace with trailing slash
            if subgraph and subgraph[-1] != SEP:
                subgraph = subgraph + SEP
            #we don't bother with subscribers as subscribers don't report topic types. also, the intended
            #use case is for subscribe-by-topic-type
            retval = [[t, self.topics_types[t]] for t in self.publishers.iterkeys() if t.startswith(subgraph)]
        finally:
            self.ps_lock.release()
        return 1, "current topics", retval
    
    @apivalidate([[],[], []])
    def getSystemState(self, caller_id): 
        """
        Retrieve list representation of system state (i.e. publishers, subscribers, and services).
        @param caller_id: ROS caller id    
        @type  caller_id: str
        @rtype: (int, str, [[str,[str]], [str,[str]], [str,[str]]])
        @return: (code, statusMessage, systemState).

           System state is in list representation::
             [publishers, subscribers, services].
        
           publishers is of the form::
             [ [topic1, [topic1Publisher1...topic1PublisherN]] ... ]
        
           subscribers is of the form::
             [ [topic1, [topic1Subscriber1...topic1SubscriberN]] ... ]
        
           services is of the form::
             [ [service1, [service1Provider1...service1ProviderN]] ... ]
        """
        edges = []
        try: 
            self.ps_lock.acquire()
            retval = [r.get_state() for r in (self.publishers, self.subscribers, self.services)]
        finally:
            self.ps_lock.release()
        return 1, "current system state", retval

def start_master(environ, port=DEFAULT_MASTER_PORT):
    """
    Start a local master instance.
    @return: Node instance
    @rtype: rospy.msnode.ROSNode
    """
    global _local_master_uri
    master = rospy.msnode.ROSNode(rospy.core.MASTER_NAME, port, ROSMasterHandlerSD())
    master.start()
    while not master.uri and not rospy.core.is_shutdown():
        time.sleep(0.0001) #poll for init
    _local_master_uri = master.uri

    # TODO: Figure out if there is a way to query the launching process for completion state
    # (e.g. determine when roslaunch has finished starting nodes, reading parameters)
    while time.time() - master.handler.last_master_activity_time < 3.0:
        time.sleep(0.1) # Poll until master is resting

    # start service discovery on ROSMasterHandlerSD
    master.handler.start_service_discovery(master.uri)

    return master

ENV_DOC = {
    ROS_ROOT: "Directory of ROS installation to use",
    ROS_PACKAGE_PATH: "Paths to search for additional ROS packages",    
    ROS_LOG_DIR: "Directory to write log files to",
    ROS_NAMESPACE: "Namespace to place node in", #defined in names.py
    ROS_MASTER_URI: "Default URI of ROS central server",
    ROS_HOSTNAME: "address to bind to",    
    }
ENV_VARS = ENV_DOC.keys()

ZENMASTER_USAGE_ENV = "Environment variables:\n"+'\n'.join([" * %s: %s"%(k,v) for (k,v) in ENV_DOC.iteritems()])

ZENMASTER_USAGE = """
usage: %(progname)s [-p node-port] 

Flags:
 -p\tOverride port environment variable
"""+ZENMASTER_USAGE_ENV

def zenmaster_usage(progname):
    print ZENMASTER_USAGE%vars()

def zenmaster_main(argv=sys.argv, stdout=sys.stdout, env=os.environ):
    import optparse
    parser = optparse.OptionParser(usage="usage: zenmaster [options]")
    parser.add_option("--core",
                      dest="core", action="store_true", default=False,
                      help="run as core")
    parser.add_option("-p", "--port", 
                      dest="port", default=0,
                      help="override port", metavar="PORT")
    options, args = parser.parse_args(argv[1:])

    # only arg that zenmaster supports is __log remapping of logfilename
    for arg in args:
        if not arg.startswith('__log:='):
            parser.error("unrecognized arg: %s"%arg)
    rospy.core.configure_logging('zenmaster')    
    
    port = rospy.init.DEFAULT_MASTER_PORT
    if options.port:
        port = string.atoi(options.port)

    if not options.core:
        print """


ACHTUNG WARNING ACHTUNG WARNING ACHTUNG
WARNING ACHTUNG WARNING ACHTUNG WARNING


Standalone zenmaster has been deprecated, please use 'roscore' instead


ACHTUNG WARNING ACHTUNG WARNING ACHTUNG
WARNING ACHTUNG WARNING ACHTUNG WARNING


"""

    print '\n\nThis is zenmaster_sd -- uses service discovery to find other ros masters\n\n'
    logger = logging.getLogger("rospy")
    logger.info("initialization complete, waiting for shutdown")
    try:
        logger.info("Starting ROS Master Node (Service Discovery Version)")
        start_master(env, port)
        while not rospy.is_shutdown():
            time.sleep(0.5)
    except KeyboardInterrupt:
        logger.info("keyboard interrupt, will exit")
        rospy.signal_shutdown('keyboard interrupt')

    logger.info("exiting...: %s", rospy.is_shutdown())
    print "exiting..."

if __name__ == "__main__":
    main()
