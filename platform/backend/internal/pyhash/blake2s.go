// Package pyhash holds hashes the existing application computes with
// Python's hashlib where Go's libraries do not offer the same parameters.
package pyhash

import (
	"encoding/binary"
	"encoding/hex"
	"math/bits"
)

// blake2sIV is BLAKE2s's initialisation vector (RFC 7693 §2.6).
var blake2sIV = [8]uint32{
	0x6A09E667, 0xBB67AE85, 0x3C6EF372, 0xA54FF53A, 0x510E527F, 0x9B05688C, 0x1F83D9AB, 0x5BE0CD19,
}

// sigma is the message schedule (RFC 7693 §2.7).
var sigma = [10][16]byte{
	{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15},
	{14, 10, 4, 8, 9, 15, 13, 6, 1, 12, 0, 2, 11, 7, 5, 3},
	{11, 8, 12, 0, 5, 2, 15, 13, 10, 14, 3, 6, 7, 1, 9, 4},
	{7, 9, 3, 1, 13, 12, 11, 14, 2, 6, 5, 10, 4, 0, 15, 8},
	{9, 0, 5, 7, 2, 4, 10, 15, 14, 1, 11, 12, 6, 8, 3, 13},
	{2, 12, 6, 10, 0, 11, 8, 3, 4, 13, 7, 5, 15, 14, 1, 9},
	{12, 5, 1, 15, 14, 13, 4, 10, 0, 7, 6, 3, 9, 2, 8, 11},
	{13, 11, 7, 14, 12, 1, 3, 9, 5, 0, 15, 4, 8, 6, 2, 10},
	{6, 15, 14, 9, 11, 3, 0, 8, 12, 2, 13, 7, 1, 4, 10, 5},
	{10, 2, 8, 4, 7, 6, 1, 5, 15, 11, 9, 14, 3, 12, 13, 0},
}

func mix(v *[16]uint32, a, b, c, d int, x, y uint32) {
	v[a] = v[a] + v[b] + x
	v[d] = bits.RotateLeft32(v[d]^v[a], -16)
	v[c] = v[c] + v[d]
	v[b] = bits.RotateLeft32(v[b]^v[c], -12)
	v[a] = v[a] + v[b] + y
	v[d] = bits.RotateLeft32(v[d]^v[a], -8)
	v[c] = v[c] + v[d]
	v[b] = bits.RotateLeft32(v[b]^v[c], -7)
}

func compress(h *[8]uint32, block []byte, t uint64, last bool) {
	var m [16]uint32
	for i := range m {
		m[i] = binary.LittleEndian.Uint32(block[i*4:])
	}
	var v [16]uint32
	copy(v[:8], h[:])
	copy(v[8:], blake2sIV[:])
	v[12] ^= uint32(t)
	v[13] ^= uint32(t >> 32)
	if last {
		v[14] = ^v[14]
	}
	for r := 0; r < 10; r++ {
		s := sigma[r]
		mix(&v, 0, 4, 8, 12, m[s[0]], m[s[1]])
		mix(&v, 1, 5, 9, 13, m[s[2]], m[s[3]])
		mix(&v, 2, 6, 10, 14, m[s[4]], m[s[5]])
		mix(&v, 3, 7, 11, 15, m[s[6]], m[s[7]])
		mix(&v, 0, 5, 10, 15, m[s[8]], m[s[9]])
		mix(&v, 1, 6, 11, 12, m[s[10]], m[s[11]])
		mix(&v, 2, 7, 8, 13, m[s[12]], m[s[13]])
		mix(&v, 3, 4, 9, 14, m[s[14]], m[s[15]])
	}
	for i := range h {
		h[i] ^= v[i] ^ v[i+8]
	}
}

// Blake2sHex is hashlib.blake2s(data, digest_size=size).hexdigest(): unkeyed
// BLAKE2s with the digest length in its parameter block, so a short digest
// is not a prefix of the 32-byte one. size is 1 to 32.
func Blake2sHex(data []byte, size int) string {
	if size < 1 || size > 32 {
		panic("pyhash: a BLAKE2s digest is 1 to 32 bytes")
	}
	h := blake2sIV
	h[0] ^= 0x01010000 ^ uint32(size)
	var t uint64
	block := make([]byte, 64)
	for len(data) > 64 {
		copy(block, data[:64])
		t += 64
		compress(&h, block, t, false)
		data = data[64:]
	}
	for i := range block {
		block[i] = 0
	}
	copy(block, data)
	t += uint64(len(data))
	compress(&h, block, t, true)
	out := make([]byte, 32)
	for i, w := range h {
		binary.LittleEndian.PutUint32(out[i*4:], w)
	}
	return hex.EncodeToString(out[:size])
}
