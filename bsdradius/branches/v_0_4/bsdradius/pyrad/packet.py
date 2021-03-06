# packet.py
# 
# Copyright 2002-2004 Wichert Akkerman <wichert@wiggy.net>
#
# A RADIUS packet as defined in RFC 2138


"""
RADIUS packet 
"""

# HeadURL		$HeadURL: file:///Z:/backup/svn/bsdradius/branches/v_0_4/bsdradius/pyrad/packet.py $
# Author:		$Author: valts $
# File version:	$Revision: 198 $
# Last changes:	$Date: 2006-03-29 13:08:10 +0300 (Tr, 29 Mar 2006) $


__docformat__	= "epytext en"

import md5, struct, types, random, UserDict
from bsdradius import misc
import tools
from types import *
from bsdradius.logger import *

# Packet codes
AccessRequest		= 1
AccessAccept		= 2
AccessReject		= 3
AccountingRequest	= 4
AccountingResponse	= 5
AccessChallenge		= 11
StatusServer		= 12
StatusClient		= 13

# Current ID
CurrentID		= random.randrange(1, 255)

class PacketError(Exception):
	pass


class Packet(UserDict.UserDict):
	"""Packet acts like a standard python map to provide simple access
	to the RADIUS attributes. Since RADIUS allows for repeated
	attributes the value will always be a sequence. pyrad makes sure
	to preserve the ordering when encoding and decoding packets.

	There are two ways to use the map intereface: if attribute
	names are used pyrad take care of en-/decoding data. If
	the attribute type number (or a vendor ID/attribute type
	tuple for vendor attributes) is used you work with the
	raw data.
	"""

	def __init__(self, code=0, id=None, secret="", authenticator=None, **attributes):
		"""Constructor

		@param dict:   RADIUS dictionary
		@type dict:    pyrad.dictionary.Dictionary class
		@param secret: secret needed to communicate with a RADIUS server
		@type secret:  string
		@param id:     packet identifaction number
		@type id:      integer (8 bits)
		@param code:   packet type code
		@type code:    integer (8bits)
		@param packet: raw packet to decode
		@type packet:  string
		"""
		UserDict.UserDict.__init__(self)
		self.code=code
		self.source = None
		if id != None:
			self.id=id
		else:
			self.id=CreateID()
		self.secret=secret
		self.authenticator=authenticator

		if attributes.has_key("dict"):
			self.dict=attributes["dict"]

		if attributes.has_key("packet"):
			self.DecodePacket(attributes["packet"])

		for (key,value) in attributes.items():
			if key in [ "dict", "fd", "packet"]:
				continue

			key=key.replace("_", "-")
			try:
				if isinstance(value, ListType):
					for listItemValue in value:
						self.AddAttribute(key, listItemValue)
				else:
					self.AddAttribute(key, value)
			# silently discard wrong attributes
			except KeyError:
				error ('Item "%s" not found in dictionary. I\'m discarding it.' % key)
				continue
			except:
				error ('Can not add item "%s". I\'m discarding it.' % key)
				misc.printExceptionError(prefix = '  ')
				continue


	def CreateReply(self, **attributes):
		return Packet(self.id, self.secret, self.authenticator,
				dict=self.dict, **attributes)


	def _DecodeValue(self, attr, value):
		if attr.values.HasBackward(value):
			return attr.values.GetBackward(value)
		else:
			return tools.DecodeAttr(attr.type, value)
	

	def _EncodeValue(self, attr, value):
		if attr.values.HasForward(value):
			return attr.values.GetForward(value)
		else:
			return tools.EncodeAttr(attr.type, value)
	

	def _EncodeKeyValues(self, key, values):
		if type(key)!=types.StringType:
			return (key, value)

		attr=self.dict.attributes[key]

		if attr.vendor:
			key=(self.dict.vendors.GetForward(attr.vendor), attr.code)
		else:
			key=attr.code

		return (key,
			map(lambda v,a=attr,s=self: s._EncodeValue(a,v), values))


	def _EncodeKey(self, key):
		if type(key)!=types.StringType:
			return key

		attr=self.dict.attributes[key]
		if attr.vendor:
			return (self.dict.vendors.GetForward(attr.vendor), attr.code)
		else:
			return attr.code
	

	def _DecodeKey(self, key):
		"Turn a key into a string if possible"

		if self.dict.attrindex.HasBackward(key):
			return self.dict.attrindex.GetBackward(key)

		return key


	def AddAttribute(self, key, value):
		"""Add an attribute to the packet.

		@param key:   attribute name or identification
		@type key:    string, attribute code or (vendor code, attribute code) tuple
		@param value: value
		@type value:  depends on type of attribute
		"""
		(key,value)=self._EncodeKeyValues(key, [value])
		value=value[0]

		if self.data.has_key(key):
			self.data[key].append(value)
		else:
			self.data[key]=[value]


	def __getitem__(self, key):
		if type(key)!=types.StringType:
			return self.data[key]

		values=self.data[self._EncodeKey(key)]
		attr=self.dict.attributes[key]
		res=[]
		for v in values:
			res.append(self._DecodeValue(attr, v))
		return res

	

	def has_key(self, key):
		return self.data.has_key(self._EncodeKey(key))


	def __setitem__(self, key, item):
		if type(key)==types.StringType:
			(key,item)=self._EncodeKeyValues(key, [item])
			self.data[key]=item
		else:
			assert(type(item)==types.ListType)
			self.data[key]=[item]


	def keys(self):
		return map(self._DecodeKey, self.data.keys())


	def CreateAuthenticator(self):
		"""Create a packet autenticator.
		
		All RADIUS packets contain a sixteen byte authenticator which
		is used to authenticate replies from the RADIUS server and in
		the password hiding algorithm. This function returns a suitable
		random string that can be used as an authenticator.

		@return: valid packet authenticator
		@rtype: string
		"""

		data=""
		for i in range(16):
			data+=chr(random.randrange(0,256))

		return data


	def CreateID(self):
		"""Create a packet ID
		
		All RADIUS requests have a ID which is used to identify
		a request. This is used to detect retries and replay
		attacks. This functino returns a suitable random number
		that can be used as ID.

		@return: ID number
		@rtype:  integer

		"""
		return random.randrange(0,256)


	def ReplyPacket(self):
		"""Create a ready-to-transmit authentication reply packet

		Return a RADIUS packet which can be directly transmitted
		to a RADIUS server. This differs with Packet() in how
		the authenticator is calculated.
		
		@return: raw packet
		@rtype:  string
		"""
		assert(self.authenticator)
		assert(self.secret)

		attr=self._PktEncodeAttributes()
		header=struct.pack("!BBH", self.code, self.id, (20+len(attr)))

		authenticator=md5.new(header[0:4] + self.authenticator
			+ attr + self.secret).digest()

		return header + authenticator + attr


	def VerifyReply(self, reply, rawreply=None):
		if reply.id!=self.id:
			return 0

		if rawreply==None:
			rawreply=reply.ReplyPacket()
		
		hash=md5.new(rawreply[0:4] + self.authenticator + 
			rawreply[20:] + self.secret).digest()

		if hash!=reply.authenticator:
			return 0

		return 1


	def _PktEncodeAttribute(self, key, value):
		if type(key)==types.TupleType:
			value=struct.pack("!L", key[0]) + \
				self._PktEncodeAttribute(key[1], value)
			key=26

		return struct.pack("!BB", key, (len(value)+2))+value


	def _PktEncodeAttributes(self):
		result=""
		for (code, datalst) in self.items():
			for data in datalst:
				result+=self._PktEncodeAttribute(code, data)

		return result


	def _PktDecodeVendorAttribute(self, data):
		# Check if this packet is long enough to be in the
		# RFC2865 recommended form
		if len(data)<6:
			return (26, data)

		try:
			(vendor, type, length)=struct.unpack("!LBB", data[:6])[0:3]
		except struct.error:
			raise PacketError, "Vender attribute header is corrupt"
		# Another sanity check
		if len(data)!=length+4:
			return (26,data)

		return ((vendor,type), data[6:])


	def DecodePacket(self, packet):
		"""Initialize the object from raw packet data.

		Decode a packet as received from the network and decode
		it.
		
		@param packet: raw packet
		@type packet:  string"""

		try:
			(self.code, self.id, length, self.authenticator)=struct.unpack("!BBH16s", packet[0:20])
		except struct.error:
			raise PacketError, "Packet header is corrupt"
		if len(packet)!=length:
			raise PacketError, "Packet has invalid length"
		if length>8192:
			raise PacketError, "Packet length is too long (%s)" % leng

		self.clear()

		packet=packet[20:]
		while packet:
			try:
				(key, attrlen)=struct.unpack("!BB", packet[0:2])
			except struct.error:
				raise PacketError, "Attribute header is corrupt"

			if attrlen<2:
				raise PacketError, "Attribute length is too small (%d)" % attrlen

			value=packet[2:attrlen]
			if key==26:
				(key,value)=self._PktDecodeVendorAttribute(value)

			if self.data.has_key(key):
				self.data[key].append(value)
			else:
				self.data[key]=[value]

			packet=packet[attrlen:]


	def __str__(self):
		output = ""
		for key, values in self.iteritems():
			attrName = self._DecodeKey(key)
			attr=self.dict.attributes[attrName]
			for val in values:
				output += ("%r: %r\n" % (attrName, self._DecodeValue(attr, val)))
		return output
	
	
	def addClientIpAddress(self):
		self['Client-IP-Address'] = self.source[0]
	
	
	def addRequestAuthenticator(self):
		self['Request-Authenticator'] = self.authenticator



