package io.github.nouxel00.grabdrop

import android.app.Application
import androidx.lifecycle.DefaultLifecycleObserver
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.ProcessLifecycleOwner

class GrabDropApp : Application() {
    lateinit var runtime: GrabDropRuntime
        private set

    override fun onCreate() {
        super.onCreate()
        runtime = GrabDropRuntime(this)
        // Réseau actif tant que l'app est visible (et, via le service, tant qu'un objet est en main).
        ProcessLifecycleOwner.get().lifecycle.addObserver(object : DefaultLifecycleObserver {
            override fun onStart(owner: LifecycleOwner) = runtime.onAppVisible(true)
            override fun onStop(owner: LifecycleOwner) = runtime.onAppVisible(false)
        })
    }
}
