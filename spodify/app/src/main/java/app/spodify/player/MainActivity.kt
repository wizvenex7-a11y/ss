package app.spodify.player

import android.Manifest
import android.app.*
import android.content.*
import android.content.res.ColorStateList
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.*
import android.text.*
import android.view.*
import android.widget.*
import java.util.concurrent.Executors

class MainActivity : Activity() {
    private val bg = Color.rgb(16, 18, 17)
    private val surface = Color.rgb(31, 35, 32)
    private val green = Color.rgb(54, 232, 139)
    private val muted = Color.rgb(159, 171, 163)
    private lateinit var root: LinearLayout
    private lateinit var content: LinearLayout
    private lateinit var mini: LinearLayout
    private lateinit var miniTitle: TextView
    private lateinit var miniArtist: TextView
    private lateinit var miniPlay: ImageButton
    private lateinit var db: LibraryStore
    private val worker = Executors.newSingleThreadExecutor()
    private val handler = Handler(Looper.getMainLooper())
    private var tracks = emptyList<Track>()
    private var service: PlaybackService? = null
    private var bound = false
    private var tab = 0
    private var filterLiked = false
    private var importing = false
    private var query = ""
    private var reportedError: String? = null
    private var playerDialog: Dialog? = null
    private var playerUpdate: (() -> Unit)? = null
    private val connection = object : ServiceConnection {
        override fun onServiceConnected(name: ComponentName, binder: IBinder) {
            service = (binder as PlaybackService.LocalBinder).service
            service?.listener = { updatePlayback() }
            updatePlayback()
        }
        override fun onServiceDisconnected(name: ComponentName) { service = null; updatePlayback() }
    }
    private val tick = object : Runnable {
        override fun run() { playerUpdate?.invoke(); handler.postDelayed(this, 500) }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        db = LibraryStore(this)
        tab = savedInstanceState?.getInt("tab") ?: 0
        query = savedInstanceState?.getString("query") ?: ""
        filterLiked = savedInstanceState?.getBoolean("liked") ?: false
        buildShell()
        bound = bindService(Intent(this, PlaybackService::class.java), connection, BIND_AUTO_CREATE)
        reload()
    }

