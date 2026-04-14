package com.ely.agent.service

import android.content.Context
import android.media.MediaRecorder
import android.os.Build
import dagger.hilt.android.qualifiers.ApplicationContext
import java.io.File
import javax.inject.Inject
import javax.inject.Singleton

@Singleton
class VoiceRecorderManager @Inject constructor(@ApplicationContext private val context: Context) {
    private var recorder: MediaRecorder? = null
    private var outputFile: File? = null

    fun startRecording() {
        val file = File(context.cacheDir, "voice_${System.currentTimeMillis()}.m4a")
        outputFile = file
        recorder = (if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) MediaRecorder(context)
                    else @Suppress("DEPRECATION") MediaRecorder()).apply {
            setAudioSource(MediaRecorder.AudioSource.MIC)
            setOutputFormat(MediaRecorder.OutputFormat.MPEG_4)
            setAudioEncoder(MediaRecorder.AudioEncoder.AAC)
            setAudioSamplingRate(16000)
            setAudioEncodingBitRate(64000)
            setOutputFile(file.absolutePath)
            prepare()
            start()
        }
    }

    fun stopRecording(): File? = try {
        recorder?.stop(); recorder?.release(); recorder = null; outputFile
    } catch (e: Exception) {
        recorder?.release(); recorder = null; null
    }

    fun isRecording() = recorder != null
}
