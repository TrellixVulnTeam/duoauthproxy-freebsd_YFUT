# Copyright (C) 2001 Tommi Virtanen
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of version 2.1 of the GNU Lesser General Public
# License as published by the Free Software Foundation.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

"""LDAP protocol client"""

from ldaptor.protocols import pureldap, pureber
from ldaptor.protocols.ldap import ldaperrors

from twisted.python import log
from twisted.internet import protocol, defer, ssl, reactor


class LDAPClientConnectionLostException(ldaperrors.LDAPException):
    def toWire(self):
        return b'Connection lost'


class LDAPStartTLSBusyError(ldaperrors.LDAPOperationsError):
    def __init__(self, onwire, message=None):
        self.onwire = onwire
        ldaperrors.LDAPOperationsError.__init__(self, message=message)

    def toWire(self):
        return b'Cannot STARTTLS while operations on wire: %r' % self.onwire


class LDAPStartTLSInvalidResponseName(ldaperrors.LDAPException):
    def __init__(self, responseName):
        self.responseName = responseName
        ldaperrors.LDAPException.__init__(self)

    def toWire(self):
        return b'Invalid responseName in STARTTLS response: %r' % (self.responseName, )


class LDAPClient(protocol.Protocol):
    """An LDAP client"""
    debug = False
    # DUO EDIT D46272: Added "is_logging_insecure" support
    is_logging_insecure = False
    # END EDIT

    def __init__(self):
        self.onwire = {}
        self.buffer = b''
        self.connected = None

    berdecoder = pureldap.LDAPBERDecoderContext_TopLevel(
        inherit=pureldap.LDAPBERDecoderContext_LDAPMessage(
            fallback=pureldap.LDAPBERDecoderContext(fallback=pureber.BERDecoderContext()),
            inherit=pureldap.LDAPBERDecoderContext(fallback=pureber.BERDecoderContext())))

    def dataReceived(self, recd):
        self.buffer += recd
        while 1:
            try:
                o, bytes = pureber.berDecodeObject(self.berdecoder, self.buffer)
            except pureber.BERExceptionInsufficientData:
                o, bytes = None, 0
            self.buffer = self.buffer[bytes:]
            if not o:
                break
            self.handle(o)

    def connectionMade(self):
        """TCP connection has opened"""
        self.connected = 1

    def connectionLost(self, reason=protocol.connectionDone):
        """Called when TCP connection has been lost"""
        self.connected = 0
        # notify handlers of operations in flight
        while self.onwire:
            k, v = self.onwire.popitem()
            # DUO EDIT D46273: Remove depenence on specific number of elemnts in items
            # Change originally made here
            # https://github.com/tv42/ldaptor/tree/024250a206ea1c10dfee5deb5eb2b7d1a34eecc6
            # d, _, _, _, _ = v
            d = v[0]
            # END EDIT
            d.errback(reason)

    def _send(self, op, controls=None):
        if not self.connected:
            raise LDAPClientConnectionLostException()
        msg = pureldap.LDAPMessage(op, controls=controls)
        if self.debug:
            # DUO EDIT D46272: Added "is_logging_insecure" support
            op.is_logging_insecure = self.is_logging_insecure
            # END EDIT
            log.msg('C->S %s' % repr(msg))
        assert msg.id not in self.onwire
        return msg

    # DUO EDIT D46274: Add support for response handlers
    def send(self, op, controls=None, handler=None, return_controls=False):
        """
        Send an LDAP operation to the server.

        @param op: the operation to send

        @type op: LDAPProtocolRequest

        @param controls: LDAP controls to send with the message as a
        list of 3-tuples ('OID string', criticality, value).
        Criticality and value can be None to omit them from the
        message that is sent. Otherwise, criticality must be boolean.

        @type controls: list

        @param handler: Callable that will be called for each
        response. It must return a boolean indicating whether this was
        the final response. functools.partial can be used to give
        further arguments or keyword arguments to the callable.

        @type handler: Callable.

        @param return_controls: If true, the handler will be called with
        the LDAP Message's value as well as the controls

        @type handle_controls: bool

        @return: the response from server

        @rtype: Deferred LDAPProtocolResponse
        """
        msg = self._send(op, controls=controls)
        assert op.needs_answer
        d = defer.Deferred()
        # self.onwire[msg.id] = (d, False, None, None, None)
        if handler is not None:
            self.onwire[msg.id] = (d, return_controls, handler, [], {})
        else:
            self.onwire[msg.id] = (d, return_controls, None, None, None)
        self.transport.write(msg.toWire())
        return d
    # END EDIT

    def send_multiResponse(self, op, handler, *args, **kwargs):
        """
        Send an LDAP operation to the server, expecting one or more
        responses.

        If `handler` is provided, it will receive a LDAP response as
        its first argument. The Deferred returned by this function will
        never fire.

        If `handler` is not provided, the Deferred returned by this
        function will fire with the final LDAP response.

        @param op: the operation to send
        @type op: LDAPProtocolRequest
        @param handler: a callable that will be called for each
        response. It should return a boolean, whether this was the
        final response.
        @param args: positional arguments to pass to handler
        @param kwargs: keyword arguments to pass to handler
        @return: the result from the first handler as a deferred that
        completes when the first response has been received
        @rtype: Deferred LDAPProtocolResponse
        """
        msg = self._send(op)
        assert op.needs_answer
        d = defer.Deferred()
        self.onwire[msg.id] = (d, False, handler, args, kwargs)
        self.transport.write(msg.toWire())
        return d

    def send_multiResponse_ex(self, op, controls=None, handler=None, *args, **kwargs):
        """
        Send an LDAP operation to the server, expecting one or more
        responses.

        If `handler` is provided, it will receive a LDAP response *and*
        response controls as its first 2 arguments. The Deferred returned
        by this function will never fire.

        If `handler` is not provided, the Deferred returned by this
        function will fire with a tuple of the first LDAP response
        and any associated response controls.

        @param op: the operation to send
        @type op: LDAPProtocolRequest
        @param controls: LDAP controls to send with the message.
        @type controls: LDAPControls
        @param handler: a callable that will be called for each
        response. It should return a boolean, whether this was the
        final response.
        @param args: positional arguments to pass to handler
        @param kwargs: keyword arguments to pass to handler
        @return: the result from the last handler as a deferred that
        completes when the last response has been received
        @rtype: Deferred LDAPProtocolResponse
        """
        msg = self._send(op, controls=controls)
        assert op.needs_answer
        d = defer.Deferred()
        self.onwire[msg.id] = (d, True, handler, args, kwargs)
        self.transport.write(msg.toWire())
        return d

    def send_noResponse(self, op, controls=None):
        """
        Send an LDAP operation to the server, with no response
        expected.

        @param op: the operation to send
        @type op: LDAPProtocolRequest
        """
        msg = self._send(op, controls=controls)
        assert not op.needs_answer
        self.transport.write(msg.toWire())

    def unsolicitedNotification(self, msg):
        log.msg("Got unsolicited notification: %s" % repr(msg))

    def handle(self, msg):
        assert isinstance(msg.value, pureldap.LDAPProtocolResponse)
        if self.debug:
            log.msg('C<-S %s' % repr(msg))

        if msg.id == 0:
            self.unsolicitedNotification(msg.value)
        else:
            d, return_controls, handler, args, kwargs = self.onwire[msg.id]

            if handler is None:
                assert (args is None) or (args == ())
                assert (kwargs is None) or (kwargs == {})
                if return_controls:
                    d.callback((msg.value, msg.controls))
                else:
                    d.callback(msg.value)
                del self.onwire[msg.id]
            else:
                assert args is not None
                assert kwargs is not None
                # Return true to mark request as fully handled
                if return_controls:
                    if handler(msg.value, msg.controls, *args, **kwargs):
                        del self.onwire[msg.id]
                        # DUO EDIT D46274: Add support for response handlers
                        d.callback(None)
                        # END EDIT
                else:
                    if handler(msg.value, *args, **kwargs):
                        del self.onwire[msg.id]
                        # DUO EDIT D46274: Add support for response handlers
                        d.callback(None)
                        # END EDIT

    def bind(self, dn='', auth=''):
        """
        @depreciated: Use e.bind(auth).

        @todo: Remove this method when there are no callers.
        """
        if not self.connected:
            raise LDAPClientConnectionLostException()
        else:
            r = pureldap.LDAPBindRequest(dn=dn, auth=auth)
            d = self.send(r)
            d.addCallback(self._handle_bind_msg)
        return d

    def _handle_bind_msg(self, msg):
        assert isinstance(msg, pureldap.LDAPBindResponse)
        assert msg.referral is None  # TODO
        if msg.resultCode != ldaperrors.Success.resultCode:
            raise ldaperrors.get(msg.resultCode, msg.errorMessage)
        return (msg.matchedDN, msg.serverSaslCreds)

    def unbind(self):
        if not self.connected:
            raise Exception("Not connected (TODO)")  # TODO make this a real object
        r = pureldap.LDAPUnbindRequest()
        self.send_noResponse(r)
        self.transport.loseConnection()

    def _cbStartTLS(self, msg, ctx):
        assert isinstance(msg, pureldap.LDAPExtendedResponse)
        assert msg.referral is None  # TODO
        if msg.resultCode != ldaperrors.Success.resultCode:
            raise ldaperrors.get(msg.resultCode, msg.errorMessage)

        if (msg.responseName is not None) and \
                (msg.responseName != pureldap.LDAPStartTLSResponse.oid):
            raise LDAPStartTLSInvalidResponseName(msg.responseName)

        self.transport.startTLS(ctx)
        return self

    def startTLS(self, ctx=None):
        """
        Start Transport Layer Security.

        It is the callers responsibility to make sure other things
        are not happening at the same time.

        @todo: server hostname check, see rfc2830 section 3.6.
        @return: a deferred that will complete when the TLS handshake is
        complete.
        """
        if ctx is None:
            ctx = ssl.ClientContextFactory()
        # we always delay by one event loop iteration to make
        # sure the previous handler has exited and self.onwire
        # has been cleaned up
        d = defer.Deferred()
        d.addCallback(self._startTLS)
        reactor.callLater(0, d.callback, ctx)
        return d

    def _startTLS(self, ctx):
        if not self.connected:
            raise LDAPClientConnectionLostException()
        elif self.onwire:
            raise LDAPStartTLSBusyError(self.onwire)
        else:
            op = pureldap.LDAPStartTLSRequest()
            d = self.send(op)
            d.addCallback(self._cbStartTLS, ctx)
            return d