class AuthPacket(Packet):
	def __init__(self, code=AccessRequest, id=None, secret="", authenticator=None, **attributes):
		"""Constructor

		@param code:   packet type code
		@type code:    integer (8bits)
		@param id:     packet identifaction number
		@type id:      integer (8 bits)
		@param secret: secret needed to communicate with a RADIUS server
		@type secret:  string

		@param dict:   RADIUS dictionary
		@type dict:    pyrad.dictionary.Dictionary class

		@param packet: raw packet to decode
		@type packet:  string
		"""
		Packet.__init__(self, code, id, secret, authenticator, **attributes)


	def CreateReply(self, **attributes):
		return AuthPacket(AccessAccept, self.id,
			self.secret, self.authenticator, dict=self.dict,
			**attributes)


	def RequestPacket(self):
		"""Create a ready-to-transmit authentication request packet

		Return a RADIUS packet which can be directly transmitted
		to a RADIUS server.
		
		@return: raw packet
		@rtype:  string
		"""

		attr=self._PktEncodeAttributes()

		if self.authenticator==None:
			self.authenticator=self.CreateAuthenticator()

		if self.id==None:
			self.id=self.CreateID()

		header=struct.pack("!BBH16s", self.code, self.id,
			(20+len(attr)), self.authenticator)

		return header+attr


	def PwDecrypt(self, password):
		"""Unobfuscate a RADIUS password

		RADIUS hides passwords in packets by using an algorithm
		based on the MD5 hash of the pacaket authenticator and RADIUS
		secret. This function reverses the obfuscation process.

		@param password: obfuscated form of password
		@type password:  string
		@return:         plaintext password
		@rtype:          string
		"""
		buf=password
		pw=""

		last=self.authenticator
		while buf:
			hash=md5.new(self.secret+last).digest()
			for i in range(16):
				pw+=chr(ord(hash[i]) ^ ord(buf[i]))

			(last,buf)=(buf[:16], buf[16:])

		while pw.endswith("\x00"):
			pw=pw[:-1]

		return pw


	def PwCrypt(self, password):
		"""Obfuscate password
		
		RADIUS hides passwords in packets by using an algorithm
		based on the MD5 hash of the pacaket authenticator and RADIUS
		secret. If no authenticator has been set before calling PwCrypt
		one is created automatically. Changing the authenticator after
		setting a password that has been encrypted using this function
		will not work.

		@param password: plaintext password
		@type password:  string
		@return:         obfuscated version of the password
		@rtype:          string
		"""
		if self.authenticator==None:
			self.authenticator=self.CreateAuthenticator()

		buf=password
		if len(password)%16!=0:
			buf+="\x00" * (16-(len(password)%16))

		hash=md5.new(self.secret+self.authenticator).digest()
		result=""

		last=self.authenticator
		while buf:
			hash=md5.new(self.secret+last).digest()
			for i in range(16):
				result+=chr(ord(hash[i]) ^ ord(buf[i]))

			last=result[-16:]
			buf=buf[16:]

		return result


	def __str__(self):
		output = "--AuthPacket--------------------------------------------------\n"
		output += Packet.__str__(self)
		return output
		
	
	def decryptAttributes(self):
		"""Decrypt all crypted attributes
			Input: none
			Output: none
		"""
		for key, values in self.iteritems():
			attrName = self._DecodeKey(key)
			# skip unknown attributes
			if not isinstance(attrName, StringType):
				continue
			attr=self.dict.attributes[attrName]
			# decrypt using password decryption method
			if attr.encryptMethod == 1:
				for i in xrange(len(values)):
					# get decrypted password
					decrypted = self.PwDecrypt(values[i])
					# replace encrypted item with decrypted one
					self.data[key][i] = decrypted


