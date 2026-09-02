# Moshi
-keep class com.squareup.moshi.** { *; }
-keepclassmembers class ** {
    @com.squareup.moshi.FromJson *;
    @com.squareup.moshi.ToJson *;
}
# Retrofit
-keepattributes Signature
-keepattributes Exceptions
-keep class retrofit2.** { *; }
# Room
-keep class * extends androidx.room.RoomDatabase
# Firebase
-keep class com.google.firebase.** { *; }
# ELY models
-keep class com.ely.agent.data.remote.dto.** { *; }
-keep class com.ely.agent.core.model.** { *; }
