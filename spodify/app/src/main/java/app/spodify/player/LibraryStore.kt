package app.spodify.player

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import android.media.MediaMetadataRetriever
import android.net.Uri
import android.provider.OpenableColumns

data class Track(val uri: String, val title: String, val artist: String, val duration: Long, val liked: Boolean)

class LibraryStore(private val context: Context) : SQLiteOpenHelper(context, "library.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("CREATE TABLE tracks (uri TEXT PRIMARY KEY, title TEXT NOT NULL, artist TEXT NOT NULL, duration INTEGER NOT NULL, liked INTEGER NOT NULL DEFAULT 0)")
    }
    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun tracks(): List<Track> {
        val result = mutableListOf<Track>()
        readableDatabase.query("tracks", null, null, null, null, null, "title COLLATE NOCASE").use { cursor ->
            while (cursor.moveToNext()) result += Track(cursor.getString(0), cursor.getString(1), cursor.getString(2), cursor.getLong(3), cursor.getInt(4) != 0)
        }
        return result
    }

    fun import(uri: Uri) {
        var filename = "Untitled audio"
        context.contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
            if (it.moveToFirst()) filename = it.getString(0) ?: filename
        }
        val metadata = MediaMetadataRetriever()
        try {
            metadata.setDataSource(context, uri)
            val duration = metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_DURATION)?.toLongOrNull() ?: 0L
            require(duration > 0L) { "Not a supported audio file" }
            val values = ContentValues().apply {
                put("uri", uri.toString())
                put("title", metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_TITLE)?.takeIf { it.isNotBlank() } ?: filename.substringBeforeLast('.'))
                put("artist", metadata.extractMetadata(MediaMetadataRetriever.METADATA_KEY_ARTIST)?.takeIf { it.isNotBlank() } ?: "Unknown artist")
                put("duration", duration)
            }
            writableDatabase.insertWithOnConflict("tracks", null, values, SQLiteDatabase.CONFLICT_IGNORE)
        } finally { metadata.release() }
    }

    fun setLiked(uri: String, liked: Boolean) {
        writableDatabase.update("tracks", ContentValues().apply { put("liked", if (liked) 1 else 0) }, "uri = ?", arrayOf(uri))
    }
}
