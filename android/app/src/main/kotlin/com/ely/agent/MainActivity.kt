// =============================================================================
// @project    ELY — Exactly Like You
// @file       android/app/src/main/kotlin/com/ely/agent/MainActivity.kt
// @brief      Main activity — Compose entry point
//
// @author     Franck OLLIVIER <contact@agent-ely.fr>
// @copyright  Copyright (c) 2025-2026 Franck OLLIVIER — All rights reserved
// @license    PolyForm Strict License 1.0.0
//             https://polyformproject.org/licenses/strict/1.0.0/
// @version    1.1.0
// @link       https://github.com/franckolv-dev/PhysicalAgent
//
// RÉSUMÉ DES CONDITIONS :
//   - AUTORISÉ : Utilisation personnelle, éducative et tests privés.
//   - INTERDIT : Toute utilisation commerciale sans accord préalable.
//   - INTERDIT : Redistribution de versions modifiées de ce code.
// =============================================================================

package com.ely.agent

import android.Manifest
import android.os.Build
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.lifecycle.lifecycleScope
import com.ely.agent.core.datastore.userPreferencesDataStore
import com.ely.agent.core.fcm.FcmTokenManager
import com.ely.agent.core.model.ThemePreference
import com.ely.agent.ui.navigation.AppNavGraph
import com.ely.agent.ui.theme.ElyTheme
import dagger.hilt.android.AndroidEntryPoint
import kotlinx.coroutines.launch
import javax.inject.Inject

@AndroidEntryPoint
class MainActivity : ComponentActivity() {

    @Inject lateinit var fcmTokenManager: FcmTokenManager

    /**
     * Request every runtime permission we declare in the manifest on first
     * launch, in a single system dialog chain. Users can still revoke any
     * of them later from Settings → Apps → ELY.
     *
     * `MANAGE_EXTERNAL_STORAGE` is NOT included here — it's a special
     * permission that only Settings can grant (user taps "Autoriser l'accès
     * à tous les fichiers" in the File Manager screen).
     */
    private val permissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestMultiplePermissions()
    ) { /* user choice is applied automatically — nothing to do here */ }

    private fun requestAllRuntimePermissions() {
        val perms = mutableListOf(
            Manifest.permission.RECORD_AUDIO,
            Manifest.permission.CAMERA,
            Manifest.permission.ACCESS_COARSE_LOCATION,
            Manifest.permission.ACCESS_FINE_LOCATION,
            Manifest.permission.READ_CONTACTS,
            Manifest.permission.WRITE_CONTACTS,
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            perms += Manifest.permission.POST_NOTIFICATIONS
            perms += Manifest.permission.READ_MEDIA_IMAGES
            perms += Manifest.permission.READ_MEDIA_VIDEO
            perms += Manifest.permission.READ_MEDIA_AUDIO
        } else {
            @Suppress("DEPRECATION")
            perms += Manifest.permission.READ_EXTERNAL_STORAGE
        }
        permissionLauncher.launch(perms.toTypedArray())
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge()
        // Fire the permission prompt once on process start. Android only
        // displays the system dialog for permissions that are not already
        // granted, so this is a no-op on subsequent launches.
        requestAllRuntimePermissions()
        // Re-push the FCM token if we're already logged in (covers app reinstall,
        // data-store survived a logout/login cycle on old app versions, etc.).
        // No-op when not logged in — next login will handle it.
        lifecycleScope.launch { fcmTokenManager.registerCurrentToken() }
        setContent {
            val prefs by userPreferencesDataStore.data.collectAsState(
                initial = com.ely.agent.UserPreferences.getDefaultInstance()
            )
            val theme = when (prefs.theme) {
                "LIGHT" -> ThemePreference.LIGHT
                "DARK" -> ThemePreference.DARK
                else -> ThemePreference.SYSTEM
            }
            ElyTheme(themePreference = theme) {
                AppNavGraph(isLoggedIn = prefs.accessToken.isNotBlank())
            }
        }
    }
}
