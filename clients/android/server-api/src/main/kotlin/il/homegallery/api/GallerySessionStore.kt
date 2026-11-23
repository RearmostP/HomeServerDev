package il.homegallery.api

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.AtomicFile
import java.io.File
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import org.json.JSONObject

class GallerySessionStore(context: Context, host: String) {
    private val file = AtomicFile(File(context.noBackupFilesDir, "gallery-session.bin"))
    private val associatedData = host.toByteArray(Charsets.UTF_8)

    @Synchronized
    fun read(): JSONObject? {
        return runCatching {
            if (!file.baseFile.exists()) return null
            val data = file.readFully()
            require(data.size in 29..32_768)
            val key = existingKey() ?: error("Missing gallery session key")
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key, GCMParameterSpec(128, data.copyOfRange(0, 12)))
            cipher.updateAAD(associatedData)
            JSONObject(cipher.doFinal(data, 12, data.size - 12).toString(Charsets.UTF_8))
        }.getOrElse {
            clear()
            null
        }
    }

    @Synchronized
    fun save(session: JSONObject) {
        val cipher = Cipher.getInstance(TRANSFORMATION)
        cipher.init(Cipher.ENCRYPT_MODE, existingKey() ?: createKey())
        cipher.updateAAD(associatedData)
        val encrypted = cipher.iv + cipher.doFinal(session.toString().toByteArray(Charsets.UTF_8))
        val output = file.startWrite()
        try {
            output.write(encrypted)
            file.finishWrite(output)
        } catch (error: java.io.IOException) {
            file.failWrite(output)
            throw error
        }
    }

    @Synchronized
    fun clear() = file.delete()

    private fun existingKey(): SecretKey? = KeyStore.getInstance("AndroidKeyStore").run {
        load(null)
        getKey(ALIAS, null) as? SecretKey
    }

    private fun createKey(): SecretKey = KeyGenerator.getInstance(
        KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore",
    ).run {
        init(
            KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .setKeySize(256)
                .build(),
        )
        generateKey()
    }

    companion object {
        private const val ALIAS = "home-gallery-session-v1"
        private const val TRANSFORMATION = "AES/GCM/NoPadding"
    }
}
