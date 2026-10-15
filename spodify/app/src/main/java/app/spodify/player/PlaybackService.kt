package app.spodify.player

import android.app.*
import android.content.*
import android.graphics.drawable.Icon
import android.media.*
import android.media.session.MediaSession
import android.media.session.PlaybackState
import android.net.Uri
import android.os.*

class PlaybackService : Service() {
    inner class LocalBinder : Binder() { val service get() = this@PlaybackService }
    private val binder = LocalBinder()
    private var player: MediaPlayer? = null
    private var prepared = false
    private var foreground = false
    private var resumeOnFocus = false
    private lateinit var audio: AudioManager
    private lateinit var focus: AudioFocusRequest
    private lateinit var session: MediaSession
    private var queue: List<Track> = emptyList()
    private var index = -1
    var current: Track? = null
        private set
    var shuffle = false
    var repeat = false
    var loading = false
        private set
    var listener: (() -> Unit)? = null
    var error: String? = null
        private set
    val playing get() = prepared && player?.isPlaying == true
    val position get() = if (prepared) player?.currentPosition ?: 0 else 0
    val duration get() = if (prepared) player?.duration ?: 0 else 0

    private val noisy = object : BroadcastReceiver() {
        override fun onReceive(context: Context, intent: Intent) { pause() }
    }

