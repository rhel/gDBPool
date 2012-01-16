# -*- coding: utf-8 -*-

# Copyright 2011-2012 Florian von Bock (f at vonbock dot info)
#
# gDBPool - db connection pooling for gevent
#
# PGChannelListener - subscribes to a (NOTIFY) channel on postgres
# via LISTEN and streams the events to the subscribes result_queues

__author__ = "Florian von Bock"
__email__ = "f at vonbock dot info"
__version__ = "0.1.2"


import gevent
from gevent import monkey; monkey.patch_all()

import psycopg2

from psyco_ge import make_psycopg_green; make_psycopg_green()
from gevent.select import select
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

class PGChannelListenerException( Exception ):
    pass


def pipe_colon_unmarshall( payload_string ):
    payload_data = {}
    try:
        for kv_pair in payload_string.split( '|' ):
            k, v = kv_pair.split( ':', 1 )
            payload_data[ k ] = v
    except Exception, e:
        raise PGChannelListenerException( "Unmarshalling of the LISTEN payload failed: %s" % ( e.message, ) )
    return payload_data


class PGChannelListener( object ):
    """
    A Listener for Postgres LISTEN/NOTIFY channels using gevent.

    For each channel there will be one {PGChannelListener} instance that fans
    notifications out to the subscribed {Queues}
    """

    def __new__(  cls, q, pool, channel_name, *args, **kwargs ):
        if not hasattr( cls, '_instances' ):
            cls._instances = {}
        if not cls._instances.has_key( channel_name ):
            cls._instances[ channel_name ] = object.__new__( cls )
            cls._instances[ channel_name ].subscribers = {}
            cls._instances[ channel_name ].pool = pool
            cls._instances[ channel_name ].conn = pool.get( iso_level = ISOLATION_LEVEL_AUTOCOMMIT )
            cls._instances[ channel_name ].cur = None
            cls._instances[ channel_name ].channel_name = channel_name
            gevent.spawn( cls._instances[ channel_name ].listen )

        # hai hai... using id for this kind of stuff is sort of dangerous.
        # will come up with something less pointing gun at foot(TM). later. (TM).
        cls._instances[ channel_name ].subscribers[ id( q ) ] = q
        return cls._instances[ channel_name ]

    def __init__( self, q, conn, channel_name ):
        pass

    def __del__( self ):
        print "** __del__", self.channel_name
        del PGChannelListener._instances[ self.channel_name ]

    def unregister_queue( self, q_id ):
        if self.stop_event.is_set():
            return
        del self.subscribers[ q_id ]
        if len( self.subscribers ) == 0:
            self.stop_event.set()
            self.cur.close()
            self.pool.put( self.conn )

    def listen( self, unmarshaller = pipe_colon_unmarshall ):
        """
        Subscriber to the channel and send notification payloads to the
        results Queue.
        """

        self.stop_event = stop_event = gevent.event.Event()
        self.cur = self.conn.cursor()
        self.cur.execute( "LISTEN %s;" % ( self.channel_name, ) )
        while 1:
            if self.stop_event.is_set():
                return
            if select( [ self.conn ], [], [] ) == ( [], [], [] ):
                print "LISTEN timeout."
            else:
                if self.stop_event.is_set():
                    return
                self.conn.poll()
                while self.conn.notifies:
                    if self.stop_event.is_set():
                        return
                    notify = self.conn.notifies.pop()
                    payload_data = unmarshaller( notify.payload )
                    for q_id in self.subscribers.iterkeys():
                            self.subscribers[ q_id ].put( payload_data )
