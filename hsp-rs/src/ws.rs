use std::os::fd::RawFd;

#[repr(u8)]
#[derive(Copy, Clone, Debug, Eq, PartialEq, Default)]
pub enum ClientRole {
    #[default]
    Observer = 0,
    Control = 1,
    Ingest = 2,
}

#[derive(Copy, Clone, Debug)]
pub struct ClientSlot {
    pub fd: RawFd,
    pub occupied: bool,
    pub role: ClientRole,
    pub last_seen_seq: u32,
}

impl ClientSlot {
    pub const EMPTY: Self = Self {
        fd: -1,
        occupied: false,
        role: ClientRole::Observer,
        last_seen_seq: 0,
    };
}

impl Default for ClientSlot {
    fn default() -> Self {
        Self::EMPTY
    }
}

#[derive(Debug)]
pub struct ClientSlab<const N: usize> {
    slots: [ClientSlot; N],
}

impl<const N: usize> Default for ClientSlab<N> {
    fn default() -> Self {
        Self::new()
    }
}

impl<const N: usize> ClientSlab<N> {
    pub fn new() -> Self {
        Self {
            slots: [ClientSlot::EMPTY; N],
        }
    }

    pub fn allocate(&mut self, fd: RawFd, role: ClientRole) -> Option<usize> {
        for (index, slot) in self.slots.iter_mut().enumerate() {
            if !slot.occupied {
                *slot = ClientSlot {
                    fd,
                    occupied: true,
                    role,
                    last_seen_seq: 0,
                };
                return Some(index);
            }
        }
        None
    }

    pub fn release(&mut self, index: usize) {
        if let Some(slot) = self.slots.get_mut(index) {
            *slot = ClientSlot::EMPTY;
        }
    }

    pub fn set_role(&mut self, index: usize, role: ClientRole) {
        if let Some(slot) = self.slots.get_mut(index) {
            if slot.occupied {
                slot.role = role;
            }
        }
    }

    pub fn active_count(&self) -> usize {
        self.slots.iter().filter(|slot| slot.occupied).count()
    }
}