    private fun buildShell() {
        root = column().apply { setBackgroundColor(bg) }
        if (Build.VERSION.SDK_INT >= 30) {
            root.setOnApplyWindowInsetsListener { view, insets ->
                val bars = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                view.setPadding(bars.left, bars.top, bars.right, bars.bottom)
                insets
            }
        } else {
            root.setOnApplyWindowInsetsListener { view, insets ->
                @Suppress("DEPRECATION")
                view.setPadding(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
                insets
            }
        }
        val scroll = ScrollView(this).apply { isFillViewport = true; clipToPadding = false }
        content = column().apply { setPadding(dp(22), dp(24), dp(22), dp(26)) }
        scroll.addView(content)
        root.addView(scroll, LinearLayout.LayoutParams(-1, 0, 1f))
        mini = row().apply { setPadding(dp(12), dp(9), dp(8), dp(9)); background = shape(Color.rgb(39, 57, 47), 12); visibility = View.GONE }
        mini.addView(art(42), LinearLayout.LayoutParams(dp(42), dp(42)).apply { marginEnd = dp(12) })
        val labels = column()
        miniTitle = text("", 14, Color.WHITE, true).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }
        miniArtist = text("", 12, muted).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END }
        labels.addView(miniTitle); labels.addView(miniArtist)
        mini.addView(labels, LinearLayout.LayoutParams(0, -2, 1f))
        miniPlay = icon(android.R.drawable.ic_media_play, "Play", green) { service?.toggle() }
        mini.addView(miniPlay, LinearLayout.LayoutParams(dp(48), dp(48)))
        mini.setOnClickListener { showPlayer() }
        root.addView(mini, LinearLayout.LayoutParams(-1, -2).apply { setMargins(dp(8), 0, dp(8), dp(4)) })
        val nav = row().apply { setPadding(dp(8), dp(8), dp(8), dp(10)) }
        listOf("Home", "Search", "Your library").forEachIndexed { index, title ->
            nav.addView(Button(this).apply {
                text = title; textSize = 12f; isAllCaps = false; setTextColor(if (index == tab) green else muted)
                background = shape(if (index == tab) surface else bg, 22)
                setOnClickListener { tab = index; query = ""; filterLiked = false; buildShell(); render(); updatePlayback() }
            }, LinearLayout.LayoutParams(0, dp(48), 1f).apply { marginStart = dp(3); marginEnd = dp(3) })
        }
        root.addView(nav)
        setContentView(root)
        root.requestApplyInsets()
    }

    private fun render() {
        content.removeAllViews()
        val heading = row()
        val headingLabels = column()
        headingLabels.addView(text("SPODIFY / OFFLINE", 10, green, true).apply { letterSpacing = 0.18f })
        headingLabels.addView(text(when (tab) { 1 -> "Find your sound."; 2 -> "Your library."; else -> "Made for your ears." }, 29, Color.WHITE, true).apply { setPadding(0, dp(9), 0, 0) })
        heading.addView(headingLabels, LinearLayout.LayoutParams(0, -2, 1f))
        heading.addView(icon(android.R.drawable.ic_input_add, "Import audio", green) { importAudio() }, LinearLayout.LayoutParams(dp(48), dp(48)))
        content.addView(heading)
        space(26)
        when (tab) {
            0 -> home()
            1 -> search()
            else -> library()
        }
    }

    private fun home() {
        val hero = column().apply {
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(Color.rgb(42, 86, 60), Color.rgb(25, 40, 31))).apply { cornerRadius = dp(20).toFloat() }
            setPadding(dp(22), dp(24), dp(22), dp(22))
        }
        hero.addView(text("NO ACCOUNT. JUST MUSIC.", 10, green, true).apply { letterSpacing = 0.12f })
        hero.addView(text("Your music.\nYour rules.", 34, Color.WHITE, true).apply { setPadding(0, dp(16), 0, dp(10)) })
        hero.addView(text("Bring your favorite audio files.\nKeep listening, even when you are offline.", 14, Color.rgb(204, 219, 209)))
        hero.addView(primary(if (importing) "Importing…" else "Import your music") { importAudio() }.apply { isEnabled = !importing }, LinearLayout.LayoutParams(-1, dp(52)).apply { topMargin = dp(24) })
        content.addView(hero)
        space(26)
        val collections = row()
        val favorites = collection("Liked songs", "${tracks.count { it.liked }} songs", Color.rgb(66, 48, 104)) {
            tab = 2; filterLiked = true; buildShell(); render(); updatePlayback()
        }
        val all = collection("On your device", "${tracks.size} songs", Color.rgb(27, 68, 55)) {
            tab = 2; filterLiked = false; buildShell(); render(); updatePlayback()
        }
        collections.addView(favorites, LinearLayout.LayoutParams(0, dp(116), 1f).apply { marginEnd = dp(10) })
        collections.addView(all, LinearLayout.LayoutParams(0, dp(116), 1f))
        content.addView(collections)
        space(28)
        content.addView(text("Ready when you are", 22, Color.WHITE, true))
        space(12)
        if (tracks.isEmpty()) empty("A little quiet in here", "Import MP3, M4A, FLAC, OGG, or WAV files you own. Your library stays on this device.")
        else showTracks(tracks.take(8))
        space(20)
        content.addView(text("Independent music player. Not affiliated with Spotify. No streaming catalog or DRM bypass.", 11, muted))
    }

    private fun search() {
        val input = EditText(this).apply {
            hint = "Songs or artists"; setHintTextColor(muted); setTextColor(Color.WHITE); textSize = 16f
            setSingleLine(true); inputType = android.text.InputType.TYPE_CLASS_TEXT
            background = shape(surface, 12); setPadding(dp(16), dp(12), dp(16), dp(12)); setText(query)
            contentDescription = "Search imported songs and artists"
        }
        content.addView(input, LinearLayout.LayoutParams(-1, dp(54)))
        space(24)
        val results = column()
        content.addView(results)
        fun update() {
            results.removeAllViews()
            val matches = tracks.filter { it.title.contains(query, true) || it.artist.contains(query, true) }
            results.addView(text(if (query.isBlank()) "All your music" else "${matches.size} results", 21, Color.WHITE, true))
            if (matches.isEmpty()) {
                results.addView(text(if (tracks.isEmpty()) "Import some audio to start searching." else "No matches. Try a different song or artist.", 14, muted).apply { setPadding(0, dp(20), 0, dp(20)) })
            } else matches.forEach { results.addView(trackRow(it, matches)) }
        }
        input.addTextChangedListener(object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) { query = s?.toString() ?: ""; update() }
            override fun afterTextChanged(s: Editable?) = Unit
        })
        update()
    }

    private fun library() {
        val filters = row()
        listOf("All music", "Liked songs").forEachIndexed { index, title ->
            val selected = filterLiked == (index == 1)
            filters.addView(Button(this).apply {
                text = title; isAllCaps = false; textSize = 13f
                setTextColor(if (selected) bg else Color.WHITE); background = shape(if (selected) green else surface, 22)
                setOnClickListener { filterLiked = index == 1; render() }
            }, LinearLayout.LayoutParams(0, dp(44), 1f).apply { marginEnd = dp(8) })
        }
        content.addView(filters)
        space(24)
        val visible = tracks.filter { !filterLiked || it.liked }
        val summary = row()
        summary.addView(text("${visible.size} songs · on this device", 13, muted), LinearLayout.LayoutParams(0, -2, 1f))
        if (visible.isNotEmpty()) summary.addView(icon(android.R.drawable.ic_media_play, "Play all", green) { play(visible, 0) }, LinearLayout.LayoutParams(dp(48), dp(48)))
        content.addView(summary)
        if (visible.isEmpty()) empty(if (filterLiked) "Keep your favorites close" else "Make yourself at home", if (filterLiked) "Tap the favorite button beside a song to add it here." else "Your library starts with the music you love. Import audio files to begin.")
        else showTracks(visible)
        space(20)
        content.addView(primary(if (importing) "Importing…" else "Import audio files") { importAudio() }.apply { isEnabled = !importing }, LinearLayout.LayoutParams(-1, dp(52)))
    }

    private fun showTracks(items: List<Track>) { items.forEach { content.addView(trackRow(it, items)) } }

    private fun trackRow(track: Track, queue: List<Track>): View {
        val line = row().apply { setPadding(0, dp(9), 0, dp(9)); minimumHeight = dp(68) }
        line.addView(art(48, track.title.hashCode()), LinearLayout.LayoutParams(dp(48), dp(48)).apply { marginEnd = dp(12) })
        val titleBlock = column()
        titleBlock.addView(text(track.title, 15, if (service?.current?.uri == track.uri) green else Color.WHITE, true).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END })
        titleBlock.addView(text("${track.artist} · ${QueuePolicy.time(track.duration.coerceAtMost(Int.MAX_VALUE.toLong()).toInt())}", 12, muted).apply { maxLines = 1; ellipsize = TextUtils.TruncateAt.END; setPadding(0, dp(4), 0, 0) })
        line.addView(titleBlock, LinearLayout.LayoutParams(0, -2, 1f))
        line.addView(icon(if (track.liked) android.R.drawable.btn_star_big_on else android.R.drawable.btn_star_big_off, if (track.liked) "Remove ${track.title} from liked songs" else "Like ${track.title}", if (track.liked) green else muted) {
            worker.execute { db.setLiked(track.uri, !track.liked); loadLibrary() }
        }, LinearLayout.LayoutParams(dp(48), dp(48)))
        line.setOnClickListener { play(queue, queue.indexOf(track)) }
        line.contentDescription = "Play ${track.title} by ${track.artist}"
        return line
    }

    private fun play(queue: List<Track>, index: Int) {
        val playback = service ?: return toast("Player is starting. Please try again.")
        reportedError = null
        playback.play(queue, index)
        if (Build.VERSION.SDK_INT >= 33 && checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 8)
        }
    }

    private fun importAudio() {
        if (importing) return
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            type = "audio/*"
            addCategory(Intent.CATEGORY_OPENABLE)
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true)
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }
        try { @Suppress("DEPRECATION") startActivityForResult(intent, 40) }
        catch (_: ActivityNotFoundException) { toast("No file picker is available on this device.") }
    }

    @Deprecated("Uses platform document picker for API 26 compatibility")
    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        super.onActivityResult(requestCode, resultCode, data)
        if (requestCode != 40 || resultCode != RESULT_OK || data == null) return
        val uris = mutableListOf<Uri>()
        data.clipData?.let { clip -> for (i in 0 until clip.itemCount) uris += clip.getItemAt(i).uri }
        if (uris.isEmpty()) data.data?.let { uris += it }
        importing = true; render()
        worker.execute {
            var failures = 0
            for (uri in uris.distinct()) {
                try {
                    contentResolver.takePersistableUriPermission(uri, Intent.FLAG_GRANT_READ_URI_PERMISSION)
                    db.import(uri)
                } catch (_: Exception) { failures++ }
            }
            val updated = db.tracks()
            runOnUiThread {
                if (!isDestroyed) {
                    tracks = updated; importing = false; render()
                    toast(if (failures == 0) "Your music is ready." else "$failures files could not be imported. Choose supported, locally available audio.")
                }
            }
        }
    }

    private fun reload() { worker.execute { loadLibrary() } }
    private fun loadLibrary() {
        val updated = db.tracks()
        runOnUiThread { if (!isDestroyed) { tracks = updated; render(); updatePlayback() } }
    }

    private fun updatePlayback() {
        val playback = service
        val track = playback?.current
        mini.visibility = if (track == null) View.GONE else View.VISIBLE
        miniTitle.text = track?.title ?: ""
        miniArtist.text = if (playback?.loading == true) "Loading audio…" else track?.artist ?: ""
        val active = playback?.playing == true
        miniPlay.setImageResource(if (active) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play)
        miniPlay.contentDescription = if (active) "Pause" else "Play"
        playback?.error?.let { if (it != reportedError) { reportedError = it; toast(it) } }
        playerUpdate?.invoke()
    }

    private fun showPlayer() {
        val playback = service ?: return
        if (playback.current == null || playerDialog?.isShowing == true) return
        val dialog = Dialog(this, android.R.style.Theme_Material_NoActionBar)
        playerDialog = dialog
        val scroll = ScrollView(this).apply { setBackgroundColor(bg) }
        val body = column().apply { setPadding(dp(28), dp(28), dp(28), dp(36)) }
        scroll.addView(body)
        body.addView(text("NOW PLAYING / YOUR DEVICE", 11, green, true).apply { letterSpacing = 0.12f })
        body.addView(Button(this).apply { text = getString(R.string.back_to_music); isAllCaps = false; setTextColor(muted); setBackgroundColor(Color.TRANSPARENT); setOnClickListener { dialog.dismiss() } })
        body.addView(art(260, playback.current!!.title.hashCode()), LinearLayout.LayoutParams(-1, dp(260)).apply { topMargin = dp(18); bottomMargin = dp(32) })
        val title = text("", 27, Color.WHITE, true)
        val artist = text("", 16, muted).apply { setPadding(0, dp(8), 0, dp(20)) }
        body.addView(title); body.addView(artist)
        val seek = SeekBar(this).apply { progressTintList = ColorStateList.valueOf(green); thumbTintList = ColorStateList.valueOf(green); contentDescription = "Playback position" }
        body.addView(seek)
        val times = row()
        val elapsed = text("0:00", 12, muted)
        val length = text("0:00", 12, muted)
        times.addView(elapsed, LinearLayout.LayoutParams(0, -2, 1f)); times.addView(length)
        body.addView(times)
        val controls = row().apply { gravity = Gravity.CENTER; setPadding(0, dp(22), 0, dp(20)) }
        controls.addView(icon(android.R.drawable.ic_media_previous, "Previous track", Color.WHITE) { playback.previous() }, LinearLayout.LayoutParams(dp(64), dp(64)))
        val play = icon(android.R.drawable.ic_media_play, "Play", bg) { playback.toggle() }.apply { background = shape(green, 40); setPadding(dp(20), dp(20), dp(20), dp(20)) }
        controls.addView(play, LinearLayout.LayoutParams(dp(80), dp(80)).apply { marginStart = dp(22); marginEnd = dp(22) })
        controls.addView(icon(android.R.drawable.ic_media_next, "Next track", Color.WHITE) { playback.next() }, LinearLayout.LayoutParams(dp(64), dp(64)))
        body.addView(controls)
        val modes = row()
        val shuffle = Button(this).apply { isAllCaps = false; setOnClickListener { playback.shuffle = !playback.shuffle; playerUpdate?.invoke() } }
        val repeat = Button(this).apply { isAllCaps = false; setOnClickListener { playback.repeat = !playback.repeat; playerUpdate?.invoke() } }
        modes.addView(shuffle, LinearLayout.LayoutParams(0, dp(52), 1f).apply { marginEnd = dp(8) })
        modes.addView(repeat, LinearLayout.LayoutParams(0, dp(52), 1f))
        body.addView(modes)
        body.addView(text("Your files. No account. No connection needed.", 12, muted).apply { gravity = Gravity.CENTER; setPadding(0, dp(28), 0, 0) })
        var dragging = false
        seek.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onStartTrackingTouch(bar: SeekBar) { dragging = true }
            override fun onStopTrackingTouch(bar: SeekBar) { playback.seek(bar.progress); dragging = false }
            override fun onProgressChanged(bar: SeekBar, progress: Int, fromUser: Boolean) { if (fromUser) elapsed.text = QueuePolicy.time(progress) }
        })
        playerUpdate = {
            title.text = playback.current?.title
            artist.text = if (playback.loading) "Loading audio…" else playback.current?.artist
            if (!dragging) { seek.max = playback.duration; seek.progress = playback.position; elapsed.text = QueuePolicy.time(playback.position) }
            length.text = QueuePolicy.time(playback.duration)
            play.setImageResource(if (playback.playing) android.R.drawable.ic_media_pause else android.R.drawable.ic_media_play)
            play.contentDescription = if (playback.playing) "Pause" else "Play"
            shuffle.text = if (playback.shuffle) "Shuffle: on" else "Shuffle: off"
            repeat.text = if (playback.repeat) "Repeat: on" else "Repeat: off"
            shuffle.setTextColor(if (playback.shuffle) green else muted); shuffle.background = shape(surface, 24)
            repeat.setTextColor(if (playback.repeat) green else muted); repeat.background = shape(surface, 24)
        }
        dialog.setOnDismissListener { playerUpdate = null; playerDialog = null }
        dialog.setContentView(scroll)
        dialog.show()
        dialog.window?.setLayout(-1, -1)
        playerUpdate?.invoke()
    }

    private fun collection(title: String, subtitle: String, color: Int, action: () -> Unit): View = column().apply {
        background = shape(color, 14); setPadding(dp(16), dp(18), dp(16), dp(18))
        addView(text(title, 16, Color.WHITE, true)); addView(text(subtitle, 12, Color.rgb(211, 218, 214)).apply { setPadding(0, dp(9), 0, 0) })
        isFocusable = true; contentDescription = "$title, $subtitle"; setOnClickListener { action() }
    }
    private fun empty(title: String, description: String) {
        content.addView(column().apply {
            background = shape(surface, 14); setPadding(dp(20), dp(22), dp(20), dp(24))
            addView(text(title, 18, Color.WHITE, true))
            addView(text(description, 14, muted).apply { setPadding(0, dp(10), 0, 0); setLineSpacing(dp(3).toFloat(), 1f) })
        })
    }
    private fun art(size: Int, seed: Int = 0): View = FrameLayout(this).apply {
        val colors = arrayOf(intArrayOf(0xff375948.toInt(), 0xff17271f.toInt()), intArrayOf(0xff5a4677.toInt(), 0xff24202c.toInt()), intArrayOf(0xff6a5637.toInt(), 0xff2c271e.toInt()))
        background = GradientDrawable(GradientDrawable.Orientation.TL_BR, colors[Math.floorMod(seed, colors.size)]).apply { cornerRadius = dp(12).toFloat() }
        addView(ImageView(this@MainActivity).apply { setImageResource(R.drawable.ic_app); alpha = 0.85f }, FrameLayout.LayoutParams(dp(size / 2), dp(size / 2), Gravity.CENTER))
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private fun text(value: String, size: Int, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = value; textSize = size.toFloat(); setTextColor(color); if (bold) setTypeface(typeface, Typeface.BOLD)
    }
    private fun primary(title: String, action: () -> Unit) = Button(this).apply {
        text = title; textSize = 14f; isAllCaps = false; setTypeface(typeface, Typeface.BOLD); setTextColor(bg); background = shape(green, 28); setOnClickListener { action() }
    }
    private fun icon(resource: Int, label: String, tint: Int, action: () -> Unit) = ImageButton(this).apply {
        setImageResource(resource); imageTintList = ColorStateList.valueOf(tint); contentDescription = label; background = shape(Color.TRANSPARENT, 24)
        setPadding(dp(12), dp(12), dp(12), dp(12)); setOnClickListener { action() }
    }
    private fun column() = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
    private fun row() = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
    private fun shape(color: Int, radius: Int) = GradientDrawable().apply { setColor(color); cornerRadius = dp(radius).toFloat() }
    private fun space(height: Int) { content.addView(Space(this), LinearLayout.LayoutParams(1, dp(height))) }
    private fun dp(value: Int) = (value * resources.displayMetrics.density).toInt()
    private fun toast(message: String) { Toast.makeText(this, message, Toast.LENGTH_LONG).show() }
    override fun onStart() { super.onStart(); handler.post(tick) }
    override fun onStop() { handler.removeCallbacks(tick); super.onStop() }
    override fun onSaveInstanceState(outState: Bundle) { outState.putInt("tab", tab); outState.putString("query", query); outState.putBoolean("liked", filterLiked); super.onSaveInstanceState(outState) }
    override fun onDestroy() {
        playerDialog?.dismiss(); service?.listener = null
        if (bound) unbindService(connection)
        worker.execute { db.close() }; worker.shutdown()
        super.onDestroy()
    }
}
