package com.squad.vpn.ui

import android.content.Context
import android.graphics.SurfaceTexture
import android.media.MediaPlayer
import android.view.Surface
import android.view.TextureView
import androidx.annotation.RawRes
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.lifecycle.compose.LocalLifecycleOwner
import androidx.compose.ui.viewinterop.AndroidView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver

/**
 * A silent video from res/raw playing in a loop. TextureView (not
 * SurfaceView) so it can be clipped, faded and scaled like any other
 * composable. Pauses while the app is in the background.
 */
@Composable
fun LoopVideo(@RawRes res: Int, modifier: Modifier = Modifier) {
    val holder = remember { PlayerHolder() }
    val lifecycle = LocalLifecycleOwner.current.lifecycle
    DisposableEffect(lifecycle) {
        val observer = LifecycleEventObserver { _, event ->
            when (event) {
                Lifecycle.Event.ON_START -> holder.resume()
                Lifecycle.Event.ON_STOP -> holder.pause()
                else -> Unit
            }
        }
        lifecycle.addObserver(observer)
        onDispose {
            lifecycle.removeObserver(observer)
            holder.release()
        }
    }
    AndroidView(
        factory = { context ->
            TextureView(context).apply {
                isOpaque = false
                surfaceTextureListener = object : TextureView.SurfaceTextureListener {
                    override fun onSurfaceTextureAvailable(texture: SurfaceTexture, width: Int, height: Int) {
                        holder.start(context, res, Surface(texture))
                    }

                    override fun onSurfaceTextureDestroyed(texture: SurfaceTexture): Boolean {
                        holder.release()
                        return true
                    }

                    override fun onSurfaceTextureSizeChanged(texture: SurfaceTexture, width: Int, height: Int) = Unit
                    override fun onSurfaceTextureUpdated(texture: SurfaceTexture) = Unit
                }
            }
        },
        modifier = modifier,
    )
}

private class PlayerHolder {
    private var player: MediaPlayer? = null
    private var surface: Surface? = null
    private var paused = false

    fun start(context: Context, @RawRes res: Int, target: Surface) {
        release()
        surface = target
        // A broken or unsupported video just leaves the still image showing.
        player = runCatching {
            MediaPlayer.create(context, res)?.apply {
                setSurface(target)
                setVolume(0f, 0f)
                isLooping = true
                if (!paused) start()
            }
        }.getOrNull()
    }

    fun pause() {
        paused = true
        runCatching { player?.takeIf { it.isPlaying }?.pause() }
    }

    fun resume() {
        paused = false
        runCatching { player?.start() }
    }

    fun release() {
        runCatching { player?.release() }
        player = null
        surface?.release()
        surface = null
    }
}
