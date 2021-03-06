# Copyright (C) 2011-2013 Versile AS
#
# This file is part of Versile Python.
#
# Versile Python is free software: you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public License
# as published by the Free Software Foundation, either version 3 of
# the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

"""Block cipher generated from a number cipher."""
from __future__ import print_function, unicode_literals

from versile.internal import _b2s, _s2b, _vexport, _b_chr, _b_ord, _pyver
from versile.common.util import posint_to_bytes, bytes_to_posint
from versile.crypto import VBlockCipher, VBlockTransform, VCryptoException
from versile.crypto.rand import VUrandom

__all__ = ['VNumBlockCipher']
__all__ = _vexport(__all__)


class VNumBlockCipher(VBlockCipher):
    """A block cipher which is generated by a number cipher.

    The block cipher is set up by defining the maximum block size that
    is guaranteed to fit within the maximum number that can be encoded
    by the number cipher, and convert blocks of data to/from
    numbers. This makes it possible to conveniently use e.g. RSA
    number arithmetics as an encryption engine for a block cipher.

    The block cipher supports CBC chaining mode.

    :param num-cipher:  the cipher to use
    :param cipher_name: the name to set for the cipher
    :param rand:        random data padding to use, or None
    :type  rand:        :class:`versile.crypto.rand.VByteGenerator`

    If *cipher_name* is None then the name of the number cipher is
    used. If *rand* is None then :class:`versile.crypto.rand.VUrandom`
    is used.

    """
    def __init__(self, num_cipher, cipher_name=None, rand=None):
        if cipher_name is None:
            cipher_name = num_cipher.name

        self.__num_cipher = num_cipher
        if rand is None:
            rand = VUrandom()
        self.__rand = rand

        super_init=super(VNumBlockCipher, self).__init__
        super_init(cipher_name, ('cbc',), num_cipher.symmetric)

    def blocksize(self, key=None):
        if key is None:
            raise VCryptoException('Requires key')
        return self.__blocksize(self.__max_num(key))[0]

    def c_blocksize(self, key=None):
        if key is None:
            raise VCryptoException('Requires key')
        return self.__blocksize(self.__max_num(key))[1]

    def encrypter(self, key, iv=None, mode='cbc'):
        if key is None:
            raise VCryptoException('Requires key')
        if iv is None:
            iv = self.blocksize(key)*b'\x00'
        num_encrypter = self.__num_cipher.encrypter(key)
        return _VNumBlockTransform(num_encrypter, self.blocksize(key),
                                   self.c_blocksize(key), iv, mode,
                                   encrypt=True, rand=self.__rand)

    def decrypter(self, key, iv=None, mode='cbc'):
        if key is None:
            raise VCryptoException('Requires key')
        if iv is None:
            iv = self.blocksize(key)*b'\x00'
        num_decrypter = self.__num_cipher.decrypter(key)
        return _VNumBlockTransform(num_decrypter, self.c_blocksize(key),
                                   self.blocksize(key), iv, mode,
                                   encrypt=False, rand=self.__rand)

    @property
    def key_factory(self):
        return self.__num_cipher.key_factory

    def __max_num(self, key):
        try:
            max_num = self.__num_cipher.encrypter(key).max_number
        except:
            try:
                max_num = self.__num_cipher.decrypter(key).max_number
            except:
                raise VCryptoException('Could not determine max number')
        return max_num

    def __blocksize(self, max_num):
        """Compute block size from max number of a num cipher."""
        byte_rep = posint_to_bytes(max_num)
        c_blocksize = len(byte_rep)
        blocksize = c_blocksize - 11
        if blocksize <= 0:
            raise CryptoException('Supported block size must be minimum 1')
        return (blocksize, c_blocksize)


class _VNumBlockTransform(VBlockTransform):
    def __init__(self, num_transform, in_size, out_size, iv, mode, encrypt,
                 rand):
        self.__num_transform = num_transform
        self.__in_size = in_size
        self.__out_size = out_size
        self.__encrypt = encrypt
        self.__rand = rand

        super(_VNumBlockTransform, self).__init__(in_size)

        if encrypt:
            self.__plainsize = in_size
            self.__ciphersize = out_size
        else:
            self.__plainsize = out_size
            self.__ciphersize = in_size

        # iv always uses plaintext blocksize
        if not isinstance(iv, bytes) or len(iv) != self.__plainsize:
            raise VCryptoException('Invalid initialization vector')
        self.__iv = iv

        if mode == 'cbc':
            self.__transform = self.__transform_cbc
        else:
            raise VCryptoException('Mode not supported')

    def _transform(self, data):
        return self.__transform(data)

    def __transform_cbc(self, data):
        len_data = len(data)
        if len_data % self.__in_size:
            raise VCryptoException('Data not block aligned')
        result = []
        start = 0
        while start < len_data:
            end = start + self.__in_size
            block = data[start:end]
            if self.__encrypt:
                if _pyver == 2:
                    indata = b''.join([_s2b(_b_chr(_b_ord(a) ^ _b_ord(b)))
                                       for a, b in zip(block, self.__iv)])
                else:
                    indata = bytes([a ^ b for a, b in zip(block, self.__iv)])
                # Appending random data, similar to RSAES-PKCS1-V1_5-ENCRYPT
                _rand_data = self.__rand(8)
                indata = b''.join((b'\x02', indata, b'\x00', _rand_data))
                cipher = self.__block_transform(indata, self.__in_size+10,
                                                self.__out_size)
                # Can only take plaintext size bytes as the carry-on mask
                self.__iv = cipher[:(self.__plainsize)]
                result.append(cipher)
            else:
                deciphered = self.__block_transform(block, self.__in_size,
                                                    self.__out_size+10)
                if _pyver == 2:
                    if deciphered[0] != b'\x02' or deciphered[-9] != b'\x00':
                        raise VCryptoException('Invalid RSA ciphertext')
                else:
                    if deciphered[0] != 0x02 or deciphered[-9] != 0x00:
                        raise VCryptoException('Invalid RSA ciphertext')
                deciphered = deciphered[1:-8]
                if _pyver == 2:
                    plaintext = b''.join([_s2b(_b_chr(_b_ord(a) ^ _b_ord(b)))
                                          for a, b
                                          in zip(deciphered, self.__iv)])
                else:
                    plaintext = bytes([a ^ b for a, b
                                       in zip(deciphered, self.__iv)])
                # Can only take plaintext size bytes as the carry-on mask
                self.__iv = block[:(self.__plainsize)]
                result.append(plaintext)
            start += self.__in_size
        return b''.join(result)

    def __block_transform(self, block, in_size, out_size):
        if len(block) != in_size:
            raise VCryptoException('Invalid input block size')
        num = bytes_to_posint(block)
        trans_num = self.__num_transform(num)
        trans_block = posint_to_bytes(trans_num)
        trans_block_len = len(trans_block)
        if trans_block_len > out_size:
            raise VCryptoException('Invalid output block size')
        elif trans_block_len < out_size:
            pad_num = out_size - trans_block_len
            trans_block = pad_num*b'\x00' + trans_block
        return trans_block
