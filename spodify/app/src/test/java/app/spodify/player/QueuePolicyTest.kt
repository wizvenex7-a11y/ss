package app.spodify.player

import org.junit.Assert.*
import org.junit.Test

class QueuePolicyTest {
    @Test fun emptyQueueStops() { assertNull(QueuePolicy.nextIndex(0, 0, true, true)) }
    @Test fun endStopsWithoutRepeat() { assertNull(QueuePolicy.nextIndex(2, 3, false, false)) }
    @Test fun repeatWraps() { assertEquals(0, QueuePolicy.nextIndex(2, 3, true, false)) }
    @Test fun ordinaryNext() { assertEquals(1, QueuePolicy.nextIndex(0, 3, false, false)) }
    @Test fun shuffleDoesNotRepeatCurrent() {
        for (current in 0..4) for (offset in -10..10) {
            val next = QueuePolicy.nextIndex(current, 5, false, true, offset)!!
            assertTrue(next in 0..4)
            assertNotEquals(current, next)
        }
    }
    @Test fun singleTrackStopsUnlessRepeat() {
        assertNull(QueuePolicy.nextIndex(0, 1, false, true))
        assertEquals(0, QueuePolicy.nextIndex(0, 1, true, true))
    }
    @Test fun formatsTime() {
        assertEquals("0:00", QueuePolicy.time(-1))
        assertEquals("3:05", QueuePolicy.time(185000))
        assertEquals("60:00", QueuePolicy.time(3600000))
    }
}
