// Package pyrandom is CPython's random.Random for a string seed: the
// Mersenne Twister seeded as random.seed(str) seeds it (version 2: the
// string's bytes followed by their SHA-512), getrandbits, and sample, so a
// draw the existing application seeds by name picks the same items here.
package pyrandom

import (
	"crypto/sha512"
	"math"
	"math/big"
	"math/bits"
)

const (
	n         = 624
	m         = 397
	matrixA   = 0x9908b0df
	upperMask = 0x80000000
	lowerMask = 0x7fffffff
)

// Random is one generator.
type Random struct {
	mt  [n]uint32
	mti int
}

// New is random.Random(seed) for a str seed.
func New(seed string) *Random {
	b := []byte(seed)
	sum := sha512.Sum512(b)
	value := new(big.Int).SetBytes(append(append([]byte{}, b...), sum[:]...))
	// The key is the integer's 32-bit words, least significant first.
	raw := value.Bytes() // big-endian
	words := (len(raw) + 3) / 4
	if words == 0 {
		words = 1
	}
	key := make([]uint32, words)
	for i := 0; i < len(raw); i++ {
		byteIndex := len(raw) - 1 - i // from the least significant byte
		key[i/4] |= uint32(raw[byteIndex]) << (8 * uint(i%4))
	}
	r := &Random{}
	r.initByArray(key)
	return r
}

func (r *Random) initGenrand(s uint32) {
	r.mt[0] = s
	for i := 1; i < n; i++ {
		r.mt[i] = 1812433253*(r.mt[i-1]^(r.mt[i-1]>>30)) + uint32(i)
	}
	r.mti = n
}

func (r *Random) initByArray(key []uint32) {
	r.initGenrand(19650218)
	i, j := 1, 0
	k := max(n, len(key))
	for ; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1664525)) + key[j] + uint32(j)
		i++
		j++
		if i >= n {
			r.mt[0] = r.mt[n-1]
			i = 1
		}
		if j >= len(key) {
			j = 0
		}
	}
	for k = n - 1; k > 0; k-- {
		r.mt[i] = (r.mt[i] ^ ((r.mt[i-1] ^ (r.mt[i-1] >> 30)) * 1566083941)) - uint32(i)
		i++
		if i >= n {
			r.mt[0] = r.mt[n-1]
			i = 1
		}
	}
	r.mt[0] = 0x80000000
}

// GetRandBits32 is genrand_uint32: one 32-bit word.
func (r *Random) GetRandBits32() uint32 {
	if r.mti >= n {
		var kk int
		mag := [2]uint32{0, matrixA}
		for kk = 0; kk < n-m; kk++ {
			y := (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
			r.mt[kk] = r.mt[kk+m] ^ (y >> 1) ^ mag[y&1]
		}
		for ; kk < n-1; kk++ {
			y := (r.mt[kk] & upperMask) | (r.mt[kk+1] & lowerMask)
			r.mt[kk] = r.mt[kk+(m-n)] ^ (y >> 1) ^ mag[y&1]
		}
		y := (r.mt[n-1] & upperMask) | (r.mt[0] & lowerMask)
		r.mt[n-1] = r.mt[m-1] ^ (y >> 1) ^ mag[y&1]
		r.mti = 0
	}
	y := r.mt[r.mti]
	r.mti++
	y ^= y >> 11
	y ^= (y << 7) & 0x9d2c5680
	y ^= (y << 15) & 0xefc60000
	y ^= y >> 18
	return y
}

// getRandBits is getrandbits(k) for 0 < k <= 32.
func (r *Random) getRandBits(k int) uint32 {
	return r.GetRandBits32() >> (32 - uint(k))
}

// randBelow is _randbelow_with_getrandbits(n), for 0 < below < 2**32.
func (r *Random) randBelow(below int) int {
	k := bits.Len(uint(below))
	v := int(r.getRandBits(k))
	for v >= below {
		v = int(r.getRandBits(k))
	}
	return v
}

// Sample is sample(range(population), k): k distinct indexes, in the order
// CPython draws them. It panics on k outside [0, population], as CPython
// raises.
func (r *Random) Sample(population, k int) []int {
	if k < 0 || k > population {
		panic("pyrandom: sample larger than population or is negative")
	}
	result := make([]int, k)
	setsize := 21
	if k > 5 {
		setsize += int(math.Pow(4, math.Ceil(math.Log(float64(k*3))/math.Log(4))))
	}
	if population <= setsize {
		pool := make([]int, population)
		for i := range pool {
			pool[i] = i
		}
		for i := 0; i < k; i++ {
			j := r.randBelow(population - i)
			result[i] = pool[j]
			pool[j] = pool[population-i-1]
		}
		return result
	}
	selected := map[int]bool{}
	for i := 0; i < k; i++ {
		j := r.randBelow(population)
		for selected[j] {
			j = r.randBelow(population)
		}
		selected[j] = true
		result[i] = j
	}
	return result
}
