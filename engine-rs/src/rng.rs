//! CPython's `random.Random`, reproduced exactly: MT19937, string seeding (version 2),
//! `random()` (genrand_res53), `getrandbits`, `randint`/`randrange` and `choice`.

use sha2::{Digest, Sha512};

const N: usize = 624;
const M: usize = 397;

pub struct PyRandom {
    mt: [u32; N],
    index: usize,
}

impl PyRandom {
    /// `random.Random(s)` for a str seed: `a = s.encode(); a += sha512(a).digest();
    /// n = int.from_bytes(a, "big")`, then init_by_array on the 32-bit little-endian limbs of n.
    pub fn from_str_seed(seed: &str) -> PyRandom {
        let mut bytes = seed.as_bytes().to_vec();
        let digest = Sha512::digest(&bytes);
        bytes.extend_from_slice(&digest);
        // big-endian integer: drop leading zero bytes, then take limbs from the least significant end
        let first = bytes.iter().position(|b| *b != 0).unwrap_or(bytes.len());
        let sig = &bytes[first..];
        let mut key: Vec<u32> = Vec::new();
        let mut end = sig.len();
        while end > 0 {
            let start = end.saturating_sub(4);
            let mut limb = 0u32;
            for b in &sig[start..end] {
                limb = (limb << 8) | *b as u32;
            }
            key.push(limb);
            end = start;
        }
        if key.is_empty() {
            key.push(0);
        }
        let mut r = PyRandom { mt: [0; N], index: N + 1 };
        r.init_by_array(&key);
        r
    }

    fn init_genrand(&mut self, s: u32) {
        self.mt[0] = s;
        for i in 1..N {
            self.mt[i] = 1812433253u32
                .wrapping_mul(self.mt[i - 1] ^ (self.mt[i - 1] >> 30))
                .wrapping_add(i as u32);
        }
        self.index = N;
    }

    fn init_by_array(&mut self, key: &[u32]) {
        self.init_genrand(19650218);
        let mut i = 1usize;
        let mut j = 0usize;
        let mut k = if N > key.len() { N } else { key.len() };
        while k > 0 {
            self.mt[i] = (self.mt[i]
                ^ (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)).wrapping_mul(1664525))
            .wrapping_add(key[j])
            .wrapping_add(j as u32);
            i += 1;
            j += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            if j >= key.len() {
                j = 0;
            }
            k -= 1;
        }
        k = N - 1;
        while k > 0 {
            self.mt[i] = (self.mt[i]
                ^ (self.mt[i - 1] ^ (self.mt[i - 1] >> 30)).wrapping_mul(1566083941))
            .wrapping_sub(i as u32);
            i += 1;
            if i >= N {
                self.mt[0] = self.mt[N - 1];
                i = 1;
            }
            k -= 1;
        }
        self.mt[0] = 0x80000000;
        self.index = N;
    }

    fn genrand_u32(&mut self) -> u32 {
        if self.index >= N {
            for kk in 0..N {
                let y = (self.mt[kk] & 0x80000000) | (self.mt[(kk + 1) % N] & 0x7fffffff);
                let mut v = self.mt[(kk + M) % N] ^ (y >> 1);
                if y & 1 != 0 {
                    v ^= 0x9908b0df;
                }
                self.mt[kk] = v;
            }
            self.index = 0;
        }
        let mut y = self.mt[self.index];
        self.index += 1;
        y ^= y >> 11;
        y ^= (y << 7) & 0x9d2c5680;
        y ^= (y << 15) & 0xefc60000;
        y ^= y >> 18;
        y
    }

    /// `random.random()`
    pub fn random(&mut self) -> f64 {
        let a = (self.genrand_u32() >> 5) as f64;
        let b = (self.genrand_u32() >> 6) as f64;
        (a * 67108864.0 + b) * (1.0 / 9007199254740992.0)
    }

    /// `getrandbits(k)` for 0 < k <= 64
    pub fn getrandbits(&mut self, k: u32) -> u64 {
        if k == 0 {
            return 0;
        }
        if k <= 32 {
            return (self.genrand_u32() >> (32 - k)) as u64;
        }
        // CPython fills 32-bit words least significant first, the last one is shifted down
        let mut out = 0u64;
        let mut rem = k;
        let mut shift = 0u32;
        while rem > 0 {
            let mut w = self.genrand_u32();
            if rem < 32 {
                w >>= 32 - rem;
            }
            out |= (w as u64) << shift;
            shift += 32;
            rem = rem.saturating_sub(32);
        }
        out
    }

    /// `_randbelow_with_getrandbits(n)` for n > 0
    pub fn randbelow(&mut self, n: u64) -> u64 {
        let k = 64 - n.leading_zeros();
        let mut r = self.getrandbits(k);
        while r >= n {
            r = self.getrandbits(k);
        }
        r
    }

    /// `randint(a, b)`
    pub fn randint(&mut self, a: i64, b: i64) -> i64 {
        let width = (b + 1 - a) as u64;
        a + self.randbelow(width) as i64
    }

    /// `choice(seq)` returns an index
    pub fn choice_index(&mut self, len: usize) -> usize {
        self.randbelow(len as u64) as usize
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Expected values come from CPython 3.13: random.Random(seed) then the same calls.
    fn check(seed: &str, floats: [f64; 3], randint: (i64, i64), choice4: usize, bits7: u64, bits40: u64) {
        let mut r = PyRandom::from_str_seed(seed);
        for f in floats {
            assert_eq!(r.random(), f, "random() for {:?}", seed);
        }
        assert_eq!(r.randint(-3, 3), randint.0);
        assert_eq!(r.randint(3, 5), randint.1);
        assert_eq!(r.choice_index(4), choice4);
        assert_eq!(r.getrandbits(7), bits7);
        assert_eq!(r.getrandbits(40), bits40);
    }

    #[test]
    fn matches_cpython_ascii_and_non_ascii_seeds() {
        check("hermes", [0.6632465346769258, 0.9965692312100912, 0.2979092701315553], (1, 3), 1, 65, 976820925557);
        check("Zo\u{eb}", [0.07509478927224611, 0.20493031396531547, 0.6827474302456673], (-2, 4), 1, 108, 300636665319);
        check("5:1:herds", [0.9528509512675707, 0.7307020042831418, 0.19278881322710162], (1, 5), 1, 5, 667534823526);
    }
}