class AcctPacket(Packet):
	def __init__(self, code=AccountingRequest, id=None, secret="", authenticator=None, **attributes):
		"""Constructor

		@param dict:   RADIUS dictionary
		@type dict:    pyrad.dictionary.Dictionary class
		@param secret: secret needed to communicate with a RADIUS server
		@type secret:  string
		@param id:     packet identifaction number
		@type id:      integer (8 bits)
		@param code:   packet type code
		@type code:    integer (8bits)
		@param packet: raw packet to decode
		@type packet:  string
		"""
		Packet.__init__(self, code, id, secret, authenticator, **attributes)
		if attributes.has_key("packet"):
			self.raw_packet=attributes["packet"]


	def CreateReply(self, **attributes):
		return AcctPacket(AccountingResponse, self.id,
			self.secret, self.authenticator, dict=self.dict,
			**attributes)

		def VerifyAcctRequest(self):
			"""Verify request authenticator

			@return: True if verification failed else False
			@rtype: boolean
			"""
			assert(self.raw_packet)
			hash=md5.new(self.raw_packet[0:4] + 16*"\x00" + 
					self.raw_packet[20:] + self.secret).digest()

			return hash==self.authenticator

	def RequestPacket(self):
		"""Create a ready-to-transmit authentication request packet

		Return a RADIUS packet which can be directly transmitted
		to a RADIUS server.
		
		@return: raw packet
		@rtype:  string
		"""

		attr=self._PktEncodeAttributes()

		if self.id==None:
			self.id=self.CreateID()

		header=struct.pack("!BBH", self.code, self.id, (20+len(attr)))

		self.authenticator=md5.new(header[0:4] + 16 * "\x00" + attr
			+ self.secret).digest()

		return header + self.authenticator + attr


	def __str__(self):
		output = "--AcctPacket--------------------------------------------------\n"
		output += Packet.__str__(self)
		return output



def CreateID():
	"""Generate a packet ID.

	@return: packet ID
	@rtype:  8 bit integer
	"""
	global CurrentID

	CurrentID=(CurrentID+1)%256
	return CurrentID
