package app.spodify.player

object QueuePolicy {
    fun nextIndex(current: Int, size: Int, repeat: Boolean, shuffle: Boolean, randomOffset: Int = 0): Int? {
        if (size <= 0) return null
        if (shuffle && size > 1) return (current + 1 + Math.floorMod(randomOffset, size - 1)) % size
        if (current + 1 < size) return current + 1
        return if (repeat) 0 else null
    }

    fun time(milliseconds: Int): String {
        val seconds = milliseconds.coerceAtLeast(0) / 1000
        return "%d:%02d".format(java.util.Locale.ROOT, seconds / 60, seconds % 60)
    }
}
