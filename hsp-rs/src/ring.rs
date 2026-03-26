#[derive(Clone, Debug)]
pub struct RingBuffer<T: Copy + Default, const N: usize> {
    items: [T; N],
    head: usize,
    len: usize,
}

impl<T: Copy + Default, const N: usize> Default for RingBuffer<T, N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<T: Copy + Default, const N: usize> RingBuffer<T, N> {
    pub fn new() -> Self {
        Self {
            items: [T::default(); N],
            head: 0,
            len: 0,
        }
    }

    pub fn push(&mut self, value: T) {
        self.items[self.head] = value;
        self.head = (self.head + 1) % N;
        if self.len < N {
            self.len += 1;
        }
    }

    pub fn len(&self) -> usize {
        self.len
    }

    pub fn is_empty(&self) -> bool {
        self.len == 0
    }

    pub fn is_full(&self) -> bool {
        self.len == N
    }

    pub fn latest(&self) -> Option<T> {
        if self.len == 0 {
            return None;
        }
        let index = if self.head == 0 { N - 1 } else { self.head - 1 };
        Some(self.items[index])
    }

    pub fn iter(&self) -> RingIter<'_, T, N> {
        RingIter {
            ring: self,
            offset: 0,
        }
    }
}

pub struct RingIter<'a, T: Copy + Default, const N: usize> {
    ring: &'a RingBuffer<T, N>,
    offset: usize,
}

impl<'a, T: Copy + Default, const N: usize> Iterator for RingIter<'a, T, N> {
    type Item = T;

    fn next(&mut self) -> Option<Self::Item> {
        if self.offset >= self.ring.len {
            return None;
        }

        let start = if self.ring.len == N { self.ring.head } else { 0 };
        let index = (start + self.offset) % N;
        self.offset += 1;
        Some(self.ring.items[index])
    }
}

#[cfg(test)]
mod tests {
    use super::RingBuffer;

    #[test]
    fn keeps_latest_values_after_wrap() {
        let mut ring = RingBuffer::<u16, 3>::new();
        ring.push(10);
        ring.push(20);
        ring.push(30);
        ring.push(40);

        let values: Vec<u16> = ring.iter().collect();
        assert_eq!(values, vec![20, 30, 40]);
        assert_eq!(ring.latest(), Some(40));
        assert!(ring.is_full());
    }
}