    override fun onCreate() {
        super.onCreate()
        audio = getSystemService(AudioManager::class.java)
        val attributes = AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build()
        focus = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN).setAudioAttributes(attributes)
            .setOnAudioFocusChangeListener { change ->
                when (change) {
                    AudioManager.AUDIOFOCUS_LOSS -> { resumeOnFocus = false; pause() }
                    AudioManager.AUDIOFOCUS_LOSS_TRANSIENT -> { resumeOnFocus = playing; pause(false) }
                    AudioManager.AUDIOFOCUS_LOSS_TRANSIENT_CAN_DUCK -> player?.setVolume(0.2f, 0.2f)
                    AudioManager.AUDIOFOCUS_GAIN -> {
                        player?.setVolume(1f, 1f)
                        if (resumeOnFocus) { resumeOnFocus = false; resume() }
                    }
                }
            }.build()
        session = MediaSession(this, "Spodify").apply {
            setCallback(object : MediaSession.Callback() {
                override fun onPlay() = resume()
                override fun onPause() = pause()
                override fun onSkipToNext() = next()
                override fun onSkipToPrevious() = previous()
                override fun onSeekTo(pos: Long) = seek(pos.toInt())
                override fun onStop() = stopPlayback()
            })
        }
        getSystemService(NotificationManager::class.java).createNotificationChannel(NotificationChannel("playback", "Music playback", NotificationManager.IMPORTANCE_LOW))
        if (Build.VERSION.SDK_INT >= 33) registerReceiver(noisy, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY), RECEIVER_NOT_EXPORTED)
        else registerReceiver(noisy, IntentFilter(AudioManager.ACTION_AUDIO_BECOMING_NOISY))
    }

    override fun onBind(intent: Intent): IBinder = binder
    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        when (intent?.action) {
            "toggle" -> toggle()
            "next" -> next()
            "previous" -> previous()
            "stop" -> stopPlayback()
        }
        return START_NOT_STICKY
    }

    fun play(tracks: List<Track>, selected: Int) {
        if (selected !in tracks.indices) return
        queue = tracks.toList()
        index = selected
        current = queue[index]
        error = null
        loading = true
        prepared = false
        player?.release()
        player = null
        startForegroundService(Intent(this, PlaybackService::class.java))
        startForeground(7, notification())
        foreground = true
        if (audio.requestAudioFocus(focus) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            fail("Audio is in use by another app. Try again.")
            return
        }
        session.isActive = true
        try {
            player = MediaPlayer().apply {
                setAudioAttributes(AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_MEDIA).setContentType(AudioAttributes.CONTENT_TYPE_MUSIC).build())
                setWakeMode(applicationContext, PowerManager.PARTIAL_WAKE_LOCK)
                setDataSource(applicationContext, Uri.parse(current!!.uri))
                setOnPreparedListener {
                    prepared = true
                    loading = false
                    it.start()
                    publish()
                }
                setOnCompletionListener { next() }
                setOnErrorListener { _, _, _ -> fail("This file cannot be played. Re-import it if it moved."); true }
                prepareAsync()
            }
        } catch (_: Exception) { fail("Cannot open this audio file. Please import it again.") }
        publish()
    }

    fun toggle() { if (playing || loading) pause() else resume() }
    fun resume() {
        if (loading) return
        if (!prepared) {
            if (index in queue.indices) play(queue, index)
            return
        }
        startForegroundService(Intent(this, PlaybackService::class.java))
        startForeground(7, notification())
        foreground = true
        if (audio.requestAudioFocus(focus) != AudioManager.AUDIOFOCUS_REQUEST_GRANTED) {
            fail("Audio is in use by another app. Try again.")
            return
        }
        player?.start()
        session.isActive = true
        publish()
    }

    fun pause(abandonFocus: Boolean = true) {
        if (loading) {
            player?.release()
            player = null
            prepared = false
            loading = false
        } else if (playing) player?.pause()
        if (abandonFocus) { resumeOnFocus = false; audio.abandonAudioFocusRequest(focus) }
        publish()
        if (foreground) { stopForeground(STOP_FOREGROUND_DETACH); foreground = false }
        stopSelf()
    }

    fun seek(value: Int) {
        if (prepared) player?.seekTo(value.coerceIn(0, duration))
        publish()
    }

    fun next() {
        val next = QueuePolicy.nextIndex(index, queue.size, repeat, shuffle, kotlin.random.Random.nextInt(Int.MAX_VALUE))
        if (next != null) play(queue, next) else { pause(); seek(0) }
    }

    fun previous() {
        if (position > 3000) seek(0)
        else if (queue.isNotEmpty()) play(queue, (index - 1).coerceAtLeast(0))
    }

    fun stopPlayback() {
        player?.release()
        player = null
        prepared = false
        loading = false
        audio.abandonAudioFocusRequest(focus)
        session.isActive = false
        stopForeground(STOP_FOREGROUND_REMOVE)
        foreground = false
        listener?.invoke()
        stopSelf()
    }

    private fun fail(message: String) {
        error = message
        stopPlayback()
    }

    private fun publish() {
        val state = when { loading -> PlaybackState.STATE_BUFFERING; playing -> PlaybackState.STATE_PLAYING; else -> PlaybackState.STATE_PAUSED }
        session.setPlaybackState(PlaybackState.Builder().setActions(PlaybackState.ACTION_PLAY or PlaybackState.ACTION_PAUSE or PlaybackState.ACTION_PLAY_PAUSE or PlaybackState.ACTION_SKIP_TO_NEXT or PlaybackState.ACTION_SKIP_TO_PREVIOUS or PlaybackState.ACTION_SEEK_TO or PlaybackState.ACTION_STOP).setState(state, position.toLong(), if (playing) 1f else 0f).build())
        current?.let {
            session.setMetadata(MediaMetadata.Builder().putString(MediaMetadata.METADATA_KEY_TITLE, it.title).putString(MediaMetadata.METADATA_KEY_ARTIST, it.artist).putLong(MediaMetadata.METADATA_KEY_DURATION, duration.toLong()).build())
            getSystemService(NotificationManager::class.java).notify(7, notification())
        }
        listener?.invoke()
    }

    private fun notification(): Notification {
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        fun action(name: String) = PendingIntent.getService(this, name.hashCode(), Intent(this, PlaybackService::class.java).setAction(name), PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
        return Notification.Builder(this, "playback").setSmallIcon(R.drawable.ic_app)
            .setContentTitle(current?.title ?: "Spodify").setContentText(current?.artist ?: "Your music, without limits")
            .setContentIntent(open).setVisibility(Notification.VISIBILITY_PUBLIC).setOnlyAlertOnce(true).setOngoing(playing || loading)
            .addAction(Notification.Action.Builder(Icon.createWithResource(this, android.R.drawable.ic_media_previous), "Previous", action("previous")).build())
            .addAction(Notification.Action.Builder(Icon.createWithResource(this, if (playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play), if (playing) "Pause" else "Play", action("toggle")).build())
            .addAction(Notification.Action.Builder(Icon.createWithResource(this, android.R.drawable.ic_media_next), "Next", action("next")).build())
            .setStyle(Notification.MediaStyle().setMediaSession(session.sessionToken).setShowActionsInCompactView(0, 1, 2))
            .setDeleteIntent(action("stop")).build()
    }

    override fun onDestroy() {
        listener = null
        player?.release()
        audio.abandonAudioFocusRequest(focus)
        session.release()
        unregisterReceiver(noisy)
        getSystemService(NotificationManager::class.java).cancel(7)
        super.onDestroy()
    }
}
